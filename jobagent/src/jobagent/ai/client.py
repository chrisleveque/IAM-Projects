"""Thin wrapper around the Anthropic SDK with JSON-extraction helpers."""

from __future__ import annotations

import json
import os
import re


class MissingAPIKeyError(RuntimeError):
    pass


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response (handles code fences)."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object found in model response: {text[:200]!r}")
    return json.loads(text[start : end + 1])


class AIClient:
    def __init__(self, model: str, max_tokens: int = 4096):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise MissingAPIKeyError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add "
                "your key from https://console.anthropic.com"
            )
        from anthropic import Anthropic  # imported lazily so tests can mock AIClient

        self._client = Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, system: str, user: str, max_tokens: int | None = None) -> str:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens or self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")

    def complete_json(self, system: str, user: str, max_tokens: int | None = None) -> dict:
        return extract_json(self.complete(system, user, max_tokens))
