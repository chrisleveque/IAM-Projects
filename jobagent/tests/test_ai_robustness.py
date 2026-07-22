"""Regression tests for malformed model JSON (seen in the wild during tailoring)."""

import json

from jobagent.ai.client import AIClient
from jobagent.ai.scorer import ScoreResult


def make_client_without_init() -> AIClient:
    """Build an AIClient without __init__ (no API key needed for these tests)."""
    ai = AIClient.__new__(AIClient)
    ai.model = "test-model"
    ai.max_tokens = 1024
    return ai


def test_complete_json_repairs_invalid_output():
    ai = make_client_without_init()
    calls = []

    def fake_complete(system, user, max_tokens=None):
        calls.append(user)
        if len(calls) == 1:
            return '{"summary": "an "unescaped" quote breaks this'
        return '{"summary": "fixed"}'

    ai.complete = fake_complete
    assert ai.complete_json("sys", "user prompt") == {"summary": "fixed"}
    assert len(calls) == 2
    assert "was not valid JSON" in calls[1]


def test_parse_falls_back_when_structured_outputs_unavailable():
    ai = make_client_without_init()
    ai._client = object()  # no .messages.parse -> AttributeError -> fallback
    ai.complete = lambda system, user, max_tokens=None: json.dumps(
        {"score": 72, "reasons": ["good match"], "concerns": []}
    )
    result = ai.parse("sys", "user", ScoreResult)
    assert isinstance(result, ScoreResult)
    assert result.score == 72
