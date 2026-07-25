"""CLI test for 'products clear': wiping the local pipeline to start clean.

This only touches shopagent's own tracking table — it never calls Shopify,
Amazon, or CJ, so there's nothing to mock beyond the store itself.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from shopagent.cli import app
from shopagent.store import Store

runner = CliRunner()


def _init_project(tmp_path: Path) -> Path:
    (tmp_path / "config.yaml").write_text("mode: dry_run\n")
    (tmp_path / "inbox").mkdir()
    return tmp_path


def test_clear_with_yes_deletes_all_products_without_prompt(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    store = Store(root / "shopagent.db")
    store.upsert_product("CJ-1", "Thing One")
    store.upsert_product("CJ-2", "Thing Two")
    store.close()

    result = runner.invoke(app, ["products", "clear", "--yes"])
    assert result.exit_code == 0, result.output
    assert "cleared 2 product(s)" in result.output

    store = Store(root / "shopagent.db")
    assert store.list_products() == []
    store.close()


def test_clear_without_yes_prompts_and_respects_decline(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    store = Store(root / "shopagent.db")
    store.upsert_product("CJ-1", "Thing One")
    store.close()

    result = runner.invoke(app, ["products", "clear"], input="n\n")
    assert result.exit_code != 0
    assert "cancelled" in result.output

    store = Store(root / "shopagent.db")
    assert len(store.list_products()) == 1
    store.close()


def test_clear_without_yes_confirmed_deletes(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    store = Store(root / "shopagent.db")
    store.upsert_product("CJ-1", "Thing One")
    store.close()

    result = runner.invoke(app, ["products", "clear"], input="y\n")
    assert result.exit_code == 0, result.output

    store = Store(root / "shopagent.db")
    assert store.list_products() == []
    store.close()


def test_clear_on_empty_pipeline_is_a_noop(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    result = runner.invoke(app, ["products", "clear", "--yes"])
    assert result.exit_code == 0, result.output
    assert "no products to clear" in result.output


def test_clear_does_not_touch_orders_or_approvals(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    store = Store(root / "shopagent.db")
    store.upsert_product("CJ-1", "Thing One")
    store.upsert_order("gid://shopify/Order/1", order_number="#1001")
    store.close()

    result = runner.invoke(app, ["products", "clear", "--yes"])
    assert result.exit_code == 0, result.output

    store = Store(root / "shopagent.db")
    assert store.list_products() == []
    assert len(store.list_orders()) == 1
    store.close()
