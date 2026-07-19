import pytest

from shopagent.store import Approval


def _approval(**kw) -> Approval:
    base = dict(
        action_type="marketing.publish",
        agent="marketing",
        title="Post about the LED collar",
        payload={"channel": "social", "title": "Glow up", "body": "Shine bright."},
        rationale="new product needs traffic",
    )
    base.update(kw)
    return Approval(**base)


def test_approval_lifecycle_approve_execute(store):
    approval_id = store.propose(_approval())
    a = store.get_approval(approval_id)
    assert a.status == "pending"
    assert a.payload["channel"] == "social"

    store.decide_approval(approval_id, "approved")
    store.mark_executed(approval_id, '{"written_to": "x"}')
    a = store.get_approval(approval_id)
    assert a.status == "executed"
    assert a.decided_at and a.executed_at


def test_approval_reject_is_terminal(store):
    approval_id = store.propose(_approval())
    store.decide_approval(approval_id, "rejected", note="not our tone")
    a = store.get_approval(approval_id)
    assert a.status == "rejected"
    assert "not our tone" in a.rationale
    with pytest.raises(ValueError):
        store.decide_approval(approval_id, "approved")


def test_failed_approval_can_be_retried(store):
    approval_id = store.propose(_approval())
    store.decide_approval(approval_id, "approved")
    store.mark_failed(approval_id, "supplier timeout")
    assert store.get_approval(approval_id).status == "failed"
    # retry path: failed -> approved again
    a = store.decide_approval(approval_id, "approved")
    assert a.status == "approved"
    assert a.error == ""


def test_propose_rejects_unknown_action_type(store):
    with pytest.raises(ValueError, match="unknown action_type"):
        store.propose(_approval(action_type="shopify.delete_everything"))


def test_propose_rejects_missing_payload_keys(store):
    with pytest.raises(ValueError, match="missing keys"):
        store.propose(_approval(action_type="cj.create_order",
                                payload={"order_ref": "#1001"}))


def test_pending_filter_and_all(store):
    a1 = store.propose(_approval())
    a2 = store.propose(_approval(title="Second"))
    store.decide_approval(a1, "rejected")
    assert [a.id for a in store.list_approvals("pending")] == [a2]
    assert len(store.list_approvals(None)) == 2


def test_product_upsert_preserves_status(store):
    pid = store.upsert_product("CJ-1", "Widget", supplier_price=3.0, niche="gadgets")
    store.update_product(pid, status="shortlisted")
    again = store.upsert_product("CJ-1", "Widget", supplier_price=3.5)
    assert again == pid
    p = store.get_product(pid)
    assert p["status"] == "shortlisted"
    assert p["supplier_price"] == 3.5


def test_product_status_validated(store):
    pid = store.upsert_product("CJ-2", "Gizmo")
    with pytest.raises(ValueError):
        store.update_product(pid, status="on_the_moon")


def test_order_upsert_preserves_cj_linkage(store):
    oid = store.upsert_order("gid://shopify/Order/1", order_number="#1001",
                             customer_email="a@example.com")
    store.update_order(oid, status="cj_placed", cj_order_id="CJ123")
    again = store.upsert_order("gid://shopify/Order/1", order_number="#1001",
                               customer_email="a@example.com")
    assert again == oid
    o = store.get_order(oid)
    assert o["status"] == "cj_placed"
    assert o["cj_order_id"] == "CJ123"


def test_images_json_migration_for_old_databases(tmp_path):
    import sqlite3

    from shopagent.store import Store
    # simulate a database created before the images_json column existed
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cj_product_id TEXT NOT NULL, cj_vid TEXT DEFAULT '',
        name TEXT NOT NULL, niche TEXT DEFAULT '',
        supplier_price REAL, shipping_estimate REAL, proposed_price REAL,
        listing_json TEXT DEFAULT '', shopify_product_id TEXT DEFAULT '',
        status TEXT DEFAULT 'candidate', notes TEXT DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(cj_product_id))""")
    conn.execute("INSERT INTO products (cj_product_id, name, created_at, updated_at)"
                 " VALUES ('CJ-OLD', 'Old Thing', 'x', 'x')")
    conn.commit()
    conn.close()

    store = Store(db)  # must add the column without touching existing rows
    p = store.list_products()[0]
    assert p["name"] == "Old Thing"
    assert p["images_json"] == "[]"
    store.close()


def test_agent_run_log(store):
    store.log_run("research", "find products", "ok", "saved 3", tool_calls=7,
                  input_tokens=100, output_tokens=50)
    runs = store.list_runs()
    assert runs[0]["agent"] == "research"
    assert runs[0]["tool_calls"] == 7
