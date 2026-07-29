"""HTTP API tests.

The security properties matter more than the JSON shapes here: no token means
no access, and there must be no way to create an approval over HTTP — an
external caller can only read the pipeline and decide on what agents proposed
locally.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shopagent.api import create_app
from shopagent.store import Approval, Store

TOKEN = "test-token-do-not-reuse"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(cfg) -> TestClient:
    return TestClient(create_app(cfg, TOKEN))


@pytest.fixture
def seeded(cfg) -> Store:
    """A store with one pending approval linked to a product."""
    store = Store(cfg.db_path)
    product_id = store.upsert_product("CJ-PET-001", "Silicone Lick Mat",
                                      supplier_price=4.2, proposed_price=18.99,
                                      status="drafted")
    store.propose(Approval(
        action_type="shopify.create_product", agent="listings",
        title="List Silicone Lick Mat at $18.99",
        payload={"title": "Silicone Lick Mat", "description_html": "<p>x</p>",
                 "tags": "pets", "price": 18.99, "vendor": "FurrFlow"},
        rationale="4.2 cost against an 18.99 price clears the margin floor",
        ref_table="products", ref_id=product_id))
    yield store
    store.close()


# --------------------------------------------------------------------- auth

def test_token_is_mandatory_at_construction(cfg):
    # an untokened API would be an open remote control for a live store
    with pytest.raises(ValueError, match="API token is required"):
        create_app(cfg, "")


def test_requests_without_a_token_are_rejected(client, seeded):
    for path in ("/status", "/approvals", "/approvals/1", "/products", "/orders"):
        assert client.get(path).status_code == 401, path
    assert client.post("/approvals/1/approve").status_code == 401
    assert client.post("/approvals/1/reject").status_code == 401


def test_wrong_and_truncated_tokens_are_rejected(client):
    assert client.get("/status", headers={"Authorization": "Bearer nope"}
                      ).status_code == 401
    # a prefix comparison would let this through
    assert client.get("/status", headers={"Authorization": f"Bearer {TOKEN[:10]}"}
                      ).status_code == 401
    assert client.get("/status", headers={"Authorization": TOKEN}).status_code == 401


def test_health_needs_no_token_and_leaks_nothing(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "shopagent"}


# ---------------------------------------------------------------- read side

def test_status_reports_modes_and_counts(client, seeded):
    body = client.get("/status", headers=AUTH).json()
    assert body["mode"] == "dry_run"
    assert body["integrations"] == {"shopify": "mock", "cj": "mock", "amazon": "mock"}
    assert body["pending_approvals"] == 1
    assert body["products"]["drafted"] == 1
    assert body["products"]["listed"] == 0


def test_approvals_list_omits_payload_but_detail_includes_it(client, seeded):
    listed = client.get("/approvals", headers=AUTH).json()
    assert listed["count"] == 1
    summary = listed["approvals"][0]
    assert summary["action_type"] == "shopify.create_product"
    assert summary["status"] == "pending"
    assert "payload" not in summary  # list view stays small enough to scan

    detail = client.get(f"/approvals/{summary['id']}", headers=AUTH).json()
    assert detail["payload"]["price"] == 18.99
    assert detail["rationale"].startswith("4.2 cost")
    assert detail["ref_table"] == "products"


def test_approvals_list_filters_by_status(client, seeded):
    assert client.get("/approvals?status=executed", headers=AUTH).json()["count"] == 0
    assert client.get("/approvals?status=all", headers=AUTH).json()["count"] == 1
    bad = client.get("/approvals?status=banana", headers=AUTH)
    assert bad.status_code == 400
    assert "status must be" in bad.json()["detail"]


def test_missing_approval_is_404(client, seeded):
    assert client.get("/approvals/999", headers=AUTH).status_code == 404


def test_products_and_orders_are_readable_and_validated(client, seeded):
    products = client.get("/products", headers=AUTH).json()
    assert products["count"] == 1
    assert products["products"][0]["name"] == "Silicone Lick Mat"
    assert client.get("/products?status=listed", headers=AUTH).json()["count"] == 0
    assert client.get("/products?status=banana", headers=AUTH).status_code == 400
    assert client.get("/orders", headers=AUTH).json()["count"] == 0


def test_orders_filter_by_channel(client, cfg, seeded):
    seeded.upsert_order("SHOP-1", channel="shopify", order_number="#1001")
    seeded.upsert_order("111-2233445-6677889", channel="amazon", order_number="AMZ-1")
    assert client.get("/orders", headers=AUTH).json()["count"] == 2
    amazon_only = client.get("/orders?channel=amazon", headers=AUTH).json()
    assert amazon_only["count"] == 1
    assert amazon_only["orders"][0]["order_number"] == "AMZ-1"


# ------------------------------------------------------------ the gate holds

def test_there_is_no_way_to_propose_an_action_over_http(client):
    """The whole approval model rests on this: proposals originate from agents
    running locally, never from a network caller."""
    mutating = {route.path for route in client.app.routes
                if getattr(route, "methods", None)
                and {"POST", "PUT", "PATCH", "DELETE"} & route.methods}
    # every mutating route decides on an approval that already exists; none
    # of them can bring a new one into being
    assert mutating == {"/approvals/{approval_id}/approve",
                        "/approvals/{approval_id}/reject",
                        "/approvals/{approval_id}/retry"}


def test_decisions_are_post_only(client, seeded):
    # a GET that mutates would fire on link preview or crawler fetch
    assert client.get("/approvals/1/approve", headers=AUTH).status_code == 405
    assert client.get("/approvals/1/reject", headers=AUTH).status_code == 405


# ------------------------------------------------------------ decision side

def test_approve_executes_and_writes_back(client, seeded):
    body = client.post("/approvals/1/approve", headers=AUTH).json()
    assert body["status"] == "executed"
    assert body["result"]["id"]  # the mock Shopify product id
    product = seeded.get_product(1)
    assert product["status"] == "listed"
    assert product["shopify_product_id"]


def test_approving_twice_is_a_conflict_not_a_second_execution(client, seeded):
    assert client.post("/approvals/1/approve", headers=AUTH).json()["status"] == "executed"
    second = client.post("/approvals/1/approve", headers=AUTH)
    assert second.status_code == 409
    assert "executed" in second.json()["detail"]


def test_reject_records_the_note_and_blocks_execution(client, seeded):
    body = client.post("/approvals/1/reject", headers=AUTH,
                       json={"note": "margin too thin"}).json()
    assert body["status"] == "rejected"
    assert "margin too thin" in seeded.get_approval(1).rationale
    assert client.post("/approvals/1/approve", headers=AUTH).status_code == 409


def test_reject_works_without_a_body(client, seeded):
    assert client.post("/approvals/1/reject", headers=AUTH).json()["status"] == "rejected"


def test_execution_failure_reports_status_failed_not_an_http_error(client, cfg):
    """A failed action still means the *decision* succeeded, and the caller
    needs the error text — so it is 200 with status 'failed'."""
    store = Store(cfg.db_path)
    store.propose(Approval(
        action_type="shopify.update_product", agent="listings",
        title="Update a product that does not exist",
        payload={"shopify_product_id": "gid://shopify/Product/does-not-exist",
                 "fields": {"title": "x"}}))
    store.close()
    response = client.post("/approvals/1/approve", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"]


def test_retry_only_applies_to_failed_approvals(client, seeded):
    not_failed = client.post("/approvals/1/retry", headers=AUTH)
    assert not_failed.status_code == 409
    assert "pending" in not_failed.json()["detail"]
    assert client.post("/approvals/999/retry", headers=AUTH).status_code == 404
