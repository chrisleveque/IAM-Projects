"""Turn the visual director's shot plan into downloaded, validated clips
mapped onto the voiceover timeline.

Deterministic fallback: if a chosen clip can't be fetched or fails probing,
walk the shot's fallback queries (first unused search result) without going
back to the agent. No clip is used twice in one video.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..integrations.stock import StockClip
from .ffmpeg import probe
from .tts import Voiceover

MIN_SLOT_SECONDS = 1.5


@dataclass
class VisualSlot:
    """One clip occupying [start_s, end_s) of the master timeline."""
    segment_id: str
    start_s: float
    end_s: float
    clip_path: Path
    clip: StockClip
    mood: str = ""

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


class FootageError(RuntimeError):
    pass


def _client_for(clients: list, provider: str):
    for c in clients:
        if c.provider == provider:
            return c
    return clients[0]


def _fetch_clip(clip: StockClip, client, cache_dir: Path) -> Path | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{clip.provider}_{clip.clip_id}.mp4"
    try:
        if not dest.exists() or dest.stat().st_size == 0:
            client.download(clip, dest)
        meta = probe(dest)
        if not meta["has_video"] or meta["duration_s"] < 0.5:
            raise FootageError(f"clip {clip.key} unusable: {meta}")
        clip.duration_s = meta["duration_s"]
        return dest
    except Exception:
        dest.unlink(missing_ok=True)
        return None


def _resolve_shot(shot: dict, clients: list, cache_dir: Path,
                  used: set[str], orientation: str = "landscape") -> tuple[StockClip, Path]:
    """The planned clip, or the first workable fallback search result."""
    client = _client_for(clients, shot.get("provider", ""))
    candidates: list[StockClip] = []
    planned_id = str(shot.get("clip_id") or "")
    if planned_id:
        for c in client.search(shot["query"], orientation=orientation):
            if c.clip_id == planned_id:
                candidates.append(c)
                break
    for query in [shot["query"], *shot.get("fallback_queries", [])]:
        for cl in clients:
            try:
                candidates.extend(cl.search(query, orientation=orientation))
            except Exception:
                continue
    for cand in candidates:
        if cand.key in used:
            continue
        path = _fetch_clip(cand, _client_for(clients, cand.provider), cache_dir)
        if path is not None:
            return cand, path
    raise FootageError(
        f"no usable footage for shot {shot.get('query')!r} "
        f"(tried {len(candidates)} candidates)")


def build_slots(shot_plan: list[dict], voiceover: Voiceover, clients: list,
                cache_dir: Path, on_event=None) -> list[VisualSlot]:
    """Assign each segment's timeline span to its planned shots (split
    equally), downloading clips as needed."""
    slots: list[VisualSlot] = []
    used: set[str] = set()
    plan_by_segment = {entry["segment_id"]: entry for entry in shot_plan}

    for span in voiceover.spans:
        entry = plan_by_segment.get(span.segment_id)
        shots = (entry or {}).get("shots") or [
            {"query": "dark gym training", "provider": "", "clip_id": "",
             "fallback_queries": ["city night rain", "mountain sunrise"]}]
        mood = (entry or {}).get("mood", "")
        span_len = span.end_s - span.start_s
        # never slice a span thinner than MIN_SLOT_SECONDS per shot
        n = max(min(len(shots), int(span_len // MIN_SLOT_SECONDS) or 1), 1)
        per = span_len / n
        for i in range(n):
            clip, path = _resolve_shot(shots[i], clients, cache_dir, used)
            used.add(clip.key)
            slots.append(VisualSlot(
                segment_id=span.segment_id,
                start_s=span.start_s + i * per,
                end_s=span.start_s + (i + 1) * per,
                clip_path=path, clip=clip, mood=mood))
            if on_event:
                on_event(f"footage: {span.segment_id} shot {i + 1}/{n} -> "
                         f"{clip.provider}:{clip.clip_id}")
    return slots
