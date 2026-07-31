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
                "SHOPIFY_CLIENT_SECRET", "CJ_EMAIL", "CJ_API_KEY",
                "AMZ_CLIENT_ID", "AMZ_CLIENT_SECRET", "AMZ_REFRESH_TOKEN",
                "AMZ_SELLER_ID"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "config.yaml").write_text("mode: live\n")
    cfg = load_config(tmp_path)
    assert cfg.shopify_mode() == "mock"
    assert cfg.shopify_auth_method() == "none"
    assert cfg.cj_mode() == "mock"
    assert cfg.amazon_mode() == "mock"


def test_amazon_mode_requires_all_four_credentials(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("mode: live\n")
    for var in ("AMZ_CLIENT_ID", "AMZ_CLIENT_SECRET", "AMZ_REFRESH_TOKEN",
                "AMZ_SELLER_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AMZ_CLIENT_ID", "cid")
    monkeypatch.setenv("AMZ_CLIENT_SECRET", "csec")
    monkeypatch.setenv("AMZ_REFRESH_TOKEN", "rtok")
    # AMZ_SELLER_ID still missing -> mock
    assert load_config(tmp_path).amazon_mode() == "mock"
    monkeypatch.setenv("AMZ_SELLER_ID", "SELLER1")
    assert load_config(tmp_path).amazon_mode() == "live"


def test_amazon_mode_mock_in_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("AMZ_CLIENT_ID", "cid")
    monkeypatch.setenv("AMZ_CLIENT_SECRET", "csec")
    monkeypatch.setenv("AMZ_REFRESH_TOKEN", "rtok")
    monkeypatch.setenv("AMZ_SELLER_ID", "SELLER1")
    cfg = load_config(tmp_path)  # default mode is dry_run
    assert cfg.amazon_mode() == "mock"


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


def test_render_engine_auto_follows_the_key(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("mode: dry_run\n", encoding="utf-8")
    monkeypatch.delenv("JSON2VIDEO_API_KEY", raising=False)
    assert load_config(tmp_path).render_engine() == "ffmpeg"
    monkeypatch.setenv("JSON2VIDEO_API_KEY", "k")
    # engine choice is deliberately independent of dry_run/live: a render is
    # not a customer-facing mutation
    assert load_config(tmp_path).render_engine() == "json2video"


def test_render_engine_explicit_choices(tmp_path, monkeypatch):
    monkeypatch.setenv("JSON2VIDEO_API_KEY", "k")
    (tmp_path / "config.yaml").write_text(
        "mode: dry_run\nvideo:\n  engine: ffmpeg\n", encoding="utf-8")
    assert load_config(tmp_path).render_engine() == "ffmpeg"
    (tmp_path / "config.yaml").write_text(
        "mode: dry_run\nvideo:\n  engine: json2video\n", encoding="utf-8")
    assert load_config(tmp_path).render_engine() == "json2video"


def test_render_engine_json2video_without_key_degrades_to_ffmpeg(tmp_path,
                                                                 monkeypatch):
    monkeypatch.delenv("JSON2VIDEO_API_KEY", raising=False)
    (tmp_path / "config.yaml").write_text(
        "mode: dry_run\nvideo:\n  engine: json2video\n", encoding="utf-8")
    assert load_config(tmp_path).render_engine() == "ffmpeg"


def test_render_engine_rejects_unknown_values(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "mode: dry_run\nvideo:\n  engine: imovie\n", encoding="utf-8")
    with pytest.raises(ValueError, match="video.engine must be"):
        load_config(tmp_path).render_engine()
