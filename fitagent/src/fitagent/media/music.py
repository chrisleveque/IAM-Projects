"""Background music selection from the local library.

Tracks live in assets/music/ and come from the YouTube Audio Library —
explicitly cleared for monetized YouTube use, so there is zero Content ID
risk (the reason we prefer it over third-party free-music APIs). Filenames
encode mood: ``epic__title.mp3``, ``dark__...``, ``calm__...``.
"""

from __future__ import annotations

from pathlib import Path

AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".flac", ".ogg")
KNOWN_MOODS = ("epic", "dark", "gritty", "calm", "uplifting")


def library(music_dir: Path) -> list[Path]:
    if not music_dir.is_dir():
        return []
    return sorted(p for p in music_dir.iterdir()
                  if p.suffix.lower() in AUDIO_EXTS and not p.name.startswith("."))


def track_mood(path: Path) -> str:
    name = path.stem
    if "__" in name:
        return name.split("__", 1)[0].lower()
    return ""


def pick_track(music_dir: Path, mood: str, exclude: list[str] | None = None) -> Path | None:
    """Best track for a mood, avoiding recently used ones. Preference order:
    unused mood match > any mood match > unused any > any at all > None."""
    tracks = library(music_dir)
    if not tracks:
        return None
    excluded = set(exclude or [])
    mood = (mood or "").lower()
    matches = [t for t in tracks if track_mood(t) == mood] if mood else []
    for pool in (
        [t for t in matches if str(t) not in excluded],
        matches,
        [t for t in tracks if str(t) not in excluded],
        tracks,
    ):
        if pool:
            return pool[0]
    return None
