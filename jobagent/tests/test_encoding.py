"""Regression tests for Windows: files must be read/written as UTF-8 explicitly,
never the locale default (cp1252 on Windows chokes on é, ·, — etc.)."""

from jobagent.cli import _answers, _master_resume
from jobagent.config import AppConfig, load_config

UNICODE_RESUME = (
    "# Chris Levequé\n\nCity, ST · chris@example.com · (555) 555-5555\n\n"
    "## Experience\n\n### Acme — IAM Engineer\n- Improved onboarding by 40%\n"
)


def make_project(tmp_path):
    (tmp_path / "profile").mkdir()
    (tmp_path / "config.yaml").write_text(
        'searches:\n  - source: linkedin\n    query: "café manager — remote"\n',
        encoding="utf-8",
    )
    (tmp_path / "profile" / "master_resume.md").write_text(
        UNICODE_RESUME, encoding="utf-8")
    (tmp_path / "profile" / "answers.yaml").write_text(
        'contact:\n  full_name: "Chris Levequé"\n  city: "Québec, QC"\n',
        encoding="utf-8",
    )
    return tmp_path


def test_load_config_reads_unicode(tmp_path):
    cfg = load_config(make_project(tmp_path))
    assert cfg.searches[0].query == "café manager — remote"


def test_master_resume_reads_unicode(tmp_path):
    cfg = AppConfig()
    cfg.root = make_project(tmp_path)
    assert "Levequé" in _master_resume(cfg)


def test_answers_reads_unicode(tmp_path):
    cfg = AppConfig()
    cfg.root = make_project(tmp_path)
    assert _answers(cfg)["contact"]["city"] == "Québec, QC"
