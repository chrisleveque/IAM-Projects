"""Google Veo (Gemini API) video generation client + in-process mock.

Powers `shopagent veo` — UGC-style video ads generated as native-audio clips
(speech included) from text prompts plus a product reference photo. One call
generates one clip (Veo's ceiling is 8 seconds); veo_ads.py stitches clips
into finished ads.

    generate_clip(prompt, ...) -> mp4 bytes        (create/poll/download)

Auth: `x-goog-api-key` header, key from GEMINI_API_KEY (aistudio.google.com).
Endpoints: POST /v1beta/models/{model}:predictLongRunning to create (returns
an operation name), GET /v1beta/{operation} to poll until done, then download
the returned video URI with the same key.

NOTE: written against the public Gemini API docs; the endpoint was not
reachable from the dev sandbox, so response property names must be
reconfirmed on the first live clip (the CJ/Amazon/JSON2Video clients all
shipped the same way). _extract_video_uri tolerates the documented shape
variants for exactly this reason.
"""

from __future__ import annotations

import base64
import time

import httpx

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Veo renders slower than JSON2Video: minutes, not seconds.
POLL_INTERVAL = 10.0
POLL_TIMEOUT = 600.0

# Published per-second-of-output USD rates (video with native audio) as of
# Aug 2026. Estimates only — reconfirm against ai.google.dev/gemini-api/docs/
# pricing before trusting a projected campaign total.
COST_PER_SECOND_USD = {
    "veo-3.1-generate-preview": 0.40,
    "veo-3.1-fast-generate-preview": 0.15,
}


class VeoError(RuntimeError):
    pass


class VeoClient:
    def __init__(self, api_key: str,
                 transport: httpx.BaseTransport | None = None,
                 timeout: float = 120.0,
                 poll_interval: float = POLL_INTERVAL,
                 poll_timeout: float = POLL_TIMEOUT):
        if not api_key:
            raise VeoError("GEMINI_API_KEY is empty")
        self._http = httpx.Client(timeout=timeout, transport=transport,
                                  follow_redirects=True,
                                  headers={"x-goog-api-key": api_key})
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    def check_auth(self) -> bool:
        """Cheap doctor probe: listing models is free and authenticated."""
        response = self._http.get(f"{BASE_URL}/models", params={"pageSize": 1})
        if response.status_code in (401, 403):
            raise VeoError(
                f"API key rejected ({response.status_code}); check GEMINI_API_KEY")
        if response.status_code >= 400:
            raise VeoError(f"Gemini API error ({response.status_code}): "
                           f"{response.text[:300]}")
        return True

    def generate_clip(self, prompt: str, *, model: str,
                      duration: int = 8, aspect_ratio: str = "9:16",
                      resolution: str = "1080p",
                      reference_image: bytes | None = None,
                      reference_mime: str = "image/jpeg") -> bytes:
        """Generate one clip and return the mp4 bytes.

        Raises VeoError with the API's own message on failure — surfaced
        verbatim by the CLI so a rejected parameter names itself.
        """
        instance: dict = {"prompt": prompt}
        if reference_image:
            # Veo 3.1 "asset" references keep a real product recognizable
            # across independently generated clips.
            instance["referenceImages"] = [{
                "image": {
                    "bytesBase64Encoded":
                        base64.b64encode(reference_image).decode("ascii"),
                    "mimeType": reference_mime,
                },
                "referenceType": "asset",
            }]
        body = {
            "instances": [instance],
            "parameters": {
                "aspectRatio": aspect_ratio,
                "resolution": resolution,
                "durationSeconds": duration,
                "personGeneration": "allow_adult",
            },
        }
        response = self._http.post(
            f"{BASE_URL}/models/{model}:predictLongRunning", json=body)
        payload = self._payload(response)
        operation = payload.get("name", "")
        if not operation:
            raise VeoError(f"no operation name in response: {payload}")
        result = self._wait(operation)
        uri = _extract_video_uri(result)
        download = self._http.get(uri)
        if download.status_code >= 400:
            raise VeoError(f"video download failed ({download.status_code}) "
                           f"from {uri}")
        return download.content

    # ------------------------------------------------------------- internals

    def _wait(self, operation: str) -> dict:
        deadline = time.monotonic() + self._poll_timeout
        while True:
            response = self._http.get(f"{BASE_URL}/{operation}")
            payload = self._payload(response)
            if payload.get("done"):
                error = payload.get("error")
                if error:
                    raise VeoError(f"generation failed: "
                                   f"{error.get('message') or error}")
                return payload.get("response", {})
            if time.monotonic() >= deadline:
                raise VeoError(f"generation timed out after "
                               f"{self._poll_timeout:.0f}s ({operation})")
            time.sleep(self._poll_interval)

    def _payload(self, response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            error = payload.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else error
            raise VeoError(f"Gemini API error ({response.status_code}): "
                           f"{message or response.text[:300]}")
        return payload


def _extract_video_uri(result: dict) -> str:
    """Find the finished clip's URI across the response shapes the docs and
    SDK have used (generateVideoResponse.generatedSamples vs generatedVideos)."""
    inner = result.get("generateVideoResponse") or result
    samples = (inner.get("generatedSamples") or inner.get("generatedVideos")
               or [])
    for sample in samples:
        video = sample.get("video") or {}
        uri = video.get("uri") or sample.get("uri")
        if uri:
            return uri
    raise VeoError(f"no video uri in finished operation: {result}")


class MockVeoClient:
    """Records requests and returns stub mp4 bytes, so the campaign runner is
    testable without a key, network, or spend."""

    def __init__(self, fail_times: int = 0,
                 error: str = "Invalid value at 'parameters.resolution'"):
        self.requests: list[dict] = []
        self.fail_times = fail_times
        self.error = error

    def check_auth(self) -> bool:
        return True

    def generate_clip(self, prompt: str, *, model: str,
                      duration: int = 8, aspect_ratio: str = "9:16",
                      resolution: str = "1080p",
                      reference_image: bytes | None = None,
                      reference_mime: str = "image/jpeg") -> bytes:
        self.requests.append({
            "prompt": prompt, "model": model, "duration": duration,
            "aspect_ratio": aspect_ratio, "resolution": resolution,
            "has_reference": reference_image is not None,
            "reference_mime": reference_mime,
        })
        if self.fail_times > 0:
            self.fail_times -= 1
            raise VeoError(self.error)
        return (b"\x00\x00\x00\x18ftypmp42-mock-veo-"
                + str(len(self.requests)).encode("ascii"))


def make_veo_client(cfg) -> VeoClient | MockVeoClient:
    """Live whenever GEMINI_API_KEY is set. Like render_engine, not gated on
    mode: live — generating a video is not a customer-facing mutation, and the
    CLI's cost confirmation is the spend gate."""
    import os
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return VeoClient(key)
    return MockVeoClient()
