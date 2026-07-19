"""YouTube Data API v3 upload client (+ mock).

Google libraries live behind the [youtube] extra and are imported lazily so
the rest of fitagent runs without them. Known platform caveats (also
surfaced by `fitagent doctor` and the README):

- An OAuth consent screen in "testing" mode issues refresh tokens that
  expire every 7 days; add yourself as a test user and expect periodic
  re-auth, or publish the app.
- Unverified API projects have uploads LOCKED TO PRIVATE until Google's
  audit passes — plan on uploading private, then flipping visibility once
  the project is verified.
- videos.insert costs 1600 quota units of the default 10,000/day: about 6
  uploads/day maximum.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

UPLOAD_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubeClient:
    mode = "live"

    def __init__(self, client_secrets: Path, token_path: Path):
        self.client_secrets = client_secrets
        self.token_path = token_path

    # ---- auth --------------------------------------------------------------

    def _credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if not self.token_path.exists():
            raise RuntimeError(
                f"no YouTube token at {self.token_path}; run `fitagent auth youtube`")
        creds = Credentials.from_authorized_user_file(str(self.token_path),
                                                      UPLOAD_SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def run_oauth(self) -> None:
        """One-time interactive flow; headless-friendly (prints the URL)."""
        from google_auth_oauthlib.flow import InstalledAppFlow

        if not self.client_secrets.exists():
            raise RuntimeError(
                f"client secrets not found at {self.client_secrets}. Create an "
                "OAuth client ID (Desktop app) in Google Cloud Console with the "
                "YouTube Data API v3 enabled, download the JSON there.")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secrets), UPLOAD_SCOPES)
        creds = flow.run_local_server(port=0, open_browser=False)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")

    # ---- upload ------------------------------------------------------------

    def upload(self, file_path: Path, title: str, description: str,
               tags: list[str], category_id: str, privacy: str) -> dict:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        service = build("youtube", "v3", credentials=self._credentials())
        body = {
            "snippet": {"title": title[:100], "description": description[:4900],
                        "tags": tags[:30], "categoryId": category_id},
            "status": {"privacyStatus": privacy,
                       "selfDeclaredMadeForKids": False},
        }
        media = MediaFileUpload(str(file_path), chunksize=8 * 1024 * 1024,
                                resumable=True, mimetype="video/mp4")
        request = service.videos().insert(part="snippet,status",
                                          body=body, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk()
        return {"video_id": response["id"],
                "url": f"https://youtu.be/{response['id']}"}


class MockYouTubeClient:
    """Dry-run stand-in: writes an upload receipt next to the video file and
    returns a fake video id."""

    mode = "mock"

    def upload(self, file_path: Path, title: str, description: str,
               tags: list[str], category_id: str, privacy: str) -> dict:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        video_id = f"mock-{stamp}"
        receipt = Path(file_path).with_suffix(".upload.json")
        receipt.write_text(json.dumps({
            "mock": True, "video_id": video_id, "file": str(file_path),
            "title": title, "description": description, "tags": tags,
            "category_id": category_id, "privacy": privacy,
            "uploaded_at": stamp,
        }, indent=2), encoding="utf-8")
        return {"video_id": video_id, "url": f"mock://youtube/{video_id}",
                "receipt": str(receipt)}


def make_youtube_client(cfg, preset_name: str | None = None):
    if cfg.youtube_mode(preset_name) != "live":
        return MockYouTubeClient()
    return YouTubeClient(cfg.youtube_client_secrets(),
                         cfg.youtube_token_path(preset_name))
