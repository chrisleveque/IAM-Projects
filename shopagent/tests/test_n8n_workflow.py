"""Contract tests between n8n/store-manager-agent.json and the HTTP API.

The workflow file is exported to a system this suite cannot reach, so n8n's own
node schema goes unverified here. What *is* verifiable is the half we own: that
every URL the workflow calls is a real route, that every query parameter it
sends is one the route accepts, and — most importantly — that the workflow
never points at an endpoint that can change anything.

That last check is the approval gate expressed as a test. An LLM holding an
approve tool is the one way this design loses its human gate, so it should fail
CI rather than fail in production.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from shopagent.api import create_app

WORKFLOW = Path(__file__).resolve().parents[1] / "n8n" / "store-manager-agent.json"
TOKEN = "workflow-contract-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TOOL_TYPE = "@n8n/n8n-nodes-langchain.toolHttpRequest"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture
def client(cfg) -> TestClient:
    return TestClient(create_app(cfg, TOKEN))


def _tool_nodes(workflow: dict) -> list[dict]:
    return [n for n in workflow["nodes"] if n["type"] == TOOL_TYPE]


def _path_of(node: dict) -> str:
    return urlparse(node["parameters"]["url"]).path


def _query_names(node: dict) -> list[str]:
    values = node["parameters"].get("parametersQuery", {}).get("values", [])
    return [v["name"] for v in values]


def test_workflow_file_is_valid_json_with_the_expected_shape(workflow):
    assert workflow["name"] == "Store Manager Agent"
    for key in ("nodes", "connections", "settings"):
        assert key in workflow
    assert _tool_nodes(workflow), "no HTTP tool nodes found"


def test_every_tool_url_is_a_real_route(workflow, client):
    routes = {r.path for r in client.app.routes}
    for node in _tool_nodes(workflow):
        assert _path_of(node) in routes, f"{node['name']} points at a nonexistent route"


def test_no_tool_can_change_anything(workflow, client):
    """The approval gate, as a test. Every tool must be a GET against a route
    that has no mutating method — no approve, reject, or retry."""
    mutating = {r.path for r in client.app.routes
                if getattr(r, "methods", None)
                and {"POST", "PUT", "PATCH", "DELETE"} & r.methods}
    # mutating routes are templated ("/approvals/{approval_id}/approve") while a
    # tool URL is concrete ("/approvals/7/approve"), so compare on the literal
    # prefix before the first placeholder — exact matching would miss them all
    prefixes = tuple(path.split("{")[0] for path in mutating)
    for node in _tool_nodes(workflow):
        method = node["parameters"].get("method", "GET")
        assert method == "GET", f"{node['name']} uses {method}"
        path = _path_of(node)
        assert not path.startswith(prefixes), (
            f"{node['name']} targets {path}, which can mutate state — "
            "an agent holding this does not have a human approval gate")
        assert not node["parameters"].get("sendBody")


def test_every_query_parameter_is_accepted_by_its_route(workflow, client):
    """A parameter name the route ignores would silently do nothing; one it
    rejects would 422 at runtime. Send each with a valid value and confirm the
    route understands it.

    Samples are per-node because 'status' means different things per route —
    'pending' is a valid approval status and an invalid product one.
    """
    samples = {
        "list_approvals": {"status": "pending"},
        "get_approval": {"id": "1"},
        "list_products": {"status": "drafted"},
        "list_orders": {"status": "new", "channel": "shopify"},
        "list_videos": {},
        "list_trends": {"kind": "hashtag"},
    }
    for node in _tool_nodes(workflow):
        path = _path_of(node)
        for name in _query_names(node):
            value = samples.get(node["name"], {}).get(name)
            assert value is not None, f"no sample for {node['name']}.{name}"
            response = client.get(f"{path}?{name}={value}", headers=AUTH)
            assert response.status_code in (200, 404), (
                f"{node['name']}: {path}?{name}= returned "
                f"{response.status_code} {response.text[:200]}")


def test_documented_parameter_values_are_the_ones_the_api_accepts(workflow, client):
    """Tool descriptions enumerate allowed values for the model. If the API
    rejects one, the model will be told to send something invalid."""
    descriptions = {n["name"]: n["parameters"]["toolDescription"]
                    for n in _tool_nodes(workflow)}

    for value in ("pending", "approved", "executed", "failed", "rejected", "all"):
        assert value in descriptions["list_approvals"]
        assert client.get(f"/approvals?status={value}",
                          headers=AUTH).status_code == 200

    for value in ("candidate", "shortlisted", "drafted", "listed", "rejected"):
        assert value in descriptions["list_products"]
        assert client.get(f"/products?status={value}", headers=AUTH).status_code == 200

    for value in ("new", "cj_proposed", "cj_placed", "shipped", "delivered",
                  "attention"):
        assert value in descriptions["list_orders"]
        assert client.get(f"/orders?status={value}", headers=AUTH).status_code == 200

    for value in ("shopify", "amazon"):
        assert value in descriptions["list_orders"]
        assert client.get(f"/orders?channel={value}", headers=AUTH).status_code == 200

    for value in ("hashtag", "format", "product", "sound", "creator", "niche", "note"):
        assert value in descriptions["list_trends"]
        assert client.get(f"/trends?kind={value}", headers=AUTH).status_code == 200


def test_the_music_licensing_caveat_travels_with_the_video_tool(workflow):
    """A royalty-free bed is safe in a draft and not safe in a paid ad. The
    agent has to say so, so the warning lives in the tool description and the
    system prompt rather than only in the README."""
    tools = {n["name"]: n["parameters"]["toolDescription"] for n in _tool_nodes(workflow)}
    assert "Commercial Music Library" in tools["list_videos"]
    agent = next(n for n in workflow["nodes"] if n["name"] == "Store Manager")
    assert "Commercial Music Library" in agent["parameters"]["options"]["systemMessage"]


def test_every_tool_carries_header_auth(workflow):
    for node in _tool_nodes(workflow):
        assert node["parameters"]["authentication"] == "genericCredentialType"
        assert node["parameters"]["genericAuthType"] == "httpHeaderAuth"
        # the credential is selected on import; only the name is meaningful here
        assert node["credentials"]["httpHeaderAuth"]["name"] == "shopagent API"


def test_connections_reference_nodes_that_exist(workflow):
    names = {n["name"] for n in workflow["nodes"]}
    for source, outputs in workflow["connections"].items():
        assert source in names, f"connection from unknown node {source!r}"
        for connections in outputs.values():
            for group in connections:
                for connection in group:
                    assert connection["node"] in names


def test_every_tool_is_wired_to_the_agent(workflow):
    """A tool node that exists but isn't connected is invisible to the model."""
    for node in _tool_nodes(workflow):
        wiring = workflow["connections"].get(node["name"], {}).get("ai_tool")
        assert wiring, f"{node['name']} is not connected to the agent"
        assert wiring[0][0]["node"] == "Store Manager"


def test_system_prompt_states_the_agent_cannot_approve(workflow):
    agent = next(n for n in workflow["nodes"] if n["name"] == "Store Manager")
    prompt = agent["parameters"]["options"]["systemMessage"]
    assert "cannot approve" in prompt
    # belt and braces: the structural guarantee is that no approve tool exists,
    # but the model should also explain the limit rather than silently fail
    assert "approvals approve" in prompt


def test_tunnel_placeholder_is_obvious(workflow):
    """Shipping a stale real hostname would be worse than an obvious blank."""
    for node in _tool_nodes(workflow):
        host = urlparse(node["parameters"]["url"]).netloc
        assert "REPLACE" in host, f"{node['name']} has a hardcoded host: {host}"
