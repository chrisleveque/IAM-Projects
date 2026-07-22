"""Mock end-to-end dry run: daily pipeline -> pending approvals -> approve ->
executed against the mock store/supplier, with write-back visible."""

from __future__ import annotations

import json

from shopagent.executor import Executor
from shopagent.orchestrator import Orchestrator

from .conftest import FakeAIClient


class ScriptedPerAgentAI:
    """Routes run_tools to a per-call FakeAIClient script, in pipeline order."""

    def __init__(self, scripts: list[FakeAIClient]):
        self.scripts = list(scripts)

    def run_tools(self, system, user, tools, handlers, max_iterations=20):
        fake = self.scripts.pop(0)
        return fake.run_tools(system, user, tools, handlers, max_iterations)


def test_daily_pipeline_end_to_end(store, cfg, shopify, cj):
    # Pipeline knows the collar so order #1001 is fulfillable, and has a
    # shortlisted product for the listings step.
    store.upsert_product("CJ-PET-002", "LED Safety Dog Collar, USB Rechargeable",
                         cj_vid="V-PET-002-A")
    bowl_id = store.upsert_product("CJ-PET-001", "Travel Bowl", cj_vid="V-PET-001-A",
                                   niche="pet accessories", supplier_price=3.2,
                                   proposed_price=8.99)
    store.update_product(bowl_id, status="shortlisted")

    fulfillment_script = FakeAIClient(script=[
        ("sync_shopify_orders", {}),
        ("map_line_items_to_cj", {"order_id": 1}),
        ("propose_action", {"action_type": "cj.create_order",
                            "title": "Fulfill #1001 via CJ",
                            "payload": {"order_ref": "#1001",
                                        "cj_items": [{"vid": "V-PET-002-A", "quantity": 1}],
                                        "shipping_address": {"name": "Jamie Rivera",
                                                             "countryCodeV2": "US"},
                                        "logistic_name": "CJPacket Ordinary"},
                            "rationale": "maps cleanly",
                            "ref_table": "orders", "ref_id": 1}),
        ("update_order_status", {"order_id": 1, "status": "cj_proposed"}),
    ], final_text="1 order proposed for fulfillment")
    support_script = FakeAIClient(script=[("list_inbox", {})],
                                  final_text="inbox empty")
    listings_script = FakeAIClient(script=[
        ("save_listing_draft", {"product_id": bowl_id, "title": "Fold-Flat Travel Bowls",
                                "description_html": "<p>Hydration anywhere.</p>",
                                "tags": ["pets", "travel"], "price": 8.99}),
        ("propose_action", {"action_type": "shopify.create_product",
                            "title": "List: Fold-Flat Travel Bowls",
                            "payload": {"title": "Fold-Flat Travel Bowls",
                                        "description_html": "<p>Hydration anywhere.</p>",
                                        "tags": ["pets", "travel"], "price": 8.99,
                                        "vendor": "shopagent"},
                            "rationale": "ready to sell",
                            "ref_table": "products", "ref_id": bowl_id}),
    ], final_text="1 listing proposed")

    # candidate pool (1 shortlisted + 1 candidate) below default threshold 3
    # would trigger research; raise scripts accordingly — research runs 3rd.
    research_script = FakeAIClient(script=[], final_text="nothing new worth saving")

    ai = ScriptedPerAgentAI([fulfillment_script, support_script,
                             research_script, listings_script])
    orch = Orchestrator(ai, store, cfg, shopify, cj)
    summary = orch.run_daily()

    steps = {s["agent"]: s for s in summary["steps"]}
    assert steps["fulfillment"]["ok"]
    assert steps["support"]["ok"]
    assert steps["research"]["ok"]          # pool of 2 < threshold 3 -> ran
    assert steps["listings"]["ok"]
    assert steps["marketing"].get("skipped")  # nothing listed yet
    assert summary["pending_approvals"] == 2

    # ---- human approves both; executor performs them against the mocks
    executor = Executor(store, cfg, shopify, cj)
    for approval in store.list_approvals("pending"):
        store.decide_approval(approval.id, "approved")
        executed = executor.execute(approval.id)
        assert executed.status == "executed", executed.error

    order = store.get_order(1)
    assert order["status"] == "cj_placed"
    assert order["cj_order_id"].startswith("MOCKCJ")
    product = store.get_product(bowl_id)
    assert product["status"] == "listed"
    assert any(p["title"] == "Fold-Flat Travel Bowls" for p in shopify.list_products())


def test_pipeline_survives_agent_failure(store, cfg, shopify, cj):
    class ExplodingAI:
        def run_tools(self, *a, **kw):
            raise RuntimeError("model unavailable")

    orch = Orchestrator(ExplodingAI(), store, cfg, shopify, cj)
    summary = orch.run_daily()
    ran = [s for s in summary["steps"] if not s.get("skipped")]
    assert ran and all(s["ok"] is False for s in ran)
    assert "model unavailable" in ran[0]["error"]


def test_daily_pipeline_emits_progress_events(store, cfg, shopify, cj):
    for i in range(3):
        store.upsert_product(f"CJ-{i}", f"Thing {i}", niche="pet accessories")
    events: list[tuple[str, dict]] = []
    ai = ScriptedPerAgentAI([FakeAIClient(final_text="orders handled"),
                             FakeAIClient(final_text="inbox handled")])
    Orchestrator(ai, store, cfg, shopify, cj).run_daily(
        on_event=lambda kind, data: events.append((kind, data)))

    # every run gets a start followed by a done; skips emit a single skip event
    assert [(k, d["agent"]) for k, d in events] == [
        ("start", "fulfillment"), ("done", "fulfillment"),
        ("start", "support"), ("done", "support"),
        ("skip", "research"),
        ("skip", "listings"),
        ("skip", "amazon"),
        ("skip", "marketing"),
    ]
    done_fulfillment = events[1][1]
    assert done_fulfillment["ok"] and done_fulfillment["summary"] == "orders handled"


def test_amazon_step_runs_for_uncrosslisted_listed_products(store, cfg, shopify, cj,
                                                              amazon):
    # pool full so research is skipped; nothing shortlisted so listings is
    # skipped; but one product is already 'listed' on Shopify with no
    # amazon_status yet, so the amazon step must run and propose a listing.
    for i in range(3):
        store.upsert_product(f"CJ-{i}", f"Thing {i}", niche="pet accessories")
    product_id = store.upsert_product("CJ-PET-002",
                                      "LED Safety Dog Collar, USB Rechargeable",
                                      cj_vid="V-PET-002-A", proposed_price=16.99)
    store.update_product(product_id, status="listed")
    attributes = {"item_name": [{"value": "LED Safety Dog Collar"}],
                  "brand": [{"value": "Generic"}]}

    amazon_script = FakeAIClient(script=[
        ("propose_action", {"action_type": "amazon.create_listing",
                            "title": "Amazon: LED Safety Dog Collar",
                            "payload": {"sku": "V-PET-002-A",
                                        "product_type": "PET_SUPPLIES",
                                        "attributes": attributes},
                            "rationale": "cross-list a Shopify winner",
                            "ref_table": "products", "ref_id": product_id}),
    ], final_text="1 Amazon listing proposed")

    ai = ScriptedPerAgentAI([FakeAIClient(final_text="orders handled"),
                             FakeAIClient(final_text="inbox handled"),
                             amazon_script])
    orch = Orchestrator(ai, store, cfg, shopify, cj, amazon=amazon)
    summary = orch.run_daily()

    steps = {s["agent"]: s for s in summary["steps"]}
    assert steps["research"].get("skipped")
    assert steps["listings"].get("skipped")
    assert steps["amazon"]["ok"]
    assert summary["pending_approvals"] == 1

    approval = store.list_approvals("pending")[0]
    assert approval.action_type == "amazon.create_listing"
    store.decide_approval(approval.id, "approved")
    executed = Executor(store, cfg, shopify, cj, amazon=amazon).execute(approval.id)
    assert executed.status == "executed", executed.error
    assert store.get_product(product_id)["amazon_status"] == "submitted"


def test_amazon_step_skipped_once_already_cross_listed(store, cfg, shopify, cj, amazon):
    product_id = store.upsert_product("CJ-PET-002", "LED Collar",
                                      cj_vid="V-PET-002-A")
    store.update_product(product_id, status="listed", amazon_status="submitted")
    ai = ScriptedPerAgentAI([FakeAIClient(), FakeAIClient()])
    summary = Orchestrator(ai, store, cfg, shopify, cj, amazon=amazon).run_daily()
    steps = {s["agent"]: s for s in summary["steps"]}
    assert steps["amazon"].get("skipped")


def test_research_skipped_when_pool_full(store, cfg, shopify, cj):
    for i in range(3):
        store.upsert_product(f"CJ-{i}", f"Thing {i}", niche="pet accessories")
    ai = ScriptedPerAgentAI([FakeAIClient(), FakeAIClient()])
    summary = Orchestrator(ai, store, cfg, shopify, cj).run_daily()
    steps = {s["agent"]: s for s in summary["steps"]}
    assert steps["research"].get("skipped")
