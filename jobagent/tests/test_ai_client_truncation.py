"""A truncated model response must not lose the job.

Real failure this reproduces:
    tailoring failed: 1 validation error for TailoredPackage
      Invalid JSON: EOF while parsing a string at line 1 column 8684
The structured-output path returned JSON cut off mid-string; `parse` only
caught SDK-capability errors, so the ValidationError killed the whole job
instead of falling through to the prompt-based fallback.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from jobagent.ai.client import MAX_OUTPUT_TOKENS, AIClient


class Package(BaseModel):
    text: str = ""
    items: list[str] = []


GOOD = {"text": "complete", "items": ["a", "b"]}
# JSON cut off mid-string, exactly like a max_tokens truncation
TRUNCATED = json.dumps(GOOD)[:18]


class FakeResponse:
    def __init__(self, parsed=None, stop_reason="end_turn"):
        self.parsed_output = parsed
        self.stop_reason = stop_reason


class FakeMessages:
    """Records every call so tests can assert on budgets and retries."""

    def __init__(self, parse_results, text_results):
        self.parse_results = list(parse_results)
        self.text_results = list(text_results)
        self.parse_budgets: list[int] = []
        self.create_budgets: list[int] = []

    def parse(self, *, model, max_tokens, system, messages, output_format):
        self.parse_budgets.append(max_tokens)
        result = self.parse_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def create(self, *, model, max_tokens, system, messages):
        self.create_budgets.append(max_tokens)
        text = self.text_results.pop(0)

        class Block:
            type = "text"

        block = Block()
        block.text = text
        return type("Resp", (), {"content": [block]})()


def make_client(monkeypatch, parse_results, text_results=()):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("anthropic.Anthropic", lambda *a, **k: object())
    client = AIClient("claude-sonnet-5", max_tokens=8192)
    client._client = type("C", (), {})()
    client._client.messages = FakeMessages(parse_results, text_results)
    return client


def test_truncated_structured_output_retries_with_a_bigger_budget(monkeypatch):
    from pydantic import ValidationError

    try:
        Package.model_validate_json(TRUNCATED)
    except ValidationError as exc:
        truncation_error = exc

    client = make_client(monkeypatch,
                         [truncation_error, FakeResponse(Package(text="ok"))])
    result = client.parse("sys", "user", Package)

    assert result.text == "ok"
    budgets = client._client.messages.parse_budgets
    assert budgets == [8192, 16384], budgets  # doubled on the retry


def test_max_tokens_stop_reason_triggers_the_retry(monkeypatch):
    """Even when the SDK hands back a parsed object, a max_tokens stop means
    the content is incomplete and must not be trusted."""
    client = make_client(monkeypatch, [
        FakeResponse(Package(text="cut off"), stop_reason="max_tokens"),
        FakeResponse(Package(text="complete")),
    ])
    assert client.parse("sys", "user", Package).text == "complete"
    assert client._client.messages.parse_budgets == [8192, 16384]


def test_falls_back_to_prompt_json_when_retry_also_truncates(monkeypatch):
    from pydantic import ValidationError

    try:
        Package.model_validate_json(TRUNCATED)
    except ValidationError as exc:
        err = exc

    client = make_client(monkeypatch, [err, err], [json.dumps(GOOD)])
    result = client.parse("sys", "user", Package)

    assert result.text == "complete"
    # the fallback runs at the raised budget, not the original one
    assert client._client.messages.create_budgets == [16384]


def test_hopeless_truncation_raises_an_actionable_error(monkeypatch):
    from pydantic import ValidationError

    try:
        Package.model_validate_json(TRUNCATED)
    except ValidationError as exc:
        err = exc

    # structured output truncates twice, and both fallback attempts truncate too
    client = make_client(monkeypatch, [err, err], [TRUNCATED, TRUNCATED])
    with pytest.raises(RuntimeError) as caught:
        client.parse("sys", "user", Package)

    message = str(caught.value)
    assert "Package" in message
    assert "cut off" in message and "ai.max_tokens" in message


def test_retry_budget_is_capped(monkeypatch):
    from pydantic import ValidationError

    try:
        Package.model_validate_json(TRUNCATED)
    except ValidationError as exc:
        err = exc

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("anthropic.Anthropic", lambda *a, **k: object())
    client = AIClient("claude-sonnet-5", max_tokens=MAX_OUTPUT_TOKENS)
    client._client = type("C", (), {})()
    client._client.messages = FakeMessages([err, err], [json.dumps(GOOD)])

    client.parse("sys", "user", Package)
    # already at the ceiling: no pointless doubling, single attempt
    assert client._client.messages.parse_budgets == [MAX_OUTPUT_TOKENS]


def test_missing_structured_output_support_uses_fallback_immediately(monkeypatch):
    client = make_client(monkeypatch, [AttributeError("no parse()")],
                         [json.dumps(GOOD)])
    assert client.parse("sys", "user", Package).text == "complete"
    assert len(client._client.messages.parse_budgets) == 1


def test_tailor_requests_a_budget_big_enough_for_a_full_resume():
    from jobagent.ai.tailor import TAILOR_MIN_TOKENS, tailor_for_job
    from jobagent.store import Job

    class CapturingAI:
        max_tokens = 8192  # the old default that truncated

        def __init__(self):
            self.max_tokens_used = None

        def parse(self, system, user, output_model, max_tokens=None):
            self.max_tokens_used = max_tokens
            return output_model.model_validate({
                "resume": {"name": "X"}, "cover_letter": ""})

    ai = CapturingAI()
    tailor_for_job(ai, "resume text", Job(url="u", source="linkedin"))
    assert ai.max_tokens_used == TAILOR_MIN_TOKENS
    assert TAILOR_MIN_TOKENS > 8192


def test_tailor_honors_a_larger_configured_budget():
    from jobagent.ai.tailor import tailor_for_job
    from jobagent.store import Job

    class BigAI:
        max_tokens = 24000

        def parse(self, system, user, output_model, max_tokens=None):
            self.max_tokens_used = max_tokens
            return output_model.model_validate({
                "resume": {"name": "X"}, "cover_letter": ""})

    ai = BigAI()
    tailor_for_job(ai, "resume text", Job(url="u", source="linkedin"))
    assert ai.max_tokens_used == 24000
