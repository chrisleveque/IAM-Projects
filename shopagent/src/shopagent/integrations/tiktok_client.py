"""TikTok Content Posting API client (draft upload only) + in-process mock.

    upload_draft(video_path, caption) -> dict
    get_publish_status(publish_id) -> dict

WHY DRAFTS AND NOT DIRECT POSTING. The Content Posting API has two modes.
Direct Post publishes straight to the profile but requires passing a TikTok
audit, and TikTok rejects audit submissions from apps that read as internal
tools or side projects — which this is. Until an app passes, every direct post
is forced to SELF_ONLY visibility, i.e. nobody sees it. Draft upload
(``MEDIA_UPLOAD``, "upload to inbox") needs no audit: the video lands in the
operator's TikTok drafts and they publish it from the app.

That limitation is a good fit rather than a workaround. The operator adds a
Commercial Music Library track (the thing that makes a Business-account ad
legal, and which no API exposes), writes the final caption with whatever sound
is trending, and posts. The human step is where the human judgment belongs.

Auth: an OAuth refresh token from the app's authorization flow is exchanged for
~24h access tokens, cached in gitignored .tiktok_token.json.

NOTE: written against developers.tiktok.com docs; the upload flow should be
reconfirmed against a live app before switching to mode: live.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from ..config import AppConfig
from . import write_private

BASE_URL = "https://open.tiktokapis.com/v2"
TOKEN_URL = f"{BASE_URL}/oauth/token/"
INBOX_INIT_URL = f"{BASE_URL}/post/publish/inbox/video/init/"
STATUS_URL = f"{BASE_URL}/post/publish/status/fetch/"

# TikTok requires the whole file in one part below this size; chunked upload
# above it. Ads from stills land far under it, so single-part is the only path
# implemented — anything larger raises rather than silently truncating.
MAX_SINGLE_PART = 64 * 1024 * 1024


class TikTokError(RuntimeError):
    pass


class TikTokAuth:
    """Refresh-token flow with a file cache, mirroring LWAAuth in
    amazon_client. Access tokens live ~24h; refresh 5 minutes early."""

    def __init__(self, client_key: str, client_secret: str, refresh_token: str,
                 token_cache: Path, http):
        self._client_key = client_key
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._token_cache = token_cache
        self._http = http
        self._token: str | None = None

    def _load_cached_token(self) -> str | None:
        try:
            data = json.loads(self._token_cache.read_text(encoding="utf-8"))
            expires = datetime.fromisoformat(data["expires_at"])
            if expires > datetime.now(timezone.utc) + timedelta(minutes=5):
                return data["token"]
        except (OSError, ValueError, KeyError):
            pass
        return None

    def _fetch_token(self) -> str:
        response = self._http.post(
            TOKEN_URL,
            data={"client_key": self._client_key,
                  "client_secret": self._client_secret,
                  "grant_type": "refresh_token",
                  "refresh_token": self._refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        if response.status_code != 200:
            raise TikTokError(
                f"TikTok token request failed ({response.status_code}): "
                f"{response.text[:300]}")
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            # never echo the payload itself: a partial token response can
            # carry a rotated refresh_token, and this message lands in the
            # approvals error column and terminal output
            raise TikTokError(
                "no access_token in token response "
                f"(fields: {sorted(payload)}, "
                f"error: {payload.get('error_description') or payload.get('error') or 'none'})")
        expires_in = int(payload.get("expires_in", 86400))
        try:
            write_private(self._token_cache, json.dumps({
                "token": token,
                "expires_at": (datetime.now(timezone.utc)
                               + timedelta(seconds=expires_in)).isoformat(),
            }))
        except OSError:
            pass  # a non-writable cache is a slowdown, not a failure
        return token

    def token(self) -> str:
        if self._token is None:
            self._token = self._load_cached_token() or self._fetch_token()
        return self._token

    def invalidate(self) -> None:
        self._token = None
        self._token_cache.unlink(missing_ok=True)


class TikTokClient:
    def __init__(self, client_key: str, client_secret: str, refresh_token: str,
                 token_cache: Path, transport: httpx.BaseTransport | None = None,
                 timeout: float = 120.0):
        self._http = httpx.Client(timeout=timeout, transport=transport,
                                  follow_redirects=True)
        self._auth = TikTokAuth(client_key, client_secret, refresh_token,
                                Path(token_cache), self._http)

    def _post(self, url: str, payload: dict, retry: bool = True) -> dict:
        response = self._http.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {self._auth.token()}",
                     "Content-Type": "application/json; charset=UTF-8"})
        if response.status_code == 401 and retry:
            self._auth.invalidate()
            return self._post(url, payload, retry=False)
        if response.status_code >= 400:
            raise TikTokError(f"{url} failed ({response.status_code}): "
                              f"{response.text[:300]}")
        body = response.json()
        error = body.get("error") or {}
        # TikTok returns HTTP 200 with an error object for most failures
        if error.get("code") not in (None, "", "ok"):
            raise TikTokError(f"{error.get('code')}: {error.get('message')}")
        return body.get("data") or {}

    def upload_draft(self, video_path: Path | str, caption: str = "") -> dict:
        """Send a video to the account's TikTok drafts. The caption is a
        suggestion the operator can edit before posting."""
        path = Path(video_path)
        if not path.exists():
            raise TikTokError(f"video not found: {path}")
        size = path.stat().st_size
        if size > MAX_SINGLE_PART:
            raise TikTokError(
                f"{path.name} is {size / 1e6:.1f}MB; only single-part upload is "
                f"implemented (limit {MAX_SINGLE_PART / 1e6:.0f}MB)")

        data = self._post(INBOX_INIT_URL, {
            "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                            "chunk_size": size, "total_chunk_count": 1}})
        upload_url = data.get("upload_url")
        publish_id = data.get("publish_id")
        if not upload_url:
            raise TikTokError(f"no upload_url in init response: {data}")

        response = self._http.put(
            upload_url, content=path.read_bytes(),
            headers={"Content-Type": "video/mp4",
                     "Content-Range": f"bytes 0-{size - 1}/{size}"})
        if response.status_code >= 400:
            raise TikTokError(f"upload failed ({response.status_code}): "
                              f"{response.text[:300]}")
        return {
            "publish_id": publish_id,
            "bytes_uploaded": size,
            "caption_suggestion": caption,
            "next_step": ("Open TikTok -> Drafts to add a Commercial Music "
                          "Library sound and post."),
        }

    def get_publish_status(self, publish_id: str) -> dict:
        return self._post(STATUS_URL, {"publish_id": publish_id})


class MockTikTokClient:
    """Records uploads instead of performing them."""

    def __init__(self):
        self.uploads: list[dict] = []

    def upload_draft(self, video_path: Path | str, caption: str = "") -> dict:
        path = Path(video_path)
        if not path.exists():
            raise TikTokError(f"video not found: {path}")
        record = {
            "publish_id": f"mock-publish-{len(self.uploads) + 1:03d}",
            "bytes_uploaded": path.stat().st_size,
            "caption_suggestion": caption,
            "next_step": ("Open TikTok -> Drafts to add a Commercial Music "
                          "Library sound and post."),
            "note": "mock upload — nothing was sent to TikTok",
        }
        self.uploads.append(record)
        return record

    def get_publish_status(self, publish_id: str) -> dict:
        known = any(u["publish_id"] == publish_id for u in self.uploads)
        return {"status": "PUBLISH_COMPLETE" if known else "NOT_FOUND",
                "publish_id": publish_id}


def make_tiktok_client(cfg: AppConfig):
    import os

    if cfg.tiktok_mode() == "live":
        return TikTokClient(os.environ["TIKTOK_CLIENT_KEY"],
                            os.environ["TIKTOK_CLIENT_SECRET"],
                            os.environ["TIKTOK_REFRESH_TOKEN"],
                            token_cache=cfg.resolve(".tiktok_token.json"))
    return MockTikTokClient()
