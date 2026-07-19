import pytest

from fitagent.agents.base import AgentOutputError, JSONAgent
from fitagent.agents.contracts import ConceptOutput
from fitagent.agents.visual_director import VisualDirectorAgent
from fitagent.integrations.stock import MockStockClient

from conftest import FakeAIClient

CONCEPT = {
    "concept": {
        "working_title": "The Quiet Hours", "theme": "discipline",
        "angle": "discipline as self-respect", "source_type": "original",
        "pd_source": None, "hook": "Nobody is coming.",
        "emotional_arc": ["low", "rise", "peak", "resolve"],
        "target_minutes": 7, "visual_world": "dark gym, rain",
        "rationale": "fits the channel",
    }
}


class ConceptAgent(JSONAgent):
    name = "test_concept"
    output_model = ConceptOutput

    def system_prompt(self) -> str:
        return "test"


def test_run_json_validates(cfg, store):
    ai = FakeAIClient(json_responses=[CONCEPT])
    agent = ConceptAgent(ai, store, cfg, cfg.preset())
    out = agent.run_json("go")
    assert out.concept.working_title == "The Quiet Hours"
    assert store.list_agent_runs()[0]["status"] == "ok"


def test_run_json_retries_then_succeeds(cfg, store):
    bad = {"concept": {"working_title": "x"}}  # missing required fields
    ai = FakeAIClient(json_responses=[bad, CONCEPT])
    agent = ConceptAgent(ai, store, cfg, cfg.preset())
    out = agent.run_json("go")
    assert out.concept.theme == "discipline"


def test_run_json_gives_up(cfg, store):
    ai = FakeAIClient(json_responses=[{"nope": 1}] * 3)
    agent = ConceptAgent(ai, store, cfg, cfg.preset())
    with pytest.raises(AgentOutputError):
        agent.run_json("go")


def test_visual_director_search_and_submit(cfg, store):
    clients = [MockStockClient()]
    results = MockStockClient().search("dark gym")
    plan = {
        "shot_plan": [{
            "segment_id": "s01", "mood": "gritty",
            "shots": [{"query": "dark gym", "provider": "mock",
                       "clip_id": results[0].clip_id,
                       "fallback_queries": ["city night"],
                       "target_seconds": 4.0}],
        }],
        "reuse_notes": "",
    }
    ai = FakeAIClient(tool_script=[("search_stock", {"query": "dark gym"}),
                                   ("submit_shot_plan", plan)])
    agent = VisualDirectorAgent(ai, store, cfg, cfg.preset(), clients)
    out = agent.run([{"id": "s01", "text": "Nobody is coming.",
                      "visual_theme": "dark gym", "energy": 3}])
    assert out.shot_plan[0].shots[0].clip_id == results[0].clip_id
    # search results were returned to the model
    assert any(name == "search_stock" for name, _, _ in ai.calls)


def test_visual_director_requires_submission(cfg, store):
    ai = FakeAIClient(tool_script=[("search_stock", {"query": "dark gym"})])
    agent = VisualDirectorAgent(ai, store, cfg, cfg.preset(), [MockStockClient()])
    with pytest.raises(AgentOutputError):
        agent.run([{"id": "s01", "text": "x", "visual_theme": "y", "energy": 3}])
