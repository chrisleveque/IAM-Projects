import json

import pytest

from shopagent.executor import Executor
from shopagent.store import Approval


@pytest.fixture
def executor(store, cfg, shopify, cj) -> Executor:
    return Executor(store, cfg, shopify, cj)


def test_only_approved_actions_execute(store, executor):
    approval_id = store.propose(Approval(
        action_type="marketing.publish", agent="marketing", title="t",
        payload={"channel": "social", "title": "t", "body": "b"}))
    with pytest.raises(ValueError, match="only approved"):
        executor.execute(approval_id)


def test_create_product_writes_back_to_pipeline(store, executor, shopify):
    product_id = store.upsert_product("CJ-PET-001", "Travel Bowl",
                                      proposed_price=9.99)
    approval_id = store.propose(Approval(
        action_type="shopify.create_product", agent="listings",
        title="List Travel Bowl",
        payload={"title": "Travel Bowl", "description_html": "<p>d</p>",
                 "tags": ["pets"], "price": 9.99, "vendor": "shopagent"},
        ref_table="products", ref_id=product_id))
    store.decide_approval(approval_id, "approved")
    a = executor.execute(approval_id)
    assert a.status == "executed"
    product = store.get_product(product_id)
    assert product["status"] == "listed"
    assert product["shopify_product_id"]
    assert any(p["title"] == "Travel Bowl" for p in shopify.list_products())


def test_cj_order_writes_back_and_failure_is_retryable(store, executor, cj):
    order_id = store.upsert_order("gid://shopify/Order/1", order_number="#1001")
    approval_id = store.propose(Approval(
        action_type="cj.create_order", agent="fulfillment", title="Fulfill #1001",
        payload={"order_ref": "#1001",
                 "cj_items": [{"vid": "V-BAD", "quantity": 1}],
                 "shipping_address": {"countryCodeV2": "US"},
                 "logistic_name": "CJPacket Ordinary"},
        ref_table="orders", ref_id=order_id))
    store.decide_approval(approval_id, "approved")
    a = executor.execute(approval_id)
    assert a.status == "failed"
    assert "unknown variant" in a.error
    assert store.get_order(order_id)["status"] == "new"  # unchanged on failure

    # fix the payload out-of-band, then retry: failed -> approved -> executed
    store.conn.execute(
        "UPDATE approvals SET payload = ? WHERE id = ?",
        (json.dumps({"order_ref": "#1001",
                     "cj_items": [{"vid": "V-PET-001-A", "quantity": 1}],
                     "shipping_address": {"countryCodeV2": "US"},
                     "logistic_name": "CJPacket Ordinary"}), approval_id))
    store.conn.commit()
    store.decide_approval(approval_id, "approved")
    a = executor.execute(approval_id)
    assert a.status == "executed"
    order = store.get_order(order_id)
    assert order["status"] == "cj_placed"
    assert order["cj_order_id"].startswith("MOCKCJ")


def test_support_reply_writes_file(store, executor, cfg):
    approval_id = store.propose(Approval(
        action_type="support.send_reply", agent="support", title="Reply to Jamie",
        payload={"customer_email": "jamie@example.com",
                 "subject": "Your order #1001", "body": "It ships this week."}))
    store.decide_approval(approval_id, "approved")
    a = executor.execute(approval_id)
    assert a.status == "executed"
    written = json.loads(a.result)["written_to"]
    content = open(written).read()
    assert "To: jamie@example.com" in content
    assert "It ships this week." in content


def test_marketing_publish_writes_channel_dir(store, executor, cfg):
    approval_id = store.propose(Approval(
        action_type="marketing.publish", agent="marketing", title="Social post",
        payload={"channel": "social", "title": "Glow walkies",
                 "body": "Night walks, but safe."}))
    store.decide_approval(approval_id, "approved")
    a = executor.execute(approval_id)
    assert a.status == "executed"
    written = json.loads(a.result)["written_to"]
    assert "/marketing/social/" in written
