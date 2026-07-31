"""JSON2Video render client + in-process mock.

The cloud render engine behind `tiktok.render_video` when JSON2VIDEO_API_KEY
is set (see AppConfig.render_engine). We build a "movie" JSON from the ad
script and product photos, POST it, poll until the render finishes, and
download the mp4. Their motion design (animated text, pan/zoom, transitions,
built-in TTS) is the reason this engine exists — it out-edits the local
ffmpeg renderer.

    build_movie(script, image_urls, cfg-ish knobs) -> dict   (pure, testable)
    render(movie, out_path) -> dict                          (create/poll/download)

Auth: `x-api-key` header. Endpoints: POST /v2/movies to create (returns a
project id), GET /v2/movies?project=... to poll (status ends in 'done' with a
video url, or 'error'). Free tier exists, so a bad movie JSON costs credits,
not money.

NOTE: written against the public docs' documented shape; json2video.com is
unreachable from the dev sandbox, so property names must be reconfirmed on
the first live render (the CJ/Amazon clients shipped the same way). Two nets
catch schema drift: the executor's LLM repair loop fixes field-level
rejections, and any final failure falls back to the ffmpeg engine.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from ..config import AppConfig

BASE_URL = "https://api.json2video.com/v2"

# Their voice element uses Azure TTS voice names; this is a natural US-English
# ad-read voice. Overridable per call.
DEFAULT_VOICE = "en-US-EmmaMultilingualNeural"

POLL_INTERVAL = 3.0
POLL_TIMEOUT = 300.0

# statuses their docs/tutorials show while a render is in flight
IN_FLIGHT = ("not started", "pending", "queued", "running", "rendering",
             "processing", "started")


class JSON2VideoError(RuntimeError):
    pass


def build_movie(script: dict, image_urls: list[str], *,
                width: int = 1080, height: int = 1920,
                seconds_per_shot: float = 3.0, max_seconds: float = 34.0,
                brand_name: str = "", accent_color: str = "#5BC8AC",
                music_url: str = "", voiceover: bool = False,
                voice: str = DEFAULT_VOICE, quality: str = "high") -> dict:
    """Build the movie JSON. Pure function so tests can pin the exact shape
    and the executor's repair loop can hand the whole document to the model.

    One scene per photo: the image cover-fills with a slow zoom, the caption
    animates in over it. The hook rides the first scene, the CTA the closing
    brand-card scene. Voiceover, when on, narrates scene-by-scene so their
    engine paces each line with its scene.
    """
    hook = (script.get("hook") or "").strip()
    cta = (script.get("cta") or "").strip()
    shots = [s.get("text", "") if isinstance(s, dict) else str(s)
             for s in (script.get("shots") or [])]
    shots = [s.strip() for s in shots if s.strip()]
    accent = accent_color.replace("0x", "#")
    if not accent.startswith("#"):
        accent = f"#{accent}"

    max_shots = max(1, int(max_seconds // seconds_per_shot))
    image_urls = list(image_urls)[:max_shots]
    if not image_urls:
        raise JSON2VideoError("no image urls to build a movie from")

    scenes: list[dict] = []
    for index, url in enumerate(image_urls):
        caption = shots[index] if index < len(shots) else ""
        elements: list[dict] = [{
            "type": "image",
            "src": url,
            "zoom": 2 if index % 2 == 0 else -2,  # alternate push in/out
            "duration": seconds_per_shot,
        }]
        if index == 0 and hook:
            elements.append({
                "type": "text",
                "style": "005",  # bold boxed headline preset
                "text": hook,
                "settings": {"font-size": "7vw", "text-align": "center",
                             "background-color": accent, "color": "#FFFFFF"},
                "position": "custom", "x": 60, "y": int(height * 0.12),
                "width": width - 120,
                "duration": seconds_per_shot,
            })
        if caption:
            elements.append({
                "type": "text",
                "style": "003",  # animated subtitle preset
                "text": caption,
                "settings": {"font-size": "5vw", "text-align": "center",
                             "color": "#FFFFFF"},
                "position": "custom", "x": 60, "y": int(height * 0.72),
                "width": width - 120,
                "duration": seconds_per_shot,
            })
            if voiceover:
                elements.append({"type": "voice", "text": caption, "voice": voice})
        scene: dict = {"elements": elements}
        if index > 0:
            scene["transition"] = {"style": "fade", "duration": 0.4}
        scenes.append(scene)

    if brand_name or cta:
        elements = []
        if brand_name:
            elements.append({
                "type": "text", "style": "005", "text": brand_name,
                "settings": {"font-size": "10vw", "text-align": "center",
                             "color": "#FFFFFF"},
                "position": "custom", "x": 60, "y": int(height * 0.40),
                "width": width - 120, "duration": 2,
            })
        if cta:
            elements.append({
                "type": "text", "style": "003", "text": cta,
                "settings": {"font-size": "6vw", "text-align": "center",
                             "color": "#FFFFFF"},
                "position": "custom", "x": 60, "y": int(height * 0.55),
                "width": width - 120, "duration": 2,
            })
            if voiceover:
                elements.append({"type": "voice", "text": cta, "voice": voice})
        scenes.append({
            "background-color": accent,
            "transition": {"style": "fade", "duration": 0.4},
            "elements": elements,
        })

    movie: dict = {
        "resolution": "custom",
        "width": width,
        "height": height,
        "quality": quality,
        "scenes": scenes,
    }
    if music_url:
        # movie-level audio runs under every scene; their engine ducks it
        # automatically beneath voice elements
        movie["elements"] = [{"type": "audio", "src": music_url,
                              "volume": 0.4, "fade-out": 1.5}]
    return movie


class JSON2VideoClient:
    def __init__(self, api_key: str,
                 transport: httpx.BaseTransport | None = None,
                 timeout: float = 60.0,
                 poll_interval: float = POLL_INTERVAL,
                 poll_timeout: float = POLL_TIMEOUT):
        if not api_key:
            raise JSON2VideoError("JSON2VIDEO_API_KEY is empty")
        self._http = httpx.Client(timeout=timeout, transport=transport,
                                  follow_redirects=True,
                                  headers={"x-api-key": api_key})
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    def check_auth(self) -> bool:
        """Cheap doctor probe: any authenticated response (even 'no such
        project') proves the key; a 401/403 disproves it."""
        response = self._http.get(f"{BASE_URL}/movies",
                                  params={"project": "doctor-probe"})
        if response.status_code in (401, 403):
            raise JSON2VideoError(
                f"API key rejected ({response.status_code}); check "
                "JSON2VIDEO_API_KEY")
        return True

    def render(self, movie: dict, out_path: Path | str) -> dict:
        """Create the movie, poll to completion, download the mp4.

        Raises JSON2VideoError with the API's own message on failure — that
        text is what the executor's repair loop reasons over.
        """
        project = self._create(movie)
        status = self._wait(project)
        url = (status.get("url") or status.get("video_url") or "")
        if not url:
            raise JSON2VideoError(f"render finished without a video url: {status}")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        download = self._http.get(url)
        if download.status_code >= 400:
            raise JSON2VideoError(f"video download failed ({download.status_code})")
        out_path.write_bytes(download.content)
        return {"video_path": str(out_path), "project": project,
                "duration": status.get("duration"),
                "credits": status.get("credits") or status.get("credits_used")}

    # ------------------------------------------------------------- internals

    def _create(self, movie: dict) -> str:
        response = self._http.post(f"{BASE_URL}/movies", json=movie)
        payload = self._payload(response)
        project = (payload.get("project")
                   or payload.get("data", {}).get("project", ""))
        if not project:
            raise JSON2VideoError(f"no project id in response: {payload}")
        return project

    def _wait(self, project: str) -> dict:
        deadline = time.monotonic() + self._poll_timeout
        while True:
            response = self._http.get(f"{BASE_URL}/movies",
                                      params={"project": project})
            payload = self._payload(response)
            movie = payload.get("movie") or payload.get("data") or payload
            status = str(movie.get("status", "")).lower()
            if status == "done":
                return movie
            if status == "error":
                raise JSON2VideoError(
                    f"render failed: {movie.get('message') or movie}")
            if status not in IN_FLIGHT and status:
                raise JSON2VideoError(f"unexpected render status {status!r}: {movie}")
            if time.monotonic() >= deadline:
                raise JSON2VideoError(
                    f"render timed out after {self._poll_timeout:.0f}s "
                    f"(project {project})")
            time.sleep(self._poll_interval)

    def _payload(self, response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            message = (payload.get("message") or payload.get("error")
                       or response.text[:300])
            raise JSON2VideoError(
                f"json2video API error ({response.status_code}): {message}")
        if payload.get("success") is False:
            raise JSON2VideoError(
                f"json2video rejected the movie: "
                f"{payload.get('message') or payload}")
        return payload


class MockJSON2VideoClient:
    """Records movie specs and writes a stub mp4, so the executor path is
    testable without network or credits. ``fail_times`` simulates the
    field-rejection errors the repair loop exists for."""

    def __init__(self, fail_times: int = 0,
                 error: str = "Invalid property 'zoom' in element 1"):
        self.movies: list[dict] = []
        self.fail_times = fail_times
        self.error = error

    def check_auth(self) -> bool:
        return True

    def render(self, movie: dict, out_path: Path | str) -> dict:
        self.movies.append(json.loads(json.dumps(movie)))  # deep snapshot
        if self.fail_times > 0:
            self.fail_times -= 1
            raise JSON2VideoError(self.error)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00\x00\x00\x18ftypmp42-mock-json2video")
        return {"video_path": str(out_path),
                "project": f"mock-{len(self.movies):03d}",
                "duration": 12.0, "credits": 60}


def make_json2video_client(cfg: AppConfig):
    if cfg.render_engine() == "json2video":
        return JSON2VideoClient(os.environ.get("JSON2VIDEO_API_KEY", ""))
    return MockJSON2VideoClient()
