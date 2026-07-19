import pytest

from shopagent.config import AppConfig, load_config, normalize_shop_domain


def test_normalize_shop_domain():
    assert normalize_shop_domain(" https://x.myshopify.com/ ") == "x.myshopify.com"
    assert normalize_shop_domain("http://x.myshopify.com/admin") == "x.myshopify.com"
    assert normalize_shop_domain("cbm3b0-cs.myshopify.com") == "cbm3b0-cs.myshopify.com"
    assert normalize_shop_domain("") == ""


def test_shop_domain_env_is_normalized(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "https://x.myshopify.com/")
    cfg = load_config(tmp_path)
    assert cfg.shop_domain == "x.myshopify.com"


def test_defaults_are_dry_run(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.mode == "dry_run"
    assert cfg.shopify_mode() == "mock"
    assert cfg.cj_mode() == "mock"


def test_invalid_mode_rejected(tmp_path):
    (tmp_path / "config.yaml").write_text("mode: yolo\n")
    with pytest.raises(ValueError, match="mode"):
        load_config(tmp_path)


def test_live_mode_without_credentials_degrades_to_mock(tmp_path, monkeypatch):
    for var in ("SHOPIFY_STORE_DOMAIN", "SHOPIFY_ACCESS_TOKEN", "SHOPIFY_CLIENT_ID",
                "SHOPIFY_CLIENT_SECRET", "CJ_EMAIL", "CJ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "config.yaml").write_text("mode: live\n")
    cfg = load_config(tmp_path)
    assert cfg.shopify_mode() == "mock"
    assert cfg.shopify_auth_method() == "none"
    assert cfg.cj_mode() == "mock"


def test_live_mode_with_client_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("SHOPIFY_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "x.myshopify.com")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "csecret")
    (tmp_path / "config.yaml").write_text("mode: live\n")
    cfg = load_config(tmp_path)
    assert cfg.shopify_mode() == "live"
    assert cfg.shopify_auth_method() == "client_credentials"


def test_half_client_credentials_stays_mock(tmp_path, monkeypatch):
    monkeypatch.delenv("SHOPIFY_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SHOPIFY_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "x.myshopify.com")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    (tmp_path / "config.yaml").write_text("mode: live\n")
    cfg = load_config(tmp_path)
    assert cfg.shopify_mode() == "mock"


def test_live_mode_with_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "x.myshopify.com")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test")
    monkeypatch.setenv("CJ_EMAIL", "a@b.c")
    monkeypatch.setenv("CJ_API_KEY", "key")
    (tmp_path / "config.yaml").write_text("mode: live\n")
    cfg = load_config(tmp_path)
    assert cfg.shopify_mode() == "live"
    assert cfg.cj_mode() == "live"


def test_yaml_overrides(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "business:\n  pricing:\n    markup_multiplier: 3.0\nai:\n  model: claude-sonnet-5\n")
    cfg = load_config(tmp_path)
    assert cfg.business.pricing.markup_multiplier == 3.0
    assert cfg.ai.model == "claude-sonnet-5"


def test_paths_resolve_under_root(tmp_path):
    cfg = AppConfig()
    cfg.root = tmp_path
    assert cfg.db_path == tmp_path / "shopagent.db"
    assert cfg.inbox_dir == tmp_path / "inbox"
