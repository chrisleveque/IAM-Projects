"""CLI tests for 'serve'.

The bug these exist to prevent: `serve` read SHOPAGENT_API_TOKEN from the
process environment *before* load_config() had a chance to read .env, so a
token sitting correctly in .env was invisible and the command refused to start.
It only worked when the token was exported as a real shell variable — which is
exactly how it got smoke-tested, and exactly why the bug survived.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from shopagent.cli import app

runner = CliRunner()

TOKEN = "env-file-token-0123456789abcdef"


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    (tmp_path / "config.yaml").write_text("mode: dry_run\n", encoding="utf-8")
    (tmp_path / "inbox").mkdir()
    monkeypatch.setenv("SHOPAGENT_HOME", str(tmp_path))
    # a token leaking in from the developer's own shell would mask the bug
    monkeypatch.delenv("SHOPAGENT_API_TOKEN", raising=False)
    return tmp_path


@pytest.fixture
def no_uvicorn_run(monkeypatch) -> list:
    """Capture uvicorn.run's arguments instead of blocking on a real server."""
    import uvicorn
    calls: list = []
    monkeypatch.setattr(uvicorn, "run",
                        lambda app, **kw: calls.append((app, kw)))
    return calls


def test_token_is_read_from_the_env_file(project, no_uvicorn_run):
    (project / ".env").write_text(f"SHOPAGENT_API_TOKEN={TOKEN}\n", encoding="utf-8")
    result = runner.invoke(app, ["serve", "--port", "9999"])
    assert result.exit_code == 0, result.output
    assert len(no_uvicorn_run) == 1
    _, kwargs = no_uvicorn_run[0]
    assert kwargs["port"] == 9999
    assert kwargs["host"] == "127.0.0.1"  # localhost by default; tunnel in front


def test_token_among_other_env_file_entries(project, no_uvicorn_run):
    (project / ".env").write_text(
        "# comment line\n"
        "ANTHROPIC_API_KEY=sk-ant-whatever\n"
        "SHOPIFY_STORE_DOMAIN=example.myshopify.com\n"
        f"SHOPAGENT_API_TOKEN={TOKEN}\n"
        "CJ_EMAIL=a@b.c\n", encoding="utf-8")
    assert runner.invoke(app, ["serve"]).exit_code == 0
    assert len(no_uvicorn_run) == 1


def test_a_later_duplicate_wins(project, no_uvicorn_run):
    """Clearing a token in an editor leaves an empty line behind; appending a
    fresh one below it is a valid fix, so make sure that actually works."""
    (project / ".env").write_text(
        "SHOPAGENT_API_TOKEN=\n"
        "CJ_EMAIL=a@b.c\n"
        f"SHOPAGENT_API_TOKEN={TOKEN}\n", encoding="utf-8")
    assert runner.invoke(app, ["serve"]).exit_code == 0
    assert len(no_uvicorn_run) == 1


def test_missing_token_refuses_to_start_with_a_useful_message(project):
    (project / ".env").write_text("CJ_EMAIL=a@b.c\n", encoding="utf-8")
    result = runner.invoke(app, ["serve"])
    assert result.exit_code != 0
    assert "SHOPAGENT_API_TOKEN is not set" in result.output
    # the message must name the file to edit and how to generate a value
    assert ".env" in result.output
    assert "token_urlsafe" in result.output


def test_empty_token_is_treated_as_missing(project):
    (project / ".env").write_text("SHOPAGENT_API_TOKEN=\n", encoding="utf-8")
    result = runner.invoke(app, ["serve"])
    assert result.exit_code != 0
    assert "SHOPAGENT_API_TOKEN is not set" in result.output


def test_no_env_file_at_all_still_fails_cleanly(project):
    result = runner.invoke(app, ["serve"])
    assert result.exit_code != 0
    assert "SHOPAGENT_API_TOKEN is not set" in result.output


def test_shell_environment_token_still_works(project, no_uvicorn_run, monkeypatch):
    """Exporting the token is a legitimate alternative to the .env file (e.g.
    running under a process manager)."""
    monkeypatch.setenv("SHOPAGENT_API_TOKEN", TOKEN)
    assert runner.invoke(app, ["serve"]).exit_code == 0
    assert len(no_uvicorn_run) == 1


def test_doctor_reports_the_api_token(project):
    (project / ".env").write_text(f"SHOPAGENT_API_TOKEN={TOKEN}\n", encoding="utf-8")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "SHOPAGENT_API_TOKEN" in result.output
    # never echo the secret itself
    assert TOKEN not in result.output
