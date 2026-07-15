# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository overview

This repo contains two unrelated parts:

1. **IAM lab portfolio (repo root)** — `README.md` documents hands-on Microsoft Entra ID labs (tenant/user setup, dynamic groups & RBAC, joiner-mover-leaver lifecycle, access reviews). It is documentation only: the labs were performed in an Azure tenant, and the repo holds the write-ups, screenshots (hosted on GitHub user-attachments), and CSV exports (`exportUsers_*.csv`, `exportGroup_*.csv`). There is no code to build or run here — edits are Markdown edits.

2. **`jobagent/`** — a Python package: a semi-automated LinkedIn/Indeed job application copilot (scan → score → tailor → apply). All development commands below apply to this directory.

## Commands (run from `jobagent/`)

```bash
# One-time setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

# Tests — no browser or API key needed; AI and Playwright are mocked/avoided
pytest                            # all tests
pytest tests/test_store.py        # one file
pytest tests/test_formfill.py::test_match_answer -k "sponsor"  # one test / keyword

# Sanity check of environment and config
jobagent doctor
```

There is no linter or formatter configured. Python 3.10+ (`X | None` unions, dataclasses, pattern of `from __future__ import annotations` throughout).

## jobagent architecture

The CLI (`src/jobagent/cli.py`, Typer app, entry point `jobagent`) drives a pipeline whose state lives in a SQLite tracker:

```
scan ──► score ──► (queued via review) ──► tailor ──► apply
```

- **`store.py`** — single `jobs` table keyed by URL. Status lifecycle: `discovered → scored → (queued) → tailored → applied`, any status can move to `skipped` (the `STATUSES` tuple is enforced in `Store.update`). Each CLI stage selects jobs by status and advances them, so stages are re-runnable and resumable. `count_applied_today()` backs the daily application cap.
- **`config.py`** — Pydantic models loaded from `config.yaml` + `.env` (only `ANTHROPIC_API_KEY`). Project root is found via `JOBAGENT_HOME` or by walking up to the dir containing `config.yaml` + `profile/`; all paths in config resolve relative to that root.
- **`browser.py`** — one persistent, always-headed Chromium context (`browser_profile/` keeps logins across runs; `jobagent login` populates it interactively). Provides randomized human-pacing delays (`pause`/`job_pause`) driven by `limits` in config.
- **`scrapers/`** (`linkedin.py`, `indeed.py`) — discovery; write `discovered` jobs into the store.
- **`ai/`** — `client.py` is a thin Anthropic wrapper (`complete`/`complete_json` + `extract_json` for fence-tolerant JSON parsing; the SDK import is lazy so tests can run without the package/key). `scorer.py` scores jobs 0–100 against the master resume; `tailor.py` produces a structured tailored resume + cover letter.
- **`docgen.py`** — renders the tailored package to `.docx` via python-docx (PDF only if LibreOffice is installed) into `output/<company>-<title>/`.
- **`apply/`** — `linkedin_easy_apply.py` / `indeed_apply.py` walk the multi-step apply modals; shared `formfill.py` matches form questions against `profile/answers.yaml`, asks the AI to draft unknown answers (always confirmed by the user in the terminal, then persisted back to `answers.yaml`).

### Key conventions

- **The human clicks Submit.** Nothing in `apply/` ever submits an application; the tool pre-fills and stops. Preserve this invariant in any change.
- **Honesty guarantee**: the tailoring prompt must never invent facts not present in `profile/master_resume.md` — only select, reorder, and reword.
- **Selectors live in one `SELECTORS` block** at the top of each scraper/apply module. When LinkedIn/Indeed markup changes, that block is the only place to fix; keep new selectors there rather than inline.
- **Rate limits are safety rails**: delays and `max_applications_per_day` exist to reduce account-ban risk. Don't remove or default them lower.
- **Gitignored user data**: `.env`, `browser_profile/`, `output/`, and `jobagent.db` never get committed. `profile/master_resume.md` and `profile/answers.yaml` are committed as templates but contain the user's real data once filled in — don't paste their contents into commits or PRs.
