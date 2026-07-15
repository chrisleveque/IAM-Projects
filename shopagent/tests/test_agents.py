"""Agent wiring tests: scripted FakeAIClient tool sequences prove each agent's
tools are correctly registered and produce valid pipeline rows / approvals."""

from __future__ import annotations

import json

import pytest

from shopagent.agents.fulfillment import FulfillmentAgent
from shopagent.agents.listings import ListingsAgent
from shopagent.agents.marketing import MarketingAgent
from shopagent.agents.research import ResearchAgent, proposed_retail
from shopagent.agents.support import SupportAgent

from .conftest import FakeAIClient


def test_proposed_retail_rounds_to_99():
    assert proposed_retail(3.20, 2.5) == 8.99
    assert proposed_retail(8.90, 2.5) == 22.99
    assert proposed_retail(0.5, 2.5) == 4.99  # floor


def test_research_agent_saves_and_shortlists(store, cfg, cj):
    ai = FakeAIClient(script=[
        ("search_supplier_products", {"keyword": "pet"}),
        ("estimate_shipping", {"vid": "V-PET-001-A"}),
        ("save_candidate", {"pid": "CJ-PET-001", "vid": "V-PET-001-A",
                            "name": "Collapsible Silicone Pet Travel Bowl (2-Pack)",
                            "niche": "pet accessories", "supplier_price": 3.20,
                            "shipping_estimate": 2.00, "shortlist": True,
                            "notes": "light, cheap to ship"}),
    ])
    agent = ResearchAgent(ai, store, cfg, cj=cj)
    agent.run("research pets")
    shortlisted = store.list_products("shortlisted")
    assert len(shortlisted) == 1
    assert shortlisted[0]["proposed_price"] == 8.99
    assert store.list_runs()[0]["agent"] == "research"


def test_research_agent_rejects_thin_margin(store, cfg, cj):
    ai = FakeAIClient(script=[
        ("save_candidate", {"pid": "CJ-X", "vid": "V-X", "name": "Cheap Thing",
                            "niche": "misc", "supplier_price": 1.00,
                            "shipping_estimate": 4.00}),
    ])
    ResearchAgent(ai, store, cfg, cj=cj).run("research")
    assert store.list_products() == []
    saved = ai.calls[0][2]
    assert saved["saved"] is False and "margin" in saved["reason"]


def test_listings_agent_drafts_and_proposes(store, cfg):
    product_id = store.upsert_product("CJ-PET-001", "Travel Bowl",
                                      cj_vid="V-PET-001-A", supplier_price=3.2,
                                      proposed_price=8.99)
    store.update_product(product_id, status="shortlisted")
    ai = FakeAIClient(script=[
        ("get_candidate", {"product_id": product_id}),
        ("save_listing_draft", {"product_id": product_id, "title": "Fold-Flat Travel Bowls",
                                "description_html": "<p>Water anywhere.</p>",
                                "tags": ["pets", "travel"], "price": 8.99}),
        ("propose_action", {"action_type": "shopify.create_product",
                            "title": "List: Fold-Flat Travel Bowls",
                            "payload": {"title": "Fold-Flat Travel Bowls",
                                        "description_html": "<p>Water anywhere.</p>",
                                        "tags": ["pets", "travel"], "price": 8.99,
                                        "vendor": "shopagent"},
                            "rationale": "strong margin", "ref_table": "products",
                            "ref_id": product_id}),
    ])
    ListingsAgent(ai, store, cfg).run("draft listings")
    assert store.get_product(product_id)["status"] == "drafted"
    pending = store.list_approvals("pending")
    assert len(pending) == 1
    assert pending[0].action_type == "shopify.create_product"
    assert pending[0].ref_id == product_id


def test_fulfillment_agent_syncs_maps_and_proposes(store, cfg, shopify, cj):
    # pipeline knows the collar product, so order #1001 (sku V-PET-002-A) maps
    store.upsert_product("CJ-PET-002", "LED Safety Dog Collar, USB Rechargeable",
                         cj_vid="V-PET-002-A")
    ai = FakeAIClient(script=[("sync_shopify_orders", {})])
    agent = FulfillmentAgent(ai, store, cfg, shopify=shopify, cj=cj)
    agent.run("sync")
    orders = store.list_orders()
    assert len(orders) == 2

    order = store.get_order_by_shopify_id("gid://shopify/Order/8000000001")
    ai2 = FakeAIClient(script=[
        ("map_line_items_to_cj", {"order_id": order["id"]}),
        ("propose_action", {"action_type": "cj.create_order",
                            "title": f"Fulfill {order['order_number']} via CJ",
                            "payload": {"order_ref": order["order_number"],
                                        "cj_items": [{"vid": "V-PET-002-A", "quantity": 1}],
                                        "shipping_address": json.loads(
                                            order["shipping_address_json"]),
                                        "logistic_name": "CJPacket Ordinary"},
                            "rationale": "all items map", "ref_table": "orders",
                            "ref_id": order["id"]}),
        ("update_order_status", {"order_id": order["id"], "status": "cj_proposed"}),
    ])
    FulfillmentAgent(ai2, store, cfg, shopify=shopify, cj=cj).run("fulfill")
    mapped = ai2.calls[0][2]
    assert mapped["cj_items"] == [{"vid": "V-PET-002-A", "quantity": 1}]
    assert mapped["unmapped"] == []
    assert store.get_order(order["id"])["status"] == "cj_proposed"
    assert store.list_approvals("pending")[0].action_type == "cj.create_order"


def test_fulfillment_unmapped_items_reported(store, cfg, shopify, cj):
    ai = FakeAIClient(script=[("sync_shopify_orders", {})])
    FulfillmentAgent(ai, store, cfg, shopify=shopify, cj=cj).run("sync")
    order = store.get_order_by_shopify_id("gid://shopify/Order/8000000002")
    ai2 = FakeAIClient(script=[("map_line_items_to_cj", {"order_id": order["id"]})])
    FulfillmentAgent(ai2, store, cfg, shopify=shopify, cj=cj).run("map")
    mapped = ai2.calls[0][2]
    # sku still maps via by_vid? V-PET-001-A not in pipeline -> unmapped
    assert mapped["cj_items"] == []
    assert mapped["unmapped"]


def test_support_agent_reads_inbox_and_proposes_reply(store, cfg):
    (cfg.inbox_dir / "msg.txt").write_text(
        "From: jamie.rivera@example.com\nSubject: Where is #1001?\n\nAny update?\n")
    order_id = store.upsert_order("gid://shopify/Order/8000000001",
                                  order_number="#1001",
                                  customer_email="jamie.rivera@example.com")
    store.update_order(order_id, status="shipped", tracking_number="CJMOCK000001")
    ai = FakeAIClient(script=[
        ("list_inbox", {}),
        ("read_message", {"filename": "msg.txt"}),
        ("lookup_order", {"order_number": "#1001"}),
        ("propose_action", {"action_type": "support.send_reply",
                            "title": "Reply: where is #1001",
                            "payload": {"customer_email": "jamie.rivera@example.com",
                                        "subject": "Your order #1001 has shipped",
                                        "body": "Tracking: CJMOCK000001"},
                            "rationale": "customer asked for status"}),
    ])
    SupportAgent(ai, store, cfg).run("handle inbox")
    looked_up = ai.calls[2][2]
    assert looked_up["tracking_number"] == "CJMOCK000001"
    assert store.list_approvals("pending")[0].action_type == "support.send_reply"


def test_marketing_agent_grounds_in_listing(store, cfg):
    product_id = store.upsert_product("CJ-PET-001", "Travel Bowl", niche="pet accessories",
                                      proposed_price=8.99)
    store.update_product(product_id, status="listed",
                         listing_json=json.dumps({"title": "Fold-Flat Travel Bowls",
                                                  "tags": ["pets"]}))
    ai = FakeAIClient(script=[
        ("get_listed_products", {}),
        ("propose_action", {"action_type": "marketing.publish",
                            "title": "Social: travel bowls",
                            "payload": {"channel": "social", "title": "Adventure hydration",
                                        "body": "Fold-flat bowls. #pets"},
                            "rationale": "promote new listing",
                            "ref_table": "products", "ref_id": product_id}),
    ])
    MarketingAgent(ai, store, cfg).run("promote")
    listed = ai.calls[0][2]
    assert listed[0]["listing"]["title"] == "Fold-Flat Travel Bowls"
    assert store.list_approvals("pending")[0].action_type == "marketing.publish"


def test_agent_tool_error_is_recorded_not_fatal(store, cfg):
    ai = FakeAIClient(script=[("get_candidate", {"product_id": 999}),
                              ("save_listing_draft", {"product_id": 999, "title": "x",
                                                      "description_html": "y",
                                                      "tags": [], "price": 1.0})])
    result = ListingsAgent(ai, store, cfg).run("draft")
    # handlers return error dicts rather than raising; run is logged either way
    assert result.tool_calls == 2
    assert store.list_runs()[0]["agent"] == "listings"


def test_propose_action_validates_bad_payload(store, cfg):
    ai = FakeAIClient(script=[
        ("propose_action", {"action_type": "cj.create_order", "title": "bad",
                            "payload": {"order_ref": "#1"},
                            "rationale": "missing keys"}),
    ])
    result = MarketingAgent(ai, store, cfg).run("x")
    assert result.errors and "missing keys" in result.errors[0]
    assert store.list_approvals("pending") == []
