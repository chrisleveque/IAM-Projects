"""CLI test for 'cj variants': listing all color/size variants of a CJ
product so a multi-variant listing (e.g. Amazon color variations) can use
each color's own vid as its SKU, instead of only the default one."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from shopagent.cli import app

runner = CliRunner()


def _init_project(tmp_path: Path) -> Path:
    (tmp_path / "config.yaml").write_text("mode: dry_run\n")
    (tmp_path / "inbox").mkdir()
    return tmp_path


def test_cj_variants_lists_four_colors(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    result = runner.invoke(app, ["cj", "variants", "CJ-PET-001"])
    assert result.exit_code == 0, result.output
    for color in ("Green", "Blue", "Orange", "Cream"):
        assert color in result.output
    assert "automated fulfillment" in result.output


def test_cj_variants_unknown_pid_fails_cleanly(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    monkeypatch.setenv("SHOPAGENT_HOME", str(root))
    result = runner.invoke(app, ["cj", "variants", "NOPE-404"])
    assert result.exit_code != 0
    assert "no variants found" in result.output
