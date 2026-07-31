"""Music client tests.

The licence filter is the part with consequences: an ad is commercial use, so a
NonCommercial-licensed track rendered into a TikTok ad is a licence breach. It
gets the most coverage here.
"""

from __future__ import annotations

import httpx
import pytest

from shopagent.integrations.music_client import (MockMusicClient, MusicClient,
                                                 MusicError, _licence_slug,
                                                 make_music_client)


def _client(handler, **kw) -> MusicClient:
    return MusicClient(transport=httpx.MockTransport(handler), **kw)


# ------------------------------------------------------------------ licences

def test_licence_slug_extraction():
    assert _licence_slug("http://creativecommons.org/licenses/by-nc-nd/3.0/") == "by-nc-nd"
    assert _licence_slug("https://creativecommons.org/licenses/by/4.0/") == "by"
    assert _licence_slug("https://creativecommons.org/publicdomain/zero/1.0/") == "zero"
    assert _licence_slug("") == ""


def test_noncommercial_tracks_are_excluded(tmp_path):
    """A NonCommercial track in an ad is a licence breach — it must never reach
    the shortlist, however well it matches the query."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [
            {"id": "1", "name": "Perfect Match", "artist_name": "A",
             "duration": 30, "audiodownload": "https://x/1.mp3",
             "license_ccurl": "http://creativecommons.org/licenses/by-nc-nd/3.0/"},
            {"id": "2", "name": "Also NC", "artist_name": "B",
             "duration": 30, "audiodownload": "https://x/2.mp3",
             "license_ccurl": "http://creativecommons.org/licenses/by-nc/3.0/"},
            {"id": "3", "name": "Usable", "artist_name": "C",
             "duration": 30, "audiodownload": "https://x/3.mp3",
             "license_ccurl": "http://creativecommons.org/licenses/by/4.0/"},
        ]})

    tracks = _client(handler, jamendo_id="cid").search("upbeat")
    assert [t["title"] for t in tracks] == ["Usable"]


def test_tracks_without_audio_are_skipped(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [
            {"id": "1", "name": "No File", "artist_name": "A", "duration": 30,
             "license_ccurl": "https://creativecommons.org/licenses/by/4.0/"},
            {"id": "2", "name": "Has File", "artist_name": "B", "duration": 30,
             "audiodownload": "https://x/2.mp3",
             "license_ccurl": "https://creativecommons.org/licenses/by/4.0/"},
        ]})

    assert [t["title"] for t in _client(handler, jamendo_id="cid").search("x")] == ["Has File"]


# -------------------------------------------------------------- providers

def test_requires_at_least_one_provider():
    with pytest.raises(MusicError, match="no music provider configured"):
        MusicClient()


def test_pixabay_only_configuration_works():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "pixabay" in str(request.url)
        return httpx.Response(200, json={"hits": [
            {"id": 7, "tags": "upbeat pop, energetic", "user": "someone",
             "duration": 31, "audio": "https://cdn/7.mp3"},
        ]})

    tracks = _client(handler, pixabay_key="pk").search("upbeat")
    assert tracks[0]["id"] == "pixabay:7"
    assert tracks[0]["title"] == "upbeat pop"  # first tag, trimmed
    assert tracks[0]["source"] == "pixabay"


def test_results_interleave_so_one_provider_cannot_dominate():
    def handler(request: httpx.Request) -> httpx.Response:
        if "pixabay" in str(request.url):
            return httpx.Response(200, json={"hits": [
                {"id": i, "tags": f"pix{i}", "user": "u", "duration": 30,
                 "audio": f"https://cdn/{i}.mp3"} for i in range(1, 6)]})
        return httpx.Response(200, json={"results": [
            {"id": str(i), "name": f"jam{i}", "artist_name": "a", "duration": 30,
             "audiodownload": f"https://x/{i}.mp3",
             "license_ccurl": "https://creativecommons.org/licenses/by/4.0/"}
            for i in range(1, 6)]})

    tracks = _client(handler, pixabay_key="pk", jamendo_id="cid").search("x", limit=4)
    assert [t["source"] for t in tracks] == ["pixabay", "jamendo", "pixabay", "jamendo"]


def test_duplicate_titles_across_providers_are_collapsed():
    def handler(request: httpx.Request) -> httpx.Response:
        if "pixabay" in str(request.url):
            return httpx.Response(200, json={"hits": [
                {"id": 1, "tags": "Same Song", "user": "Artist One",
                 "duration": 30, "audio": "https://cdn/1.mp3"}]})
        return httpx.Response(200, json={"results": [
            {"id": "1", "name": "same song", "artist_name": "artist one",
             "duration": 30, "audiodownload": "https://x/1.mp3",
             "license_ccurl": "https://creativecommons.org/licenses/by/4.0/"}]})

    tracks = _client(handler, pixabay_key="pk", jamendo_id="cid").search("x")
    assert len(tracks) == 1


def test_search_failure_raises_rather_than_returning_empty():
    """Silently returning [] would look like 'no matching music' and send the
    agent down a wrong path."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(MusicError, match="jamendo search failed"):
        _client(handler, jamendo_id="cid").search("x")


def test_download_writes_the_file(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".mp3"):
            return httpx.Response(200, content=b"ID3fake-audio-bytes")
        return httpx.Response(200, json={"results": []})

    client = _client(handler, jamendo_id="cid")
    dest = client.download({"title": "t", "url": "https://x/1.mp3"},
                           tmp_path / "nested" / "track.mp3")
    assert dest.read_bytes() == b"ID3fake-audio-bytes"


def test_download_failure_raises(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = _client(handler, jamendo_id="cid")
    with pytest.raises(MusicError, match="download failed"):
        client.download({"title": "t", "url": "https://x/1.mp3"}, tmp_path / "t.mp3")


# ------------------------------------------------------------------- mock

def test_mock_search_is_deterministic_and_query_sensitive():
    cj = MockMusicClient()
    assert cj.search("cozy sleep") == MockMusicClient().search("cozy sleep")
    assert cj.search("cozy sleep bed")[0]["title"] == "Soft Lo-Fi Cuddle"
    assert cj.search("viral punchy beat")[0]["title"] == "Deep House Scroll"


def test_mock_search_respects_limit():
    assert len(MockMusicClient().search("anything", limit=2)) == 2


def test_mock_download_writes_a_real_playable_wav(tmp_path):
    client = MockMusicClient()
    track = client.search("upbeat")[0]
    dest = client.download(track, tmp_path / "bed.wav")
    raw = dest.read_bytes()
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"
    assert len(raw) > 44  # header plus actual sample data
    assert client.downloads == [(track["id"], dest)]


# ----------------------------------------------------------------- factory

def test_factory_returns_mock_in_dry_run(cfg, monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "cid")
    assert isinstance(make_music_client(cfg), MockMusicClient)


def test_factory_returns_live_when_configured(cfg, monkeypatch):
    cfg.mode = "live"
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "cid")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    assert isinstance(make_music_client(cfg), MusicClient)


def test_factory_falls_back_to_mock_without_keys(cfg, monkeypatch):
    cfg.mode = "live"
    for var in ("JAMENDO_CLIENT_ID", "PIXABAY_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert isinstance(make_music_client(cfg), MockMusicClient)
