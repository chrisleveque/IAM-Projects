"""Optional voiceover synthesis (experimental).

Uses ``edge-tts`` (``pip install -e .[voice]``), which drives Microsoft Edge's
free TTS endpoint — no API key. That endpoint is unofficial and has broken
before, which is exactly why voiceover defaults off in config and why the
executor treats any failure here as "render without a voice", never as a
failed render.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_VOICE = "en-US-AriaNeural"


class VoiceError(RuntimeError):
    pass


def script_to_speech_text(script: dict) -> str:
    """Flatten a {hook, shots, cta} script into narratable text. Sentences get
    terminal punctuation so the voice pauses between beats instead of running
    them together."""
    parts = [script.get("hook", "")]
    parts += [s.get("text", "") if isinstance(s, dict) else str(s)
              for s in script.get("shots", [])]
    parts.append(script.get("cta", ""))
    sentences = []
    for part in parts:
        text = str(part).strip()
        if not text:
            continue
        if text[-1] not in ".!?":
            text += "."
        sentences.append(text)
    return " ".join(sentences)


def synthesize(text: str, dest: Path | str, voice: str = DEFAULT_VOICE) -> Path:
    """Write ``text`` as an mp3. Raises VoiceError on any failure, including
    edge-tts simply not being installed."""
    if not text.strip():
        raise VoiceError("no text to narrate")
    try:
        import edge_tts
    except ImportError as exc:
        raise VoiceError(
            "voiceover needs the edge-tts package: pip install -e .[voice]"
        ) from exc

    import asyncio

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    async def _run() -> None:
        await edge_tts.Communicate(text, voice).save(str(dest))

    try:
        asyncio.run(_run())
    except Exception as exc:  # unofficial endpoint: fail as one error type
        raise VoiceError(f"voice synthesis failed: {exc}") from exc
    if not dest.exists() or dest.stat().st_size == 0:
        raise VoiceError("voice synthesis produced no audio")
    return dest
