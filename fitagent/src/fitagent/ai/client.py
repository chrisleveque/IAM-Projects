"""Thin wrapper around the Anthropic SDK: completions + a manual tool-use loop."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field


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


@dataclass
class ToolRunResult:
    text: str = ""
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    stopped_on: str = "end_turn"
    errors: list[str] = field(default_factory=list)


class AIClient:
    def __init__(self, model: str, max_tokens: int = 8192):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise MissingAPIKeyError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add "
                "your key from https://console.anthropic.com"
            )
        from anthropic import Anthropic  # imported lazily so tests can inject fakes

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

    def run_tools(self, system: str, user: str, tools: list[dict],
                  handlers: dict, max_iterations: int = 20) -> ToolRunResult:
        """Manual agent loop: call the model, execute requested tools, feed the
        results back, repeat until the model stops asking for tools.

        ``tools`` are Anthropic tool schemas; ``handlers`` maps tool name to a
        callable taking the tool input dict and returning a JSON-serializable
        result. Handler exceptions are returned to the model as error tool
        results so it can recover or report.
        """
        result = ToolRunResult()
        messages: list[dict] = [{"role": "user", "content": user}]
        for _ in range(max_iterations):
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=messages,
                tools=tools,
                thinking={"type": "adaptive"},
            )
            result.input_tokens += resp.usage.input_tokens
            result.output_tokens += resp.usage.output_tokens
            result.text = "".join(b.text for b in resp.content if b.type == "text") or result.text
            if resp.stop_reason != "tool_use":
                result.stopped_on = resp.stop_reason
                return result
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                result.tool_calls += 1
                try:
                    handler = handlers[block.name]
                    output = handler(block.input or {})
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                         "content": json.dumps(output, default=str)})
                except Exception as exc:  # returned to the model, also logged
                    result.errors.append(f"{block.name}: {exc}")
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                         "content": str(exc), "is_error": True})
            messages.append({"role": "user", "content": tool_results})
        result.stopped_on = "max_iterations"
        return result
