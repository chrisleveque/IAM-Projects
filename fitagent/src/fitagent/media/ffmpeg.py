"""Thin subprocess wrapper around ffmpeg/ffprobe.

Everything in the media pipeline shells out to ffmpeg — no moviepy. All
commands log their full stderr to a per-run log file so failed renders are
diagnosable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class FFmpegMissingError(RuntimeError):
    pass


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def require_ffmpeg() -> str:
    path = ffmpeg_path()
    if not path or not shutil.which("ffprobe"):
        raise FFmpegMissingError(
            "ffmpeg/ffprobe not found on PATH. Install it first, e.g. "
            "`sudo apt-get install -y ffmpeg` (Debian/Ubuntu) or "
            "`brew install ffmpeg` (macOS)."
        )
    return path


def run_ffmpeg(args: list[str], log_path: Path | None = None,
               cwd: Path | None = None) -> None:
    """Run ffmpeg with the given args (no leading 'ffmpeg'). Raises on failure
    with the tail of stderr, and appends full output to log_path if given."""
    cmd = [require_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if log_path is not None:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("$ " + " ".join(cmd) + "\n" + proc.stderr + "\n")
    if proc.returncode != 0:
        tail = proc.stderr.strip()[-2000:]
        raise RuntimeError(f"ffmpeg failed (rc={proc.returncode}): {tail}")


def probe(path: Path) -> dict:
    """ffprobe metadata: {'duration_s': float, 'width': int, 'height': int,
    'has_video': bool, 'has_audio': bool}."""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {proc.stderr.strip()[-500:]}")
    data = json.loads(proc.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or 0)
    return {
        "duration_s": duration,
        "width": int(video["width"]) if video else 0,
        "height": int(video["height"]) if video else 0,
        "has_video": video is not None,
        "has_audio": audio is not None,
    }


def _audio_codec(out_path: Path) -> list[str]:
    return (["-c:a", "libmp3lame", "-q:a", "4"] if out_path.suffix == ".mp3"
            else ["-c:a", "pcm_s16le"])


def make_silence(out_path: Path, seconds: float, log_path: Path | None = None) -> Path:
    run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                "-t", f"{seconds:.3f}", *_audio_codec(out_path), str(out_path)],
               log_path)
    return out_path


def make_tone(out_path: Path, seconds: float, freq: int = 220,
              log_path: Path | None = None) -> Path:
    """Low sine tone — stands in for a voiceover in mock TTS."""
    run_ffmpeg(["-f", "lavfi", "-i", f"sine=frequency={freq}:sample_rate=48000",
                "-t", f"{seconds:.3f}", "-af", "volume=0.3",
                *_audio_codec(out_path), str(out_path)], log_path)
    return out_path


def make_test_clip(out_path: Path, seconds: float, width: int, height: int,
                   fps: int = 30, hue: int = 0, log_path: Path | None = None) -> Path:
    """Generated test-pattern clip — the mock stock provider's 'footage'.
    hue rotates the colors so different mock clips are distinguishable."""
    run_ffmpeg(["-f", "lavfi",
                "-i", f"testsrc2=duration={seconds:.3f}:size={width}x{height}:rate={fps}",
                "-vf", f"hue=h={hue % 360}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                "-pix_fmt", "yuv420p", str(out_path)], log_path)
    return out_path
