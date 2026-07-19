"""Burned-in captions: word timings -> .ass subtitles (libass).

The classic motivation-channel look: short uppercase phrase lines with a
per-word karaoke highlight. We own the script and the TTS providers emit
word timings, so no transcription or forced alignment is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .tts import WordTiming

MAX_WORDS_PER_LINE = 4
LINE_BREAK_GAP_S = 0.6   # a silence this long forces a new caption line


@dataclass
class CaptionStyle:
    play_res_x: int = 1920
    play_res_y: int = 1080
    font: str = "DejaVu Sans"
    font_size: int = 88
    # ASS colours are &HAABBGGRR (alpha first, BGR order)
    highlight: str = "&H004DD5FF"    # warm gold — colour a word turns as spoken
    base: str = "&H00FFFFFF"         # white — colour before the word is spoken
    outline: str = "&H00101010"
    alignment: int = 2               # 2 = bottom center, 5 = middle center
    margin_v: int = 120

    @classmethod
    def for_shorts(cls, width: int = 1080, height: int = 1920) -> "CaptionStyle":
        return cls(play_res_x=width, play_res_y=height, font_size=96,
                   alignment=5, margin_v=0)


def group_words(words: list[WordTiming]) -> list[list[WordTiming]]:
    """Group words into caption lines: cap the word count and break on
    audible pauses so lines track the delivery."""
    lines: list[list[WordTiming]] = []
    current: list[WordTiming] = []
    for w in words:
        if current:
            gap = w.start_s - current[-1].end_s
            if len(current) >= MAX_WORDS_PER_LINE or gap >= LINE_BREAK_GAP_S:
                lines.append(current)
                current = []
        current.append(w)
    if current:
        lines.append(current)
    return lines


def _ts(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(words: list[WordTiming], style: CaptionStyle | None = None,
              offset_s: float = 0.0) -> str:
    """Render an ASS document. ``offset_s`` shifts all times (used when
    cutting shorts out of the master timeline)."""
    style = style or CaptionStyle()
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {style.play_res_x}
PlayResY: {style.play_res_y}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{style.font},{style.font_size},{style.highlight},{style.base},{style.outline},&H96000000,-1,0,0,0,100,100,1,0,1,5,2,{style.alignment},60,60,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for line in group_words(words):
        start = line[0].start_s - offset_s
        end = line[-1].end_s - offset_s
        if end <= 0:
            continue
        parts = []
        for w in line:
            centis = max(int(round((w.end_s - w.start_s) * 100)), 1)
            parts.append(f"{{\\k{centis}}}{_escape(w.word.upper())}")
        events.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{' '.join(parts)}")
    return header + "\n".join(events) + "\n"


def write_ass(words: list[WordTiming], out_path: Path,
              style: CaptionStyle | None = None, offset_s: float = 0.0) -> Path:
    out_path.write_text(build_ass(words, style, offset_s), encoding="utf-8")
    return out_path
