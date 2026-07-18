"""Shared fixtures: tmp config/store and a scripted fake AI client.

No test needs network access or API keys; tests marked @pytest.mark.media
shell out to ffmpeg and are skipped when it is absent.
"""

from __future__ import annotations

import json

import pytest

from fitagent.ai.client import ToolRunResult
from fitagent.config import AppConfig
from fitagent.store import Store


class FakeAIClient:
    """Stands in for AIClient.

    ``json_responses`` is a queue of dicts returned by complete_json in
    order. ``tool_script`` is a list of (tool_name, tool_input) pairs that
    run_tools executes against the real handlers the agent wired up.
    """

    def __init__(self, json_responses: list[dict] | None = None,
                 tool_script: list[tuple[str, dict]] | None = None,
                 final_text: str = "done"):
        self.json_responses = list(json_responses or [])
        self.tool_script = list(tool_script or [])
        self.final_text = final_text
        self.calls: list[tuple[str, dict, object]] = []

    def complete(self, system: str, user: str, max_tokens: int | None = None) -> str:
        return json.dumps(self.complete_json(system, user, max_tokens))

    def complete_json(self, system: str, user: str,
                      max_tokens: int | None = None) -> dict:
        if not self.json_responses:
            raise AssertionError("FakeAIClient ran out of scripted responses")
        return self.json_responses.pop(0)

    def run_tools(self, system: str, user: str, tools: list[dict],
                  handlers: dict, max_iterations: int = 20) -> ToolRunResult:
        result = ToolRunResult(text=self.final_text)
        known = {t["name"] for t in tools}
        for name, tool_input in self.tool_script:
            assert name in known, f"scripted tool {name!r} not offered to the agent"
            result.tool_calls += 1
            try:
                output = handlers[name](tool_input)
                self.calls.append((name, tool_input, output))
            except Exception as exc:
                result.errors.append(f"{name}: {exc}")
                self.calls.append((name, tool_input, exc))
        return result


@pytest.fixture
def cfg(tmp_path) -> AppConfig:
    config = AppConfig()
    config.root = tmp_path
    config.mode = "dry_run"
    config.presets["forge"].tts.provider = "mock"
    for sub in ("assets/music", "assets/fonts", "assets/public_domain", "output"):
        (tmp_path / sub).mkdir(parents=True)
    return config


@pytest.fixture
def store(cfg) -> Store:
    s = Store(cfg.db_path)
    yield s
    s.close()
