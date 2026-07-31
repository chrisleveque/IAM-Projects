"""JSON2Video client tests.

build_movie is pure, so its shape is pinned exactly — that JSON is also what
the executor's repair loop hands to the model, so shape drift matters twice.
The HTTP flow is tested against a stub transport: create → poll → download,
plus every error surface the repair loop depends on receiving as
JSON2VideoError text.
"""

from __future__ import annotations

import json

import httpx
import pytest

from shopagent.integrations.json2video_client import (JSON2VideoClient,
                                                      JSON2VideoError,
                                                      MockJSON2VideoClient,
                                                      build_movie,
                                                      make_json2video_client)

SCRIPT = {"hook": "Your dog eats way too fast",
          "shots": ["Slows meals down", "Grips the tub", "Rinse and reuse"],
          "cta": "Link in bio"}
URLS = [f"https://cdn.test/p{i}.jpg" for i in range(3)]


# --------------------------------------------------------------- build_movie

def test_movie_is_vertical_with_one_scene_per_photo_plus_end_card():
    movie = build_movie(SCRIPT, URLS, brand_name="FurrFlow")
    assert (movie["width"], movie["height"]) == (1080, 1920)
    assert len(movie["scenes"]) == 4  # 3 photos + brand card
    image_sources = [s["elements"][0]["src"] for s in movie["scenes"][:3]]
    assert image_sources == URLS


def test_hook_rides_scene_one_and_cta_rides_the_end_card():
    movie = build_movie(SCRIPT, URLS, brand_name="FurrFlow")
    first_texts = [e["text"] for e in movie["scenes"][0]["elements"]
                   if e["type"] == "text"]
    assert SCRIPT["hook"] in first_texts
    end_texts = [e["text"] for e in movie["scenes"][-1]["elements"]
                 if e["type"] == "text"]
    assert "FurrFlow" in end_texts and "Link in bio" in end_texts


def test_no_brand_and_no_cta_means_no_end_card():
    movie = build_movie({"shots": ["a"]}, URLS[:1], brand_name="")
    assert len(movie["scenes"]) == 1


def test_scene_count_capped_by_max_seconds():
    movie = build_movie({"shots": ["a"] * 12}, URLS * 4, brand_name="",
                        seconds_per_shot=3.0, max_seconds=9.0)
    assert len(movie["scenes"]) == 3


def test_music_url_becomes_a_movie_level_audio_element():
    movie = build_movie(SCRIPT, URLS, music_url="https://audio.test/track.mp3",
                        brand_name="")
    assert movie["elements"][0]["type"] == "audio"
    assert movie["elements"][0]["src"] == "https://audio.test/track.mp3"
    assert "elements" not in build_movie(SCRIPT, URLS, brand_name="")


def test_voiceover_adds_voice_elements_per_caption():
    movie = build_movie(SCRIPT, URLS, voiceover=True, brand_name="")
    voices = [e for s in movie["scenes"] for e in s["elements"]
              if e["type"] == "voice"]
    # each caption is narrated with its scene, and the CTA with the end card
    assert [v["text"] for v in voices] == SCRIPT["shots"] + [SCRIPT["cta"]]
    silent = build_movie(SCRIPT, URLS, voiceover=False, brand_name="")
    assert not [e for s in silent["scenes"] for e in s["elements"]
                if e["type"] == "voice"]


def test_accent_color_is_css_hex_not_ffmpeg_hex():
    """config stores ffmpeg's 0xRRGGBB; their API wants CSS #RRGGBB."""
    movie = build_movie(SCRIPT, URLS, accent_color="0x5BC8AC")
    hook = next(e for e in movie["scenes"][0]["elements"] if e["type"] == "text")
    assert hook["settings"]["background-color"] == "#5BC8AC"


def test_empty_image_list_is_a_clear_error():
    with pytest.raises(JSON2VideoError, match="no image urls"):
        build_movie(SCRIPT, [])


def test_transitions_start_from_the_second_scene():
    movie = build_movie(SCRIPT, URLS, brand_name="FurrFlow")
    assert "transition" not in movie["scenes"][0]
    assert all("transition" in s for s in movie["scenes"][1:])


# ---------------------------------------------------------------- HTTP flow

def _client(handler, **kw) -> JSON2VideoClient:
    return JSON2VideoClient("key-123", transport=httpx.MockTransport(handler),
                            poll_interval=0.0, **kw)


def _flow_handler(state: dict, polls_until_done: int = 2):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "key-123"
        if request.method == "POST":
            state["movie"] = json.loads(request.content)
            return httpx.Response(200, json={"success": True, "project": "prj42"})
        if request.url.host == "cdn.render.test":
            return httpx.Response(200, content=b"mp4-bytes")
        state["polls"] = state.get("polls", 0) + 1
        assert request.url.params["project"] == "prj42"
        if state["polls"] < polls_until_done:
            return httpx.Response(200, json={"movie": {"status": "running"}})
        return httpx.Response(200, json={"movie": {
            "status": "done", "url": "https://cdn.render.test/prj42.mp4",
            "duration": 12.4, "credits": 62}})
    return handler


def test_render_creates_polls_and_downloads(tmp_path):
    state: dict = {}
    movie = build_movie(SCRIPT, URLS)
    result = _client(_flow_handler(state)).render(movie, tmp_path / "ad.mp4")
    assert state["movie"]["scenes"]  # the movie JSON went over the wire
    assert state["polls"] == 2
    assert (tmp_path / "ad.mp4").read_bytes() == b"mp4-bytes"
    assert result["project"] == "prj42"
    assert result["credits"] == 62


def test_render_error_status_carries_the_api_message(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"success": True, "project": "p"})
        return httpx.Response(200, json={"movie": {
            "status": "error", "message": "Invalid property 'zoom' in element 1"}})

    with pytest.raises(JSON2VideoError, match="Invalid property 'zoom'"):
        _client(handler).render(build_movie(SCRIPT, URLS), tmp_path / "x.mp4")


def test_rejected_movie_at_create_time_raises_with_message(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False,
                                         "message": "scenes must not be empty"})

    with pytest.raises(JSON2VideoError, match="scenes must not be empty"):
        _client(handler).render(build_movie(SCRIPT, URLS), tmp_path / "x.mp4")


def test_http_error_raises_with_status_and_message(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "quota exceeded"})

    with pytest.raises(JSON2VideoError, match=r"\(429\): quota exceeded"):
        _client(handler).render(build_movie(SCRIPT, URLS), tmp_path / "x.mp4")


def test_poll_timeout_is_bounded(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"success": True, "project": "p"})
        return httpx.Response(200, json={"movie": {"status": "running"}})

    client = _client(handler, poll_timeout=0.05)
    with pytest.raises(JSON2VideoError, match="timed out"):
        client.render(build_movie(SCRIPT, URLS), tmp_path / "x.mp4")


def test_done_without_a_url_is_an_error(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"success": True, "project": "p"})
        return httpx.Response(200, json={"movie": {"status": "done"}})

    with pytest.raises(JSON2VideoError, match="without a video url"):
        _client(handler).render(build_movie(SCRIPT, URLS), tmp_path / "x.mp4")


def test_check_auth_distinguishes_bad_key_from_ok():
    def rejecting(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "bad key"})

    with pytest.raises(JSON2VideoError, match="API key rejected"):
        _client(rejecting).check_auth()

    def accepting(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "movie": {}})

    assert _client(accepting).check_auth() is True


def test_empty_api_key_refuses_to_construct():
    with pytest.raises(JSON2VideoError, match="empty"):
        JSON2VideoClient("")


# --------------------------------------------------------------------- mock

def test_mock_records_movies_and_writes_a_stub(tmp_path):
    client = MockJSON2VideoClient()
    result = client.render(build_movie(SCRIPT, URLS), tmp_path / "ad.mp4")
    assert (tmp_path / "ad.mp4").exists()
    assert client.movies[0]["scenes"]
    assert result["project"] == "mock-001"


def test_mock_fail_times_simulates_repairable_errors(tmp_path):
    client = MockJSON2VideoClient(fail_times=2)
    for _ in range(2):
        with pytest.raises(JSON2VideoError, match="Invalid property"):
            client.render(build_movie(SCRIPT, URLS), tmp_path / "ad.mp4")
    assert client.render(build_movie(SCRIPT, URLS), tmp_path / "ad.mp4")


# ------------------------------------------------------------------ factory

def test_factory_matches_render_engine(cfg, monkeypatch):
    monkeypatch.delenv("JSON2VIDEO_API_KEY", raising=False)
    assert isinstance(make_json2video_client(cfg), MockJSON2VideoClient)
    monkeypatch.setenv("JSON2VIDEO_API_KEY", "k")
    assert isinstance(make_json2video_client(cfg), JSON2VideoClient)
    cfg.video.engine = "ffmpeg"
    assert isinstance(make_json2video_client(cfg), MockJSON2VideoClient)
