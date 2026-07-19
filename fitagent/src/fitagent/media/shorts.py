"""Vertical Shorts cut from the long-form master timeline.

Each short re-renders from the ORIGINAL source clips (not the finished
16:9 video) so the 9:16 center crop keeps maximum quality, with its own
mid-frame caption track and the same voice/music treatment.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .assemble import concat_slots, finalize, render_slot
from .captions import CaptionStyle, write_ass
from .ffmpeg import run_ffmpeg
from .footage import VisualSlot
from .tts import Voiceover


@dataclass
class ShortWindow:
    segment_ids: list[str]
    start_s: float
    end_s: float
    hook_line: str = ""

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def candidate_windows(candidates: list[dict], voiceover: Voiceover,
                      max_seconds: float) -> list[ShortWindow]:
    """Resolve the scriptwriter's shorts candidates against the real
    timeline, dropping any that exceed the Shorts length cap."""
    windows = []
    for cand in candidates:
        ids = cand.get("segment_ids") or []
        try:
            spans = [voiceover.span_for(sid) for sid in ids]
        except KeyError:
            continue
        if not spans:
            continue
        start, end = min(s.start_s for s in spans), max(s.end_s for s in spans)
        if end - start > max_seconds or end - start < 3:
            continue
        windows.append(ShortWindow(ids, start, end, cand.get("hook_line", "")))
    return windows


def _window_slots(slots: list[VisualSlot], window: ShortWindow) -> list[VisualSlot]:
    """Clip the master slot list to the window (trimming edge slots)."""
    out = []
    for slot in slots:
        start = max(slot.start_s, window.start_s)
        end = min(slot.end_s, window.end_s)
        if end - start < 0.25:
            continue
        out.append(VisualSlot(slot.segment_id, start, end,
                              slot.clip_path, slot.clip, slot.mood))
    return out


def render_short(window: ShortWindow, slots: list[VisualSlot], voiceover: Voiceover,
                 music: Path | None, workdir: Path, out_path: Path,
                 shorts_cfg, audio_cfg, index: int,
                 log_path: Path | None = None) -> Path:
    short_dir = workdir / f"short_{index:02d}"
    short_dir.mkdir(parents=True, exist_ok=True)

    # visuals: re-render the window's slots at 9:16
    slot_paths = []
    for i, slot in enumerate(_window_slots(slots, window)):
        p = short_dir / f"slot_{i:03d}.mp4"
        render_slot(slot, p, shorts_cfg.width, shorts_cfg.height, 30, log_path)
        slot_paths.append(p)
    visual = concat_slots(slot_paths, short_dir / "visual.mp4", log_path)

    # audio: the window's slice of the master voiceover
    voice_cut = short_dir / "voice.wav"
    run_ffmpeg(["-i", str(voiceover.audio_path),
                "-ss", f"{window.start_s:.3f}", "-to", f"{window.end_s:.3f}",
                "-c:a", "pcm_s16le", str(voice_cut)], log_path)

    # captions: window words, re-based to t=0, mid-frame layout
    words = [w for w in voiceover.words
             if w.start_s >= window.start_s - 0.05 and w.end_s <= window.end_s + 0.5]
    ass = write_ass(words, short_dir / "captions.ass",
                    CaptionStyle.for_shorts(shorts_cfg.width, shorts_cfg.height),
                    offset_s=window.start_s)

    return finalize(visual, voice_cut, music, ass, out_path, audio_cfg,
                    crf=20, workdir=short_dir, log_path=log_path)
