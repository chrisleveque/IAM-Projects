"""TikTok Content Posting API client tests.

Only draft upload is implemented — Direct Post needs an audit TikTok does not
grant to internal tools — so these cover the two-step init/PUT flow, the token
cache, and the fact that TikTok reports most failures as HTTP 200 with an error
object, which a naive status check would sail straight past.
"""

from __future__ import annotations

import json

import httpx
import pytest

from shopagent.integrations.tiktok_client import (MAX_SINGLE_PART,
                                                  MockTikTokClient,
                                                  TikTokClient, TikTokError,
                                                  make_tiktok_client)


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "ad.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 500)
    return path


def _client(handler, tmp_path) -> TikTokClient:
    return TikTokClient("key", "secret", "refresh",
                        token_cache=tmp_path / ".tiktok_token.json",
                        transport=httpx.MockTransport(handler))


def _ok_handler(state: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth/token/"):
            state["auth"] = state.get("auth", 0) + 1
            return httpx.Response(200, json={"access_token": f"tok{state['auth']}",
                                             "expires_in": 86400})
        if path.endswith("/inbox/video/init/"):
            state["init_body"] = json.loads(request.content)
            state["init_auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json={"data": {
                "publish_id": "pub-123",
                "upload_url": "https://upload.tiktok.test/put"}})
        if "upload" in request.url.host:
            state["put_headers"] = dict(request.headers)
            state["put_bytes"] = len(request.content)
            return httpx.Response(200)
        return httpx.Response(404)
    return handler


def test_upload_draft_runs_init_then_put(tmp_path, video):
    state: dict = {}
    result = _client(_ok_handler(state), tmp_path).upload_draft(video, "caption here")

    assert state["init_body"]["source_info"] == {
        "source": "FILE_UPLOAD", "video_size": video.stat().st_size,
        "chunk_size": video.stat().st_size, "total_chunk_count": 1}
    assert state["init_auth"] == "Bearer tok1"
    assert state["put_bytes"] == video.stat().st_size
    assert state["put_headers"]["content-range"] == f"bytes 0-{video.stat().st_size - 1}/{video.stat().st_size}"
    assert result["publish_id"] == "pub-123"
    assert result["caption_suggestion"] == "caption here"
    assert "Commercial Music Library" in result["next_step"]


def test_token_is_cached_between_clients(tmp_path, video):
    state: dict = {}
    handler = _ok_handler(state)
    _client(handler, tmp_path).upload_draft(video)
    assert state["auth"] == 1
    _client(handler, tmp_path).upload_draft(video)
    assert state["auth"] == 1, "second client re-authenticated instead of using cache"


def test_401_refreshes_the_token_once(tmp_path, video):
    state = {"auth": 0, "init": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token/"):
            state["auth"] += 1
            return httpx.Response(200, json={"access_token": f"tok{state['auth']}",
                                             "expires_in": 86400})
        if request.url.path.endswith("/inbox/video/init/"):
            state["init"] += 1
            if state["init"] == 1:
                return httpx.Response(401, json={"error": {"code": "unauthorized"}})
            return httpx.Response(200, json={"data": {
                "publish_id": "p", "upload_url": "https://upload.tiktok.test/put"}})
        return httpx.Response(200)

    _client(handler, tmp_path).upload_draft(video)
    assert state["auth"] == 2 and state["init"] == 2


def test_error_object_inside_a_200_is_raised(tmp_path, video):
    """TikTok returns HTTP 200 with an error body for most failures — checking
    only the status code would treat this as a successful upload."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token/"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 100})
        return httpx.Response(200, json={"error": {
            "code": "spam_risk_too_many_posts",
            "message": "daily post cap reached"}})

    with pytest.raises(TikTokError, match="daily post cap reached"):
        _client(handler, tmp_path).upload_draft(video)


def test_ok_error_code_is_not_treated_as_a_failure(tmp_path, video):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token/"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 100})
        if request.url.path.endswith("/inbox/video/init/"):
            return httpx.Response(200, json={
                "error": {"code": "ok", "message": ""},
                "data": {"publish_id": "p", "upload_url": "https://upload.tiktok.test/x"}})
        return httpx.Response(200)

    assert _client(handler, tmp_path).upload_draft(video)["publish_id"] == "p"


def test_missing_upload_url_is_reported(tmp_path, video):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token/"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 100})
        return httpx.Response(200, json={"data": {"publish_id": "p"}})

    with pytest.raises(TikTokError, match="no upload_url"):
        _client(handler, tmp_path).upload_draft(video)


def test_upload_failure_on_the_put_is_raised(tmp_path, video):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token/"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 100})
        if request.url.path.endswith("/inbox/video/init/"):
            return httpx.Response(200, json={"data": {
                "publish_id": "p", "upload_url": "https://upload.tiktok.test/put"}})
        return httpx.Response(413, text="too large")

    with pytest.raises(TikTokError, match="upload failed"):
        _client(handler, tmp_path).upload_draft(video)


def test_token_request_failure_is_explained(tmp_path, video):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="invalid_grant")

    with pytest.raises(TikTokError, match="token request failed"):
        _client(handler, tmp_path).upload_draft(video)


def test_missing_video_is_caught_before_any_request(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not have made a request")

    with pytest.raises(TikTokError, match="video not found"):
        _client(handler, tmp_path).upload_draft(tmp_path / "nope.mp4")


def test_oversized_file_is_rejected_rather_than_truncated(tmp_path, monkeypatch):
    big = tmp_path / "big.mp4"
    big.write_bytes(b"x" * 100)
    monkeypatch.setattr("shopagent.integrations.tiktok_client.MAX_SINGLE_PART", 50)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not have made a request")

    with pytest.raises(TikTokError, match="single-part upload"):
        _client(handler, tmp_path).upload_draft(big)


# -------------------------------------------------------------------- mock

def test_mock_records_uploads(tmp_path, video):
    client = MockTikTokClient()
    result = client.upload_draft(video, "hello")
    assert result["publish_id"] == "mock-publish-001"
    assert result["bytes_uploaded"] == video.stat().st_size
    assert "mock upload" in result["note"]
    assert client.get_publish_status("mock-publish-001")["status"] == "PUBLISH_COMPLETE"
    assert client.get_publish_status("unknown")["status"] == "NOT_FOUND"


def test_mock_still_checks_the_file_exists(tmp_path):
    with pytest.raises(TikTokError, match="video not found"):
        MockTikTokClient().upload_draft(tmp_path / "nope.mp4")


def test_factory_respects_mode(cfg, monkeypatch):
    for var in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN"):
        monkeypatch.setenv(var, "x")
    assert isinstance(make_tiktok_client(cfg), MockTikTokClient)  # dry_run
    cfg.mode = "live"
    assert isinstance(make_tiktok_client(cfg), TikTokClient)
    monkeypatch.delenv("TIKTOK_REFRESH_TOKEN")
    assert isinstance(make_tiktok_client(cfg), MockTikTokClient)  # partial creds
