"""Shared fixtures: tmp store, mock integrations, and a scripted fake AI client.

No test in this suite needs network access or API keys.
"""

from __future__ import annotations

import pytest

from shopagent.ai.client import ToolRunResult
from shopagent.config import AppConfig
from shopagent.integrations.cj_client import MockCJClient
from shopagent.integrations.shopify_client import MockShopifyClient
from shopagent.store import Store


class FakeAIClient:
    """Stands in for AIClient in agent tests.

    ``script`` is a list of (tool_name, tool_input) pairs; run_tools executes
    each against the real handlers the agent wired up, mimicking what the
    model's tool-use loop would do, then returns a canned final message.
    """

    def __init__(self, script: list[tuple[str, dict]] | None = None,
                 final_text: str = "done"):
        self.script = script or []
        self.final_text = final_text
        self.calls: list[tuple[str, dict, object]] = []  # (tool, input, output/error)

    def run_tools(self, system: str, user: str, tools: list[dict],
                  handlers: dict, max_iterations: int = 20) -> ToolRunResult:
        result = ToolRunResult(text=self.final_text)
        known = {t["name"] for t in tools}
        for name, tool_input in self.script:
            assert name in known, f"scripted tool {name!r} not offered to the agent"
            result.tool_calls += 1
            try:
                output = handlers[name](tool_input)
                self.calls.append((name, tool_input, output))
            except Exception as exc:
                result.errors.append(f"{name}: {exc}")
                self.calls.append((name, tool_input, exc))
        return result

    def complete(self, system: str, user: str, max_tokens: int | None = None) -> str:
        return self.final_text

    def complete_json(self, system: str, user: str, max_tokens: int | None = None) -> dict:
        return {}


@pytest.fixture
def cfg(tmp_path) -> AppConfig:
    config = AppConfig()
    config.root = tmp_path
    (tmp_path / "inbox").mkdir()
    return config


@pytest.fixture
def store(cfg) -> Store:
    s = Store(cfg.db_path)
    yield s
    s.close()


@pytest.fixture
def shopify() -> MockShopifyClient:
    return MockShopifyClient()


@pytest.fixture
def cj() -> MockCJClient:
    return MockCJClient()
