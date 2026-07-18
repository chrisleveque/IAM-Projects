from pathlib import Path

from fitagent.media.music import library, pick_track, track_mood


def _touch(directory: Path, *names: str) -> None:
    for name in names:
        (directory / name).write_bytes(b"")


def test_track_mood_parsing(tmp_path):
    _touch(tmp_path, "epic__rise.mp3", "plain.mp3")
    tracks = library(tmp_path)
    moods = {t.name: track_mood(t) for t in tracks}
    assert moods["epic__rise.mp3"] == "epic"
    assert moods["plain.mp3"] == ""


def test_pick_prefers_mood_and_rotation(tmp_path):
    _touch(tmp_path, "epic__a.mp3", "epic__b.mp3", "dark__c.mp3")
    first = pick_track(tmp_path, "epic")
    assert track_mood(first) == "epic"
    second = pick_track(tmp_path, "epic", exclude=[str(first)])
    assert track_mood(second) == "epic" and second != first


def test_pick_falls_back_across_moods(tmp_path):
    _touch(tmp_path, "dark__c.mp3")
    assert pick_track(tmp_path, "epic") is not None


def test_empty_library_returns_none(tmp_path):
    assert pick_track(tmp_path, "epic") is None
    assert pick_track(tmp_path / "missing", "epic") is None
