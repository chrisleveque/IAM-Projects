"""CLI test for 'products import': reconciling products sourced/listed manually
(outside shopagent's own research/listings flow) into the local pipeline."""

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


def test_import_registers_mock_cj_product(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    result = runner.invoke(app, ["products", "import", "CJ-PET-001", "--price", "79.99",
                                 "--shopify-id", "gid://shopify/Product/999",
                                 "--status", "listed"])
    assert result.exit_code == 0, result.output
    assert "imported" in result.output

    store = Store(root / "shopagent.db")
    products = store.list_products()
    assert len(products) == 1
    p = products[0]
    assert p["cj_product_id"] == "CJ-PET-001"
    assert p["cj_vid"]
    assert p["status"] == "listed"
    assert p["proposed_price"] == 79.99
    assert p["shopify_product_id"] == "gid://shopify/Product/999"
    assert p["supplier_price"] > 0
    assert p["images_json"] != "[]"
    store.close()


def test_import_unknown_pid_fails_cleanly(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    result = runner.invoke(app, ["products", "import", "NOPE-404", "--price", "9.99"])
    assert result.exit_code != 0
    assert "no CJ product found" in result.output


def test_import_records_amazon_fields(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    result = runner.invoke(app, ["products", "import", "CJ-PET-002", "--price", "22.99",
                                 "--amazon-sku", "V-PET-002-A",
                                 "--amazon-status", "submitted"])
    assert result.exit_code == 0, result.output
    store = Store(root / "shopagent.db")
    p = store.list_products()[0]
    assert p["amazon_sku"] == "V-PET-002-A"
    assert p["amazon_status"] == "submitted"
    store.close()


def test_import_rejects_bad_status(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    result = runner.invoke(app, ["products", "import", "CJ-PET-001", "--price", "10",
                                 "--status", "on_the_moon"])
    assert result.exit_code != 0
    assert "must be one of" in result.output


def test_import_twice_updates_rather_than_duplicates(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    runner.invoke(app, ["products", "import", "CJ-PET-001", "--price", "70"])
    result = runner.invoke(app, ["products", "import", "CJ-PET-001", "--price", "79.99"])
    assert result.exit_code == 0, result.output

    store = Store(root / "shopagent.db")
    products = store.list_products()
    assert len(products) == 1
    assert products[0]["proposed_price"] == 79.99
    store.close()
