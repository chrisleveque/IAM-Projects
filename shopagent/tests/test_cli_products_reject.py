"""CLI test for 'products reject': excluding stale/invalid pipeline rows (e.g.
dry-run leftovers with fake Shopify ids) from future listing/cross-listing runs."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from shopagent.cli import app
from shopagent.orchestrator import Orchestrator
from shopagent.store import Store

runner = CliRunner()


def _init_project(tmp_path: Path) -> Path:
    (tmp_path / "config.yaml").write_text("mode: dry_run\n")
    (tmp_path / "inbox").mkdir()
    return tmp_path


def test_reject_marks_product_and_records_note(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    store = Store(root / "shopagent.db")
    pid = store.upsert_product("CJ-FAKE-001", "Leftover Dry-Run Product",
                               shopify_product_id="gid://shopify/Product/9000000100")
    store.update_product(pid, status="listed")
    store.close()

    result = runner.invoke(app, ["products", "reject", str(pid),
                                 "--note", "dry-run leftover, not a real product"])
    assert result.exit_code == 0, result.output
    assert "rejected" in result.output

    store = Store(root / "shopagent.db")
    product = store.get_product(pid)
    assert product["status"] == "rejected"
    assert "dry-run leftover" in product["notes"]
    store.close()


def test_reject_unknown_id_fails_cleanly(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    result = runner.invoke(app, ["products", "reject", "999"])
    assert result.exit_code != 0
    assert "no product" in result.output


def test_rejected_product_excluded_from_amazon_cross_listing(cfg, store, shopify,
                                                              cj, amazon):
    pid = store.upsert_product("CJ-FAKE-001", "Leftover Dry-Run Product",
                               shopify_product_id="gid://shopify/Product/9000000100")
    store.update_product(pid, status="listed")
    store.update_product(pid, status="rejected", notes="dry-run leftover")

    class ExplodingAI:
        def run_tools(self, *a, **kw):
            raise AssertionError("amazon agent should not run for a rejected product")

    orch = Orchestrator(ExplodingAI(), store, cfg, shopify, cj, amazon=amazon)
    summary = orch.run_daily()
    steps = {s["agent"]: s for s in summary["steps"]}
    assert steps["amazon"].get("skipped")
