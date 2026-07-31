"""ffmpeg-backed vertical video rendering and editing.

Two jobs:

1. **Build** an ad from still product photos — the dropshipping format: a
   sequence of shots with a slow Ken Burns push, a hook across the opening, a
   caption per shot, and a music bed. `render_slideshow`.
2. **Edit** footage the operator already has — trim, restyle captions, swap the
   audio. `trim`, `add_captions`, `swap_audio`.

Everything shells out to ffmpeg rather than going through a Python wrapper:
ffmpeg is a hard requirement either way, and a wrapper would add a second thing
to keep working across Windows and Linux without removing the first.

Two portability traps handled here, both of which bite on Windows:

- **Text is passed via `textfile=`, never inline.** drawtext's inline `text=`
  needs `:`, `'`, `%` and `\\` escaped, and product copy is full of them. A file
  sidesteps the whole class of bug.
- **Filter paths get colons escaped and separators normalised.** `C:\\x\\y.txt`
  inside a filtergraph parses as an argument separator without it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

# Candidates in preference order; the first that exists wins. A bold face reads
# far better under a semi-transparent box at phone size.
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)

CAPTION_WRAP = 26  # characters per line at font_size_caption on a 1080 frame
HOOK_WRAP = 18

# How much larger than the output frame each still is scaled, to leave room for
# the camera move. 1.15 gives ~160px of travel at 1080 wide — a gentle drift.
PAN_OVERSAMPLE = 1.15

# Motion comes from an animated `crop` window, NOT from `zoompan`. zoompan
# rescales its source on every output frame, which measured at 45-90s for a
# single 2.8s shot here; an animated crop is a memory offset and measured at
# 1.5s for the same shot. The tradeoff is pan-only (a crop's output size has to
# stay constant, so it cannot zoom), which reads the same at phone size.
PAN_MOVES = ("left_right", "top_bottom", "right_left", "bottom_top")


class RenderError(RuntimeError):
    pass


@dataclass
class Script:
    """What the content agent writes and the renderer consumes."""
    hook: str = ""
    shots: list[str] = field(default_factory=list)
    cta: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Script":
        shots = data.get("shots") or []
        # accept either ["text", ...] or [{"text": ...}, ...]
        normalized = [s.get("text", "") if isinstance(s, dict) else str(s)
                      for s in shots]
        return cls(hook=data.get("hook", ""),
                   shots=[s for s in normalized if s.strip()],
                   cta=data.get("cta", ""))


# --------------------------------------------------------------- ffmpeg glue

def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _require_ffmpeg() -> None:
    if not ffmpeg_available():
        raise RenderError(
            "ffmpeg and ffprobe are required to render video but were not found "
            "on PATH.\n"
            "  Windows:  winget install Gyan.FFmpeg   (then open a NEW terminal)\n"
            "  macOS:    brew install ffmpeg\n"
            "  Linux:    sudo apt install ffmpeg")


def _run(args: list[str]) -> None:
    try:
        result = subprocess.run(args, capture_output=True, text=True)
    except OSError as exc:
        raise RenderError(f"could not start ffmpeg: {exc}") from exc
    if result.returncode != 0:
        # ffmpeg's real complaint is in the last few stderr lines; the rest is banner
        tail = "\n".join((result.stderr or "").strip().splitlines()[-12:])
        raise RenderError(f"ffmpeg failed (exit {result.returncode}):\n{tail}")


def probe(path: Path | str) -> dict:
    """Return {width, height, duration, has_audio} for a rendered file."""
    _require_ffmpeg()
    args = ["ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(path)]
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RenderError(f"ffprobe failed for {path}: {exc}") from exc
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "duration": float(payload.get("format", {}).get("duration") or 0.0),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def image_size(path: Path | str) -> tuple[int, int]:
    """(width, height) of a still, via ffprobe. Needed before building the
    filtergraph because the fit strategy depends on the source's aspect."""
    _require_ffmpeg()
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
             str(path)], capture_output=True, text=True, check=True)
        width, height = result.stdout.strip().split("x")[:2]
        size = (int(width), int(height))
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise RenderError(f"could not read image dimensions for {path}: {exc}") from exc
    if not all(size):
        # ffprobe exits 0 and reports "0x0" for a corrupt or non-image file;
        # letting that through fails later as an opaque filtergraph error
        raise RenderError(
            f"could not read image dimensions for {path}: not a usable image "
            "(a supplier URL that returned an error page will look like this)")
    return size


def find_font(override: str = "") -> str:
    if override:
        if not Path(override).exists():
            raise RenderError(f"configured font not found: {override}")
        return override
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise RenderError(
        "no usable font found for captions. Install one (Linux: "
        "`sudo apt install fonts-dejavu`) or set video.font_path in config.yaml.")


def _filter_path(path: Path | str) -> str:
    """Make a path safe to embed in a filtergraph argument.

    Backslashes become forward slashes and the drive colon is escaped, so
    'C:\\Users\\x\\hook.txt' survives as 'C\\:/Users/x/hook.txt'.
    """
    text = str(path).replace("\\", "/")
    return text.replace(":", r"\:")


# ------------------------------------------------------------------ drawtext

def _write_text(text: str, dest: Path, width: int) -> Path:
    wrapped = "\n".join(textwrap.wrap(text.strip(), width=width) or [""])
    dest.write_text(wrapped, encoding="utf-8")
    return dest


def _pan_expr(move: str, duration: float) -> tuple[str, str]:
    """Crop-window offsets for one shot, as (x, y) ffmpeg expressions.

    Direction alternates per shot so a multi-shot ad doesn't feel mechanical.
    """
    progress = f"(t/{duration:.3f})"
    centre_x, centre_y = "(iw-ow)/2", "(ih-oh)/2"
    if move == "left_right":
        return f"(iw-ow)*{progress}", centre_y
    if move == "right_left":
        return f"(iw-ow)*(1-{progress})", centre_y
    if move == "top_bottom":
        return centre_x, f"(ih-oh)*{progress}"
    return centre_x, f"(ih-oh)*(1-{progress})"


def _drawtext(textfile: Path, font: str, size: int, y_expr: str) -> str:
    return (
        f"drawtext=textfile={_filter_path(textfile)}"
        f":fontfile={_filter_path(font)}"
        f":fontsize={size}:fontcolor=white:line_spacing=10"
        f":box=1:boxcolor=black@0.55:boxborderw=24"
        f":x=(w-text_w)/2:y={y_expr}"
    )


def _shot_chain(index: int, image: Path, width: int, height: int,
                over_w: int, over_h: int, duration: float) -> str:
    """Filtergraph for one shot, choosing a fit strategy from the source aspect.

    Supplier photos are usually **square** product-on-white shots. Cover-cropping
    a square into 9:16 discards ~44% of its width, which slices the edges off a
    wide product like a lick mat — the ad then misrepresents what ships. So:

    - Portrait-ish sources cover-crop and pan: real content fills the frame and
      nothing meaningful is lost.
    - Square and landscape sources are *contained* whole over a blurred,
      cover-scaled copy of themselves, drifting gently. Nothing is cropped.
    """
    source_w, source_h = image_size(image)
    source_aspect = source_w / source_h if source_h else 1.0
    target_aspect = width / height

    if source_aspect <= target_aspect * 1.05:
        # setsar=1 matters: concat rejects segments whose sample aspect differs,
        # and scaled stills otherwise inherit the source's SAR.
        pan_x, pan_y = _pan_expr(PAN_MOVES[index % len(PAN_MOVES)], duration)
        return (
            f"[{index}:v]scale={over_w}:{over_h}:force_original_aspect_ratio=increase,"
            f"crop={over_w}:{over_h},"
            f"crop={width}:{height}:x='{pan_x}':y='{pan_y}',"
            f"setsar=1"
        )

    box_w, box_h = int(width * 0.94), int(height * 0.80)
    fit_h = min(box_h, int(box_w * source_h / source_w))
    # keep the drift inside the empty space so the product never leaves frame
    amplitude = max(0, min(50, (height - fit_h) // 4))
    drift = f"+{amplitude}*sin(t*0.9)" if amplitude else ""
    return (
        f"[{index}:v]split=2[bg{index}][fg{index}];"
        f"[bg{index}]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur=40:2,eq=brightness=-0.06[bgb{index}];"
        f"[fg{index}]scale={box_w}:{box_h}:force_original_aspect_ratio=decrease[fgs{index}];"
        f"[bgb{index}][fgs{index}]overlay=x=(W-w)/2:y='(H-h)/2{drift}',"
        f"setsar=1"
    )


# ------------------------------------------------------------------- render

def render_slideshow(images: list[Path | str], script: dict | Script,
                     out_path: Path | str, music_path: Path | str | None = None,
                     *, width: int = 1080, height: int = 1920, fps: int = 30,
                     seconds_per_shot: float = 2.8, max_seconds: float = 34.0,
                     music_volume: float = 0.5, font_path: str = "",
                     font_size_hook: int = 78, font_size_caption: int = 56,
                     work_dir: Path | str | None = None) -> Path:
    """Render a vertical ad from still images. Returns the output path.

    Shot count is capped by ``max_seconds`` — a long image list produces a
    shorter video rather than one nobody watches to the end.
    """
    _require_ffmpeg()
    images = [Path(p) for p in images]
    if not images:
        raise RenderError("no images to render — the product has no photos saved")
    missing = [p for p in images if not p.exists()]
    if missing:
        raise RenderError(f"image files not found: {[str(p) for p in missing]}")

    parsed = script if isinstance(script, Script) else Script.from_dict(script)
    font = find_font(font_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    max_shots = max(1, int(max_seconds // seconds_per_shot))
    images = images[:max_shots]

    work = Path(work_dir) if work_dir else out_path.parent / f".{out_path.stem}_work"
    work.mkdir(parents=True, exist_ok=True)

    over_w = int(width * PAN_OVERSAMPLE)
    over_h = int(height * PAN_OVERSAMPLE)

    args: list[str] = ["ffmpeg", "-y", "-loglevel", "error"]
    for image in images:
        args += ["-loop", "1", "-framerate", str(fps),
                 "-t", f"{seconds_per_shot:.3f}", "-i", str(image)]
    if music_path:
        # loop the bed so a track shorter than the ad still covers it; atrim
        # below cuts it back to exactly the video length
        args += ["-stream_loop", "-1", "-i", str(music_path)]

    chains: list[str] = []
    for index, image in enumerate(images):
        chain = _shot_chain(index, image, width, height, over_w, over_h,
                            seconds_per_shot)
        caption = parsed.shots[index] if index < len(parsed.shots) else ""
        if caption:
            path = _write_text(caption, work / f"caption_{index}.txt", CAPTION_WRAP)
            chain += "," + _drawtext(path, font, font_size_caption, "h*0.72")
        if index == 0 and parsed.hook:
            path = _write_text(parsed.hook, work / "hook.txt", HOOK_WRAP)
            chain += "," + _drawtext(path, font, font_size_hook, "h*0.12")
        if index == len(images) - 1 and parsed.cta:
            path = _write_text(parsed.cta, work / "cta.txt", HOOK_WRAP)
            chain += "," + _drawtext(path, font, font_size_hook, "h*0.42")
        chains.append(chain + f"[v{index}]")

    concat_inputs = "".join(f"[v{i}]" for i in range(len(images)))
    chains.append(f"{concat_inputs}concat=n={len(images)}:v=1:a=0[outv]")

    total = len(images) * seconds_per_shot
    if music_path:
        # atrim, not -shortest: with filter_complex, -shortest does not reliably
        # cut a filtered audio stream, and an overlong track pads the ad with
        # dead air after the last frame.
        fade_at = max(0.0, total - 1.2)
        chains.append(f"[{len(images)}:a]volume={music_volume},"
                      f"atrim=0:{total:.3f},asetpts=N/SR/TB,"
                      f"afade=t=out:st={fade_at:.3f}:d=1.2[outa]")

    args += ["-filter_complex", ";".join(chains), "-map", "[outv]"]
    if music_path:
        args += ["-map", "[outa]", "-c:a", "aac", "-b:a", "128k"]
    args += ["-t", f"{total:.3f}"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             "-r", str(fps), "-movflags", "+faststart", str(out_path)]

    _run(args)
    return out_path


# -------------------------------------------------------------------- edits

def trim(src: Path | str, out_path: Path | str, start: float = 0.0,
         end: float | None = None) -> Path:
    """Cut a clip. Re-encodes rather than stream-copying so the cut lands on the
    requested frame instead of the nearest keyframe."""
    _require_ffmpeg()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ss", f"{start:.3f}"]
    if end is not None:
        if end <= start:
            raise RenderError(f"end ({end}) must be after start ({start})")
        args += ["-to", f"{end:.3f}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-movflags", "+faststart", str(out_path)]
    _run(args)
    return out_path


def swap_audio(src: Path | str, audio: Path | str, out_path: Path | str,
               volume: float = 1.0) -> Path:
    """Replace a clip's audio wholesale — the usual fix when footage was shot
    with unusable room sound, or when a track has to change for licensing."""
    _require_ffmpeg()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-i", str(audio),
          "-filter_complex", f"[1:a]volume={volume}[outa]",
          "-map", "0:v", "-map", "[outa]", "-c:v", "copy", "-c:a", "aac",
          "-shortest", "-movflags", "+faststart", str(out_path)])
    return out_path


def add_captions(src: Path | str, captions: list[dict], out_path: Path | str,
                 *, font_path: str = "", font_size: int = 56,
                 work_dir: Path | str | None = None) -> Path:
    """Burn timed captions into existing footage.

    ``captions`` is [{"text": ..., "start": 0.0, "end": 2.5}, ...]. Burned in
    rather than a sidecar track because TikTok does not read sidecar subtitles.
    """
    _require_ffmpeg()
    if not captions:
        raise RenderError("no captions given")
    font = find_font(font_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(work_dir) if work_dir else out_path.parent / f".{out_path.stem}_work"
    work.mkdir(parents=True, exist_ok=True)

    filters = []
    for index, caption in enumerate(captions):
        text = (caption.get("text") or "").strip()
        if not text:
            continue
        start = float(caption.get("start", 0.0))
        end = float(caption.get("end", start + 2.5))
        if end <= start:
            raise RenderError(f"caption {index} ends ({end}) before it starts ({start})")
        path = _write_text(text, work / f"cap_{index}.txt", CAPTION_WRAP)
        filters.append(_drawtext(path, font, font_size, "h*0.72")
                       + f":enable='between(t,{start:.3f},{end:.3f})'")
    if not filters:
        raise RenderError("every caption was empty")

    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
          "-vf", ",".join(filters), "-c:v", "libx264", "-pix_fmt", "yuv420p",
          "-c:a", "copy", "-movflags", "+faststart", str(out_path)])
    return out_path


# ------------------------------------------------------------------ sourcing

def fetch_images(urls: list[str], dest_dir: Path | str, client=None) -> list[Path]:
    """Download product photos for rendering. Failures are skipped, not fatal —
    a supplier link that 404s shouldn't cost the whole ad."""
    import httpx

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    http = client or httpx.Client(timeout=30.0, follow_redirects=True)
    saved: list[Path] = []
    try:
        for index, url in enumerate(urls):
            suffix = Path(str(url).split("?")[0]).suffix or ".jpg"
            dest = dest_dir / f"img_{index:02d}{suffix}"
            try:
                response = http.get(url)
                response.raise_for_status()
            except Exception:
                continue
            dest.write_bytes(response.content)
            saved.append(dest)
    finally:
        if client is None:
            http.close()
    return saved
