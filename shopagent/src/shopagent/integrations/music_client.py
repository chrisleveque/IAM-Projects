"""Royalty-free music search + download for ad soundtracks.

    search(query, limit) -> list[dict]   # {id, title, artist, duration, license, source, url}
    download(track, dest) -> Path

Two backends behind one interface: Pixabay (CC0-equivalent Content License)
and Jamendo (Creative Commons, filtered to the permissive licences). Both are
free and key-based. If both keys are present, results are interleaved so one
provider's catalogue doesn't dominate.

WHY NOT THE TRENDING TIKTOK SOUNDS: the tracks trending on TikTok are
commercial recordings. On a Business account, or in any paid ad, using one is
a copyright violation — TikTok mutes or removes the video. The sanctioned
source there is TikTok's own Commercial Music Library, which has no public
API and must be picked in the app. So this module supplies a legally safe bed
for the rendered draft, and the content agent tells the operator to swap in a
Commercial Music Library track before posting as an ad. Both halves matter;
neither alone is correct.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from ..config import AppConfig
from . import fixtures

# Jamendo's track API is publicly documented and stable. Pixabay documents an
# API for images and video; its music endpoint is not part of that documented
# surface, so treat the Pixabay path as best-effort — it is skipped unless a key
# is set, search failures raise MusicError rather than returning junk, and
# `shopagent doctor` reports whether a live search actually works. Jamendo alone
# is a complete configuration.
PIXABAY_URL = "https://pixabay.com/api/videos/music/"
JAMENDO_URL = "https://api.jamendo.com/v3.0/tracks"


class MusicError(RuntimeError):
    pass


def _dedupe(tracks: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out = []
    for track in tracks:
        key = (track["title"].strip().lower(), track["artist"].strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(track)
    return out


def _interleave(*groups: list[dict]) -> list[dict]:
    """Round-robin so a single provider can't fill the whole shortlist."""
    out = []
    for i in range(max((len(g) for g in groups), default=0)):
        for group in groups:
            if i < len(group):
                out.append(group[i])
    return out


class MusicClient:
    def __init__(self, pixabay_key: str = "", jamendo_id: str = "",
                 transport: httpx.BaseTransport | None = None,
                 timeout: float = 20.0):
        if not pixabay_key and not jamendo_id:
            raise MusicError(
                "no music provider configured; set PIXABAY_API_KEY or "
                "JAMENDO_CLIENT_ID (both are free)")
        self.pixabay_key = pixabay_key
        self.jamendo_id = jamendo_id
        self._http = httpx.Client(timeout=timeout, transport=transport,
                                  follow_redirects=True)

    # ------------------------------------------------------------- search

    def search(self, query: str, limit: int = 10) -> list[dict]:
        groups = []
        if self.pixabay_key:
            groups.append(self._search_pixabay(query, limit))
        if self.jamendo_id:
            groups.append(self._search_jamendo(query, limit))
        return _dedupe(_interleave(*groups))[:limit]

    def _search_pixabay(self, query: str, limit: int) -> list[dict]:
        try:
            response = self._http.get(PIXABAY_URL, params={
                "key": self.pixabay_key, "q": query,
                "per_page": max(3, min(limit, 200))})
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise MusicError(f"pixabay search failed: {exc}") from exc
        out = []
        for hit in payload.get("hits", []):
            url = hit.get("audio") or hit.get("url") or ""
            if not url:
                continue
            out.append({
                "id": f"pixabay:{hit.get('id')}",
                "title": (hit.get("tags") or "untitled").split(",")[0].strip(),
                "artist": hit.get("user") or "Pixabay",
                "duration": int(hit.get("duration") or 0),
                "license": "Pixabay Content License (royalty-free)",
                "source": "pixabay",
                "url": url,
            })
        return out

    def _search_jamendo(self, query: str, limit: int) -> list[dict]:
        try:
            response = self._http.get(JAMENDO_URL, params={
                "client_id": self.jamendo_id, "format": "json",
                "limit": max(3, min(limit, 200)), "search": query,
                "audioformat": "mp32", "include": "licenses"})
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise MusicError(f"jamendo search failed: {exc}") from exc
        out = []
        for hit in payload.get("results", []):
            licence = (hit.get("license_ccurl") or "").lower()
            audio = hit.get("audiodownload") or hit.get("audio") or ""
            if not audio:
                continue
            # an ad is commercial use — drop anything NonCommercial
            if "nc" in _licence_slug(licence):
                continue
            out.append({
                "id": f"jamendo:{hit.get('id')}",
                "title": hit.get("name") or "untitled",
                "artist": hit.get("artist_name") or "Unknown",
                "duration": int(hit.get("duration") or 0),
                "license": licence or "Creative Commons",
                "source": "jamendo",
                "url": audio,
            })
        return out

    # ----------------------------------------------------------- download

    def download(self, track: dict, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            response = self._http.get(track["url"])
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MusicError(f"download failed for {track.get('title')}: {exc}") from exc
        dest.write_bytes(response.content)
        return dest


def _licence_slug(url: str) -> str:
    """'http://creativecommons.org/licenses/by-nc-nd/3.0/' -> 'by-nc-nd'."""
    parts = [p for p in url.split("/") if p]
    for part in parts:
        if part.startswith("by") or part == "zero":
            return part
    return ""


class MockMusicClient:
    """Deterministic offline catalogue so renders and tests need no network."""

    def __init__(self):
        self.downloads: list[tuple[str, Path]] = []

    def search(self, query: str, limit: int = 10) -> list[dict]:
        words = {w for w in query.lower().split() if len(w) > 2}
        scored = []
        for track in fixtures.MUSIC_CATALOG:
            haystack = f"{track['title']} {track['mood']}".lower()
            score = sum(1 for w in words if w in haystack)
            scored.append((score, track))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
        return [dict(track) for _, track in scored[:limit]]

    def download(self, track: dict, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # a real, playable silent WAV so the renderer can be exercised offline
        dest.write_bytes(_silent_wav(seconds=min(30, track.get("duration") or 20)))
        self.downloads.append((track["id"], dest))
        return dest


def _silent_wav(seconds: int = 20, rate: int = 44100) -> bytes:
    """Minimal 16-bit mono silent WAV — enough for ffmpeg to treat as audio."""
    import struct

    frames = rate * max(1, seconds)
    data_size = frames * 2
    header = b"RIFF" + struct.pack("<I", 36 + data_size) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", data_size)
    return header + b"\x00" * data_size


def make_music_client(cfg: AppConfig):
    if cfg.music_mode() == "live":
        return MusicClient(pixabay_key=os.environ.get("PIXABAY_API_KEY", ""),
                           jamendo_id=os.environ.get("JAMENDO_CLIENT_ID", ""))
    return MockMusicClient()
