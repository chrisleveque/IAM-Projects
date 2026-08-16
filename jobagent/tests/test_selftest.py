"""The self-test has to fail when things are broken, not just pass when
they're fine — a green check that can't go red is worse than no check.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

from jobagent.selftest import (FAIL, PASS, Report, check_documents,
                               check_profile, check_storage, collect_report,
                               redact_text, run_selftest, write_crash_report)


def make_cfg(tmp_path, resume_text="x" * 500, answers=None):
    """A config pointing at a throwaway project tree."""
    (tmp_path / "profile").mkdir(exist_ok=True)
    (tmp_path / "profile" / "master_resume.md").write_text(
        resume_text, encoding="utf-8")
    (tmp_path / "profile" / "answers.yaml").write_text(
        yaml.safe_dump(answers if answers is not None else {
            "contact": {"email": "c@example.com", "full_name": "C L"}}),
        encoding="utf-8")
    return SimpleNamespace(
        root=tmp_path,
        master_resume_path=tmp_path / "profile" / "master_resume.md",
        answers_path=tmp_path / "profile" / "answers.yaml",
        db_path=tmp_path / "t.db",
        output_dir=tmp_path / "output",
        ai=SimpleNamespace(model="claude-sonnet-5", max_tokens=1024),
        resolve=lambda rel: tmp_path / rel,
    )


def status_of(report: Report, name: str) -> str:
    return next(c.status for c in report.checks if c.name == name)


# --- checks must detect real breakage --------------------------------------

def test_template_resume_is_flagged(tmp_path):
    cfg = make_cfg(tmp_path, resume_text="REPLACE ME: paste your resume")
    report = Report()
    check_profile(report, cfg)
    assert status_of(report, "master resume") == FAIL


def test_truncated_resume_is_flagged(tmp_path):
    cfg = make_cfg(tmp_path, resume_text="# Chris")   # far too short
    report = Report()
    check_profile(report, cfg)
    assert status_of(report, "master resume") == FAIL


def test_utf16_resume_still_passes(tmp_path):
    """The exact Windows failure that crashed doctor must now be a pass."""
    cfg = make_cfg(tmp_path)
    cfg.master_resume_path.write_bytes(("# Chris\n" + "x" * 500).encode("utf-16"))
    report = Report()
    check_profile(report, cfg)
    assert status_of(report, "master resume") == PASS


def test_unparseable_answers_is_flagged(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.answers_path.write_text("contact: [unclosed", encoding="utf-8")
    report = Report()
    check_profile(report, cfg)
    assert status_of(report, "answers.yaml parses") == FAIL


def test_answers_without_email_is_flagged(tmp_path):
    cfg = make_cfg(tmp_path, answers={"contact": {"full_name": "C"}})
    report = Report()
    check_profile(report, cfg)
    assert status_of(report, "answers.yaml parses") == FAIL


def test_missing_compliance_answers_are_flagged(tmp_path):
    cfg = make_cfg(tmp_path)      # no work authorization etc.
    report = Report()
    check_profile(report, cfg)
    assert status_of(report, "compliance answers") == FAIL


def test_healthy_profile_passes(tmp_path):
    cfg = make_cfg(tmp_path, answers={
        "contact": {"email": "c@example.com", "full_name": "C L"},
        "work_authorization": {"authorized_to_work_us": True,
                               "require_sponsorship": False},
        "preferences": {"desired_salary": "120000"},
        "custom_answers": [
            {"match": ["felony"], "answer": "No"},
            {"match": ["security clearance"], "answer": "No"},
            {"match": ["drug screen"], "answer": "Yes"},
        ]})
    report = Report()
    check_profile(report, cfg)
    assert status_of(report, "answers.yaml parses") == PASS
    assert status_of(report, "compliance answers") == PASS


def test_document_generation_check_runs(tmp_path):
    """Guards the properties that regressed repeatedly: borders and columns."""
    report = Report()
    check_documents(report, make_cfg(tmp_path))
    assert status_of(report, "resume generation") == PASS


def test_storage_check_reports_counts(tmp_path):
    from jobagent.store import Job, Store

    cfg = make_cfg(tmp_path)
    store = Store(cfg.db_path)
    store.upsert_job(Job(url="u", source="linkedin"))
    store.close()
    report = Report()
    check_storage(report, cfg)
    assert status_of(report, "job tracker") == PASS
    assert "discovered:1" in next(
        c.detail for c in report.checks if c.name == "job tracker")


def test_corrupt_database_is_flagged(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.db_path.write_bytes(b"this is not a sqlite file at all")
    report = Report()
    check_storage(report, cfg)
    assert status_of(report, "job tracker") == FAIL


# --- redaction: the report gets pasted in public ---------------------------

def test_redaction_strips_personal_and_secret_values():
    raw = ("contact chrisleveque25@gmail.com or (954) 675-3653\n"
           "ANTHROPIC_API_KEY=sk-ant-abc123XYZ_secret\n"
           "JOBAGENT_EMAIL_APP_PASSWORD: abcdefghijklmnop\n"
           r"C:\Users\chril\Documents\IAM-Projects" "\n"
           "/home/chris/projects")
    clean = redact_text(raw)

    assert "chrisleveque25@gmail.com" not in clean
    assert "954" not in clean
    assert "sk-ant-abc123XYZ_secret" not in clean
    assert "abcdefghijklmnop" not in clean
    assert "chril" not in clean and "/home/chris" not in clean
    # still readable enough to be useful
    assert "<email>" in clean and "<api-key>" in clean


def test_rendered_report_is_redacted(tmp_path):
    cfg = make_cfg(tmp_path, answers={
        "contact": {"email": "real.person@gmail.com", "full_name": "C"}})
    report = Report()
    check_profile(report, cfg)
    assert "real.person@gmail.com" not in report.render()


# --- crash capture ---------------------------------------------------------

def test_crash_report_is_written_and_redacted(tmp_path):
    try:
        raise ValueError("failed for user chris@example.com")
    except ValueError as exc:
        path = write_crash_report(tmp_path, "jobagent auto-apply --submit", exc)

    text = path.read_text(encoding="utf-8")
    assert path.parent.name == "diagnostics"
    assert "auto-apply --submit" in text
    assert "ValueError" in text
    assert "Traceback" in text
    assert "chris@example.com" not in text      # redacted


def test_collect_report_survives_a_missing_database(tmp_path):
    """The bundle must still be produced when part of the project is broken —
    that is exactly when someone runs it."""
    cfg = make_cfg(tmp_path)
    cfg.db_path.write_bytes(b"corrupt")
    text = collect_report(cfg)
    assert "selftest" in text


def test_one_failing_check_does_not_stop_the_rest(tmp_path):
    """A crash in one check must not cost the whole report."""
    cfg = make_cfg(tmp_path, resume_text="REPLACE ME")
    report = run_selftest(cfg, with_ai=False, quick=True)
    assert any(c.status == FAIL for c in report.checks)
    assert len(report.checks) >= 8          # everything still ran
    assert {c.category for c in report.checks} >= {
        "environment", "profile", "storage", "documents", "services"}
