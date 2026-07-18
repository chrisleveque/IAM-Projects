"""Text-to-speech: per-segment synthesis + master voiceover timeline.

Providers implement ``synthesize(text, out_path) -> TTSResult``. The default
is Microsoft Edge neural TTS via edge-tts (free, no key, emits word-boundary
timings). ElevenLabs is an optional paid upgrade called over plain httpx.
MockTTS renders a low tone with synthetic timings for hermetic tests.

``build_voiceover`` renders every script segment, joins them with the
script's pause gaps, and returns the master timeline that clips, captions,
and shorts are all cut against.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .ffmpeg import make_tone, probe, run_ffmpeg


@dataclass
class WordTiming:
    word: str
    start_s: float
    end_s: float


@dataclass
class TTSResult:
    audio_path: Path
    duration_s: float
    words: list[WordTiming] = field(default_factory=list)


@dataclass
class SegmentSpan:
    segment_id: str
    start_s: float
    end_s: float


@dataclass
class Voiceover:
    audio_path: Path
    duration_s: float
    spans: list[SegmentSpan]
    words: list[WordTiming]          # absolute times on the master timeline

    def span_for(self, segment_id: str) -> SegmentSpan:
        for span in self.spans:
            if span.segment_id == segment_id:
                return span
        raise KeyError(segment_id)


class TTSProvider(Protocol):
    def synthesize(self, text: str, out_path: Path) -> TTSResult: ...


WPM_FALLBACK = 140  # used when a provider yields no timings


def spread_words(text: str, duration_s: float, offset_s: float = 0.0) -> list[WordTiming]:
    """Distribute words across a duration proportionally to their length —
    the fallback when a provider returns no word timings."""
    words = text.split()
    if not words:
        return []
    weights = [max(len(w), 2) for w in words]
    total = sum(weights)
    out, cursor = [], offset_s
    for w, weight in zip(words, weights):
        dur = duration_s * weight / total
        out.append(WordTiming(w, cursor, cursor + dur))
        cursor += dur
    return out


class EdgeTTS:
    """Free Microsoft Edge neural voices. Streams audio + WordBoundary events."""

    def __init__(self, voice: str, rate: str = "-8%", pitch: str = "-4Hz"):
        self.voice = voice
        self.rate = rate
        self.pitch = pitch

    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        import edge_tts

        async def _run() -> list[WordTiming]:
            kwargs = {}
            proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
            if proxy:
                kwargs["proxy"] = proxy
            communicate = edge_tts.Communicate(
                text, self.voice, rate=self.rate, pitch=self.pitch, **kwargs)
            words: list[WordTiming] = []
            with open(out_path, "wb") as f:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        start = chunk["offset"] / 1e7  # 100ns ticks -> seconds
                        words.append(WordTiming(
                            chunk["text"], start, start + chunk["duration"] / 1e7))
            return words

        words = asyncio.run(_run())
        duration = probe(out_path)["duration_s"]
        if not words:
            words = spread_words(text, duration)
        return TTSResult(out_path, duration, words)


class ElevenLabsTTS:
    """Paid upgrade; character-level alignment folded into word timings."""

    def __init__(self, api_key: str, voice_id: str, model_id: str = "eleven_multilingual_v2"):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id

    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        import httpx

        resp = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/with-timestamps",
            headers={"xi-api-key": self.api_key},
            json={"text": text, "model_id": self.model_id},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        out_path.write_bytes(base64.b64decode(data["audio_base64"]))
        words = self._words_from_alignment(text, data.get("alignment") or {})
        duration = probe(out_path)["duration_s"]
        if not words:
            words = spread_words(text, duration)
        return TTSResult(out_path, duration, words)

    @staticmethod
    def _words_from_alignment(text: str, alignment: dict) -> list[WordTiming]:
        chars = alignment.get("characters") or []
        starts = alignment.get("character_start_times_seconds") or []
        ends = alignment.get("character_end_times_seconds") or []
        if not chars or len(chars) != len(starts) or len(chars) != len(ends):
            return []
        words, current, w_start, w_end = [], "", None, 0.0
        for ch, s, e in zip(chars, starts, ends):
            if ch.isspace():
                if current:
                    words.append(WordTiming(current, w_start, w_end))
                    current, w_start = "", None
                continue
            if w_start is None:
                w_start = s
            current += ch
            w_end = e
        if current:
            words.append(WordTiming(current, w_start, w_end))
        return words


class MockTTS:
    """Hermetic stand-in: a quiet tone sized by word count, synthetic timings."""

    def __init__(self, wpm: int = WPM_FALLBACK):
        self.wpm = wpm

    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        n_words = max(len(text.split()), 1)
        duration = max(n_words * 60.0 / self.wpm, 0.5)
        make_tone(out_path, duration)
        return TTSResult(out_path, duration, spread_words(text, duration))


def make_tts(cfg, preset) -> TTSProvider:
    provider = cfg.tts_provider(preset)
    if provider == "mock":
        return MockTTS()
    if provider == "elevenlabs":
        return ElevenLabsTTS(os.environ["ELEVENLABS_API_KEY"],
                             os.environ["ELEVENLABS_VOICE_ID"])
    return EdgeTTS(preset.tts.voice, preset.tts.rate, preset.tts.pitch)


_SPEAKABLE = re.compile(r"\s+")


def build_voiceover(segments: list[dict], provider: TTSProvider,
                    workdir: Path, log_path: Path | None = None) -> Voiceover:
    """Render each segment, then concatenate with the script's pause gaps.

    ``segments`` are script-contract dicts: {id, text, pause_after_ms, ...}.
    Returns the master timeline used by footage, captions, and shorts.
    """
    seg_dir = workdir / "tts"
    seg_dir.mkdir(parents=True, exist_ok=True)

    pieces: list[tuple[dict, TTSResult]] = []
    for seg in segments:
        text = _SPEAKABLE.sub(" ", seg["text"]).strip()
        out = seg_dir / f"{seg['id']}.mp3"
        pieces.append((seg, provider.synthesize(text, out)))

    # Normalize every piece to the same wav format, with trailing pause baked
    # in, then losslessly concat.
    concat_list = seg_dir / "concat.txt"
    spans, words, cursor = [], [], 0.0
    lines = []
    for seg, res in pieces:
        pause = max(float(seg.get("pause_after_ms", 500)) / 1000.0, 0.0)
        wav = seg_dir / f"{seg['id']}.wav"
        run_ffmpeg(["-i", str(res.audio_path),
                    "-af", f"aresample=48000,apad=pad_dur={pause:.3f}",
                    "-ac", "1", "-c:a", "pcm_s16le", str(wav)], log_path)
        actual = probe(wav)["duration_s"]
        spans.append(SegmentSpan(seg["id"], cursor, cursor + res.duration_s))
        for w in res.words:
            words.append(WordTiming(w.word, cursor + w.start_s, cursor + w.end_s))
        cursor += actual
        lines.append(f"file '{wav.name}'")
    concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")

    voice_path = workdir / "voiceover.wav"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-c", "copy", str(voice_path)], log_path)
    duration = probe(voice_path)["duration_s"]
    return Voiceover(voice_path, duration, spans, words)
