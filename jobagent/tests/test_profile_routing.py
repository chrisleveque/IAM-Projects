from jobagent.browser import profile_dir_for
from jobagent.config import AppConfig


def make_cfg(tmp_path) -> AppConfig:
    cfg = AppConfig()
    cfg.root = tmp_path
    return cfg


def test_default_profile_unchanged(tmp_path):
    cfg = make_cfg(tmp_path)
    assert profile_dir_for(cfg, "default") == (tmp_path / "browser_profile").resolve()
    assert profile_dir_for(cfg, "") == (tmp_path / "browser_profile").resolve()


def test_site_profiles_are_separate(tmp_path):
    cfg = make_cfg(tmp_path)
    li = profile_dir_for(cfg, "linkedin")
    ind = profile_dir_for(cfg, "indeed")
    assert li.name == "browser_profile-linkedin"
    assert ind.name == "browser_profile-indeed"
    assert li != ind
