import json

import pytest

from shopagent.executor import Executor
from shopagent.store import Approval


@pytest.fixture
def executor(store, cfg, shopify, cj, amazon) -> Executor:
    return Executor(store, cfg, shopify, cj, amazon=amazon)


def test_only_approved_actions_execute(store, executor):
    approval_id = store.propose(Approval(
        action_type="marketing.publish", agent="marketing", title="t",
        payload={"channel": "social", "title": "t", "body": "b"}))
    with pytest.raises(ValueError, match="only approved"):
        executor.execute(approval_id)


def test_create_product_writes_back_to_pipeline(store, executor, shopify):
    product_id = store.upsert_product(
        "CJ-PET-001", "Travel Bowl", proposed_price=9.99,
        images_json=json.dumps(["https://mock.cjimg.example/CJ-PET-001/1.jpg",
                                "https://mock.cjimg.example/CJ-PET-001/2.jpg"]))
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
    created = next(p for p in shopify.list_products() if p["title"] == "Travel Bowl")
    # supplier photos from the pipeline row are attached automatically
    assert len(created["images"]) == 2
    assert json.loads(a.result)["images_attached"] == 2


def test_fulfill_order_marks_shopify_and_pipeline(store, executor, shopify):
    order_id = store.upsert_order("gid://shopify/Order/8000000001",
                                  order_number="#1001")
    store.update_order(order_id, status="cj_placed", cj_order_id="MOCKCJ000001")
    approval_id = store.propose(Approval(
        action_type="shopify.fulfill_order", agent="fulfillment",
        title="Fulfill #1001 in Shopify with tracking",
        payload={"shopify_order_id": "gid://shopify/Order/8000000001",
                 "tracking_number": "CJMOCK000001", "notify_customer": True},
        ref_table="orders", ref_id=order_id))
    store.decide_approval(approval_id, "approved")
    a = executor.execute(approval_id)
    assert a.status == "executed"
    order = store.get_order(order_id)
    assert order["status"] == "shipped"
    assert order["tracking_number"] == "CJMOCK000001"
    shopify_order = shopify.get_order("gid://shopify/Order/8000000001")
    assert shopify_order["displayFulfillmentStatus"] == "FULFILLED"

    # fulfilling twice fails cleanly instead of double-notifying the customer
    again = store.propose(Approval(
        action_type="shopify.fulfill_order", agent="fulfillment", title="dup",
        payload={"shopify_order_id": "gid://shopify/Order/8000000001",
                 "tracking_number": "CJMOCK000001"}))
    store.decide_approval(again, "approved")
    a = executor.execute(again)
    assert a.status == "failed"
    assert "already fulfilled" in a.error


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


def test_amazon_create_listing_writes_back(store, executor, amazon):
    product_id = store.upsert_product("CJ-PET-002", "LED Collar",
                                      cj_vid="V-PET-002-A", proposed_price=16.99)
    approval_id = store.propose(Approval(
        action_type="amazon.create_listing", agent="amazon",
        title="Amazon: LED Collar",
        payload={"sku": "V-PET-002-A", "product_type": "PET_SUPPLIES",
                 "attributes": {"item_name": [{"value": "LED Collar"}],
                                "brand": [{"value": "Generic"}]}},
        ref_table="products", ref_id=product_id))
    store.decide_approval(approval_id, "approved")
    a = executor.execute(approval_id)
    assert a.status == "executed", a.error
    product = store.get_product(product_id)
    assert product["amazon_sku"] == "V-PET-002-A"
    assert product["amazon_status"] == "submitted"
    assert product["amazon_submission_id"].startswith("MOCKSUB")
    assert amazon.get_listing("V-PET-002-A") is not None


def test_amazon_confirm_shipment_writes_back(store, executor, amazon):
    order_id = store.upsert_order("111-2233445-6677889", channel="amazon",
                                  order_number="111-2233445-6677889")
    store.update_order(order_id, status="cj_placed", cj_order_id="MOCKCJ000009")
    approval_id = store.propose(Approval(
        action_type="amazon.confirm_shipment", agent="fulfillment",
        title="Confirm shipment for 111-2233445-6677889",
        payload={"amazon_order_id": "111-2233445-6677889",
                 "tracking_number": "CJMOCK000009", "carrier_code": "Other",
                 "order_items": [{"order_item_id": "OI-0001", "quantity": 1}]},
        ref_table="orders", ref_id=order_id))
    store.decide_approval(approval_id, "approved")
    a = executor.execute(approval_id)
    assert a.status == "executed", a.error
    order = store.get_order(order_id)
    assert order["status"] == "shipped"
    assert order["tracking_number"] == "CJMOCK000009"
    assert len(amazon.list_unshipped_orders()) == 1  # one of two seeds shipped

    # confirming again fails cleanly
    again = store.propose(Approval(
        action_type="amazon.confirm_shipment", agent="fulfillment", title="dup",
        payload={"amazon_order_id": "111-2233445-6677889",
                 "tracking_number": "CJMOCK000009", "carrier_code": "Other",
                 "order_items": []}))
    store.decide_approval(again, "approved")
    assert executor.execute(again).status == "failed"


def test_amazon_update_price(store, executor, amazon):
    amazon.put_listing("V-PET-002-A", "PET_SUPPLIES", {})
    approval_id = store.propose(Approval(
        action_type="amazon.update_price", agent="amazon", title="Reprice",
        payload={"sku": "V-PET-002-A", "product_type": "PET_SUPPLIES",
                 "price": 18.99}))
    store.decide_approval(approval_id, "approved")
    assert executor.execute(approval_id).status == "executed"


def test_support_reply_writes_file(store, executor, cfg):
    approval_id = store.propose(Approval(
        action_type="support.send_reply", agent="support", title="Reply to Jamie",
        payload={"customer_email": "jamie@example.com",
                 "subject": "Your order #1001", "body": "It ships this week."}))
    store.decide_approval(approval_id, "approved")
    a = executor.execute(approval_id)
    assert a.status == "executed"
    written = json.loads(a.result)["written_to"]
    content = open(written, encoding="utf-8").read()
    assert "To: jamie@example.com" in content
    assert "It ships this week." in content


def test_marketing_publish_writes_channel_dir(store, executor, cfg):
    # emoji in the body: agents produce these routinely, and files must be
    # written as utf-8 even where the platform default is cp1252 (Windows)
    approval_id = store.propose(Approval(
        action_type="marketing.publish", agent="marketing", title="Social post",
        payload={"channel": "social", "title": "Glow walkies",
                 "body": "Night walks, but safe. \U0001F415✨ #glowup"}))
    store.decide_approval(approval_id, "approved")
    a = executor.execute(approval_id)
    assert a.status == "executed"
    written = json.loads(a.result)["written_to"]
    assert "/marketing/social/" in written
    assert "\U0001F415" in open(written, encoding="utf-8").read()
