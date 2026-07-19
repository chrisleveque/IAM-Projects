"""Long-form assembly: normalize each visual slot, concat, mix voiceover with
ducked music, burn captions — all via ffmpeg.

Renders are two-pass by design: slots are normalized to uniform intermediate
files (so the concat demuxer can join them losslessly), then a single final
pass does the audio graph + subtitle burn + delivery encode. This is far more
robust than one giant filtergraph across dozens of inputs.
"""

from __future__ import annotations

from pathlib import Path

from .ffmpeg import probe, run_ffmpeg
from .footage import VisualSlot

# subtle "cinematic" grade per mood; keys match the visual director's moods
GRADES = {
    "gritty": "eq=contrast=1.08:saturation=0.78:brightness=-0.02",
    "dark": "eq=contrast=1.10:saturation=0.70:brightness=-0.04",
    "epic": "eq=contrast=1.06:saturation=0.92",
    "calm": "eq=contrast=1.02:saturation=0.85",
    "": "eq=contrast=1.06:saturation=0.82",
}


def render_slot(slot: VisualSlot, out_path: Path, width: int, height: int,
                fps: int, log_path: Path | None = None) -> Path:
    """Normalize one slot: loop the clip if it's shorter than the slot, trim
    to length, scale/crop to frame, apply the mood grade."""
    grade = GRADES.get(slot.mood, GRADES[""])
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
          f"crop={width}:{height},fps={fps},setsar=1,{grade}")
    run_ffmpeg(["-stream_loop", "-1", "-i", str(slot.clip_path),
                "-t", f"{slot.duration_s:.3f}", "-an",
                "-vf", vf,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", str(out_path)], log_path)
    return out_path


def concat_slots(slot_paths: list[Path], out_path: Path,
                 log_path: Path | None = None) -> Path:
    concat_list = out_path.with_suffix(".txt")
    concat_list.write_text(
        "\n".join(f"file '{p.name}'" for p in slot_paths) + "\n", encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-c", "copy", str(out_path)], log_path)
    return out_path


def finalize(visual: Path, voiceover: Path, music: Path | None, ass: Path | None,
             out_path: Path, audio_cfg, crf: int = 20, workdir: Path | None = None,
             log_path: Path | None = None) -> Path:
    """Final pass: voice loudnorm, music loop + sidechain duck under the
    voice, master loudnorm to the YouTube target, caption burn, delivery
    encode. Paths inside the filtergraph are relative, so run in ``workdir``
    (all inputs must live there) to sidestep escaping issues."""
    cwd = workdir or out_path.parent

    def rel(p: Path | None) -> str:
        return p.name if p is not None and p.parent == cwd else str(p)

    inputs = ["-i", rel(visual), "-i", rel(voiceover)]
    filters = [f"[1:a]aresample=48000,loudnorm=I={audio_cfg.voice_lufs}:TP=-2,"
               f"asplit=2[vo][vo_key]"]
    if music is not None:
        inputs += ["-stream_loop", "-1", "-i", rel(music)]
        filters += [
            f"[2:a]aresample=48000,volume={audio_cfg.music_volume}[mus]",
            f"[mus][vo_key]sidechaincompress=threshold=0.03:ratio={audio_cfg.duck_ratio}"
            f":attack=20:release=500[duck]",
            "[vo][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]",
        ]
        last_audio = "[mix]"
    else:
        filters += ["[vo_key]anullsink", ]
        last_audio = "[vo]"
    filters += [f"{last_audio}loudnorm=I={audio_cfg.final_lufs}:TP=-1.5[aout]"]

    if ass is not None:
        filters += [f"[0:v]subtitles={rel(ass)}[vout]"]
        video_map = "[vout]"
    else:
        video_map = "0:v"

    run_ffmpeg([*inputs,
                "-filter_complex", ";".join(filters),
                "-map", video_map, "-map", "[aout]",
                "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart",
                rel(out_path) if out_path.parent == cwd else str(out_path)],
               log_path, cwd=cwd)
    return out_path


def render_long_form(slots: list[VisualSlot], voiceover: Path, music: Path | None,
                     ass: Path | None, workdir: Path, out_path: Path,
                     video_cfg, audio_cfg, log_path: Path | None = None) -> Path:
    slot_dir = workdir / "slots"
    slot_dir.mkdir(parents=True, exist_ok=True)
    slot_paths = []
    for i, slot in enumerate(slots):
        p = slot_dir / f"slot_{i:03d}.mp4"
        render_slot(slot, p, video_cfg.width, video_cfg.height, video_cfg.fps, log_path)
        slot_paths.append(p)
    visual = concat_slots(slot_paths, slot_dir / "visual.mp4", log_path)
    return finalize(visual, voiceover, music, ass, out_path, audio_cfg,
                    crf=video_cfg.crf, workdir=workdir, log_path=log_path)


def video_meta(path: Path) -> dict:
    meta = probe(path)
    return {"duration_s": meta["duration_s"], "width": meta["width"],
            "height": meta["height"]}
