import pytest

from fitagent.config import AppConfig, load_config


def test_defaults_and_paths(tmp_path):
    (tmp_path / "config.yaml").write_text("mode: dry_run\n", encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.mode == "dry_run"
    assert cfg.preset().channel_name
    assert cfg.db_path == tmp_path / "fitagent.db"
    assert cfg.music_dir == tmp_path / "assets" / "music"


def test_invalid_mode_rejected(tmp_path):
    (tmp_path / "config.yaml").write_text("mode: bogus\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(tmp_path)


def test_dry_run_forces_mock_stock(monkeypatch):
    cfg = AppConfig()
    monkeypatch.setenv("PEXELS_API_KEY", "k")
    cfg.mode = "dry_run"
    assert cfg.stock_mode() == "mock"
    cfg.mode = "live"
    assert cfg.stock_mode() == "live"


def test_live_without_keys_is_mock(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    cfg = AppConfig()
    cfg.mode = "live"
    assert cfg.stock_mode() == "mock"


def test_elevenlabs_falls_back_to_edge_without_creds(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    cfg = AppConfig()
    preset = cfg.preset()
    preset.tts.provider = "elevenlabs"
    assert cfg.tts_provider(preset) == "edge"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")
    assert cfg.tts_provider(preset) == "elevenlabs"


def test_unknown_preset_rejected():
    cfg = AppConfig()
    with pytest.raises(ValueError):
        cfg.preset("nope")
