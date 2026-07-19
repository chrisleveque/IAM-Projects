"""Stock footage clients: Pexels + Pixabay (both free, copyright-free
licenses that allow monetized YouTube use) and a mock that generates
test-pattern clips so the pipeline renders end to end with no keys.

Clients share one surface:
    search(query, orientation, per_page) -> list[StockClip]
    download(clip, dest) -> Path
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx


@dataclass
class StockClip:
    provider: str
    clip_id: str
    duration_s: float
    width: int
    height: int
    page_url: str = ""
    download_url: str = ""
    license_note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.clip_id}"


class PexelsClient:
    provider = "pexels"
    license_note = "Pexels License (free for commercial use, no attribution required)"

    def __init__(self, api_key: str, timeout: float = 60, transport=None):
        self._http = httpx.Client(
            base_url="https://api.pexels.com",
            headers={"Authorization": api_key},
            timeout=timeout, transport=transport, follow_redirects=True)

    def search(self, query: str, orientation: str = "landscape",
               per_page: int = 10) -> list[StockClip]:
        resp = self._http.get("/videos/search", params={
            "query": query, "orientation": orientation, "per_page": per_page})
        resp.raise_for_status()
        clips = []
        for video in resp.json().get("videos", []):
            best = self._best_file(video.get("video_files", []))
            if not best:
                continue
            clips.append(StockClip(
                provider=self.provider, clip_id=str(video["id"]),
                duration_s=float(video.get("duration", 0)),
                width=int(best.get("width") or 0), height=int(best.get("height") or 0),
                page_url=video.get("url", ""), download_url=best["link"],
                license_note=self.license_note))
        return clips

    @staticmethod
    def _best_file(files: list[dict]) -> dict | None:
        """Smallest rendition that is still >= 1080p tall, else the largest."""
        usable = [f for f in files if f.get("link") and f.get("height")]
        if not usable:
            return None
        hd = [f for f in usable if f["height"] >= 1080]
        if hd:
            return min(hd, key=lambda f: f["height"])
        return max(usable, key=lambda f: f["height"])

    def download(self, clip: StockClip, dest: Path) -> Path:
        with self._http.stream("GET", clip.download_url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(1 << 16):
                    f.write(chunk)
        return dest


class PixabayClient:
    provider = "pixabay"
    license_note = "Pixabay Content License (free for commercial use, no attribution required)"

    def __init__(self, api_key: str, timeout: float = 60, transport=None):
        self._key = api_key
        self._http = httpx.Client(base_url="https://pixabay.com", timeout=timeout,
                                  transport=transport, follow_redirects=True)

    def search(self, query: str, orientation: str = "landscape",
               per_page: int = 10) -> list[StockClip]:
        resp = self._http.get("/api/videos/", params={
            "key": self._key, "q": query, "per_page": max(per_page, 3)})
        resp.raise_for_status()
        want_portrait = orientation == "portrait"
        clips = []
        for hit in resp.json().get("hits", []):
            rendition = (hit.get("videos") or {}).get("large") or {}
            if not rendition.get("url"):
                rendition = (hit.get("videos") or {}).get("medium") or {}
            if not rendition.get("url"):
                continue
            w, h = int(rendition.get("width") or 0), int(rendition.get("height") or 0)
            if want_portrait != (h > w):
                continue
            clips.append(StockClip(
                provider=self.provider, clip_id=str(hit["id"]),
                duration_s=float(hit.get("duration", 0)),
                width=w, height=h,
                page_url=hit.get("pageURL", ""), download_url=rendition["url"],
                license_note=self.license_note))
        return clips

    def download(self, clip: StockClip, dest: Path) -> Path:
        with self._http.stream("GET", clip.download_url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_bytes(1 << 16):
                    f.write(chunk)
        return dest


class MockStockClient:
    """Deterministic fake: search results derived from the query hash;
    download renders a test-pattern clip with ffmpeg."""

    provider = "mock"
    license_note = "generated test pattern (mock provider)"

    def __init__(self, clip_seconds: float = 8.0):
        self.clip_seconds = clip_seconds

    def search(self, query: str, orientation: str = "landscape",
               per_page: int = 10) -> list[StockClip]:
        digest = hashlib.sha256(query.encode()).hexdigest()
        w, h = (1080, 1920) if orientation == "portrait" else (1920, 1080)
        return [
            StockClip(provider=self.provider,
                      clip_id=f"{digest[:8]}{i:02d}",
                      duration_s=self.clip_seconds, width=w, height=h,
                      page_url=f"mock://{query}/{i}",
                      download_url=f"mock://{query}/{i}",
                      license_note=self.license_note,
                      extra={"hue": (int(digest[:4], 16) + i * 47) % 360})
            for i in range(min(per_page, 5))
        ]

    def download(self, clip: StockClip, dest: Path) -> Path:
        from ..media.ffmpeg import make_test_clip
        make_test_clip(dest, clip.duration_s, clip.width, clip.height,
                       hue=clip.extra.get("hue", 0))
        return dest


def make_stock_clients(cfg) -> list:
    """Live clients for whichever keys exist; mock otherwise (and always in
    dry_run mode)."""
    if cfg.stock_mode() != "live":
        return [MockStockClient()]
    clients = []
    if os.environ.get("PEXELS_API_KEY"):
        clients.append(PexelsClient(os.environ["PEXELS_API_KEY"]))
    if os.environ.get("PIXABAY_API_KEY"):
        clients.append(PixabayClient(os.environ["PIXABAY_API_KEY"]))
    return clients or [MockStockClient()]
