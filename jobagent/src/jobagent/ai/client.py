"""Thin wrapper around the Anthropic SDK.

Structured responses use the API's structured-outputs feature via
`messages.parse()`, which guarantees schema-valid JSON. If that path is
unavailable (older SDK or unsupported model), we fall back to prompt-based
JSON with one self-repair retry.
"""

from __future__ import annotations

import json
import os
import re
from typing import TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


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
    def __init__(self, model: str, max_tokens: int = 8192):
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

    def parse(self, system: str, user: str, output_model: type[ModelT],
              max_tokens: int | None = None) -> ModelT:
        """Return a validated instance of `output_model`.

        Prefers API structured outputs (guaranteed valid JSON); falls back to
        prompt-based JSON extraction with a self-repair retry.
        """
        try:
            from anthropic import BadRequestError
            resp = self._client.messages.parse(
                model=self.model,
                max_tokens=max_tokens or self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=output_model,
            )
            if resp.parsed_output is not None:
                return resp.parsed_output
        except (AttributeError, TypeError, BadRequestError):
            pass  # SDK or model without structured outputs — use the fallback
        return output_model.model_validate(self.complete_json(system, user, max_tokens))

    def complete_json(self, system: str, user: str,
                      max_tokens: int | None = None) -> dict:
        """Prompt-based JSON with one self-repair retry on invalid output."""
        text = self.complete(system, user, max_tokens)
        try:
            return extract_json(text)
        except (ValueError, json.JSONDecodeError) as exc:
            repair = (
                f"\n\nYour previous response was not valid JSON ({exc}). "
                "Resend the ENTIRE response as one valid JSON object, with all "
                "double quotes and newlines inside strings properly escaped. "
                "Output only the JSON."
            )
            return extract_json(self.complete(system, user + repair, max_tokens))
