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

from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)

# Ceiling for the automatic retry when a response comes back truncated.
MAX_OUTPUT_TOKENS = 32000


class MissingAPIKeyError(RuntimeError):
    pass


class TruncatedResponseError(RuntimeError):
    """The model stopped at the output-token cap, so its JSON is incomplete."""


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


# Signatures of a response that stopped mid-JSON rather than being malformed.
_TRUNCATION_SIGNS = ("eof while parsing", "invalid json",
                     "no json object found", "unterminated string")


def _truncation_hint(*errors) -> str:
    """Add an actionable hint when the failure looks like a cut-off response."""
    blob = " ".join(str(e) for e in errors if e is not None).lower()
    if any(isinstance(e, TruncatedResponseError) for e in errors) or \
            any(sign in blob for sign in _TRUNCATION_SIGNS):
        return (" — the response was cut off; raise ai.max_tokens in "
                "config.yaml or shorten the master resume")
    return ""


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

        Prefers API structured outputs (guaranteed valid JSON). A response that
        hits the token ceiling comes back as truncated JSON, so retry once with
        a bigger budget, then fall back to prompt-based JSON with self-repair.
        """
        budget = max_tokens or self.max_tokens
        last_error: Exception | None = None

        for attempt in range(2):
            try:
                from anthropic import BadRequestError
                resp = self._client.messages.parse(
                    model=self.model,
                    max_tokens=budget,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    output_format=output_model,
                )
                if getattr(resp, "stop_reason", "") == "max_tokens":
                    raise TruncatedResponseError(
                        f"model stopped at the {budget}-token output cap")
                if resp.parsed_output is not None:
                    return resp.parsed_output
                last_error = RuntimeError("structured output was empty")
            except (AttributeError, TypeError, BadRequestError):
                break  # SDK or model without structured outputs — use fallback
            except (ValidationError, TruncatedResponseError) as exc:
                # Truncated or otherwise unusable JSON: raise the ceiling and
                # try again rather than losing the whole job.
                last_error = exc
                if attempt == 0 and budget < MAX_OUTPUT_TOKENS:
                    budget = min(budget * 2, MAX_OUTPUT_TOKENS)
                    continue
                break

        try:
            return output_model.model_validate(
                self.complete_json(system, user, budget))
        except Exception as exc:
            raise RuntimeError(
                f"could not get valid {output_model.__name__} from the model"
                f"{_truncation_hint(last_error, exc)}: {exc}") from exc

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
