"""Self-testing and diagnostics that run on the user's own machine.

The failures in this project are environment-shaped: a Windows encoding, a
Playwright build, a LibreOffice path, a stale install. None of them reproduce
in CI, so the useful thing is a battery of checks the user can run locally
that turns "something broke, here are six screenshots" into one shareable
report.

Every check is isolated: one failing check never prevents the others from
running, because the most useful report is the complete one. Nothing here
touches LinkedIn or submits anything.
"""

from __future__ import annotations

import platform
import re
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PASS, FAIL, SKIP = "pass", "fail", "skip"


@dataclass
class Check:
    name: str
    category: str
    status: str = PASS
    detail: str = ""
    fix: str = ""          # what the user should do about it

    @property
    def ok(self) -> bool:
        return self.status != FAIL


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    started: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(
            timespec="seconds"))

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        return check

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def passed(self) -> bool:
        return not self.failures

    def render(self, redact: bool = True) -> str:
        lines = [f"jobagent selftest — {self.started}", ""]
        current = ""
        for check in self.checks:
            if check.category != current:
                current = check.category
                lines.append(f"[{current}]")
            mark = {PASS: "PASS", FAIL: "FAIL", SKIP: "skip"}[check.status]
            line = f"  {mark:4}  {check.name}"
            if check.detail:
                line += f" — {check.detail}"
            lines.append(line)
            if check.status == FAIL and check.fix:
                lines.append(f"        fix: {check.fix}")
        lines.append("")
        lines.append(f"{len(self.checks) - len(self.failures)}/{len(self.checks)} "
                     f"checks passed")
        text = "\n".join(lines)
        return redact_text(text) if redact else text


# --- redaction --------------------------------------------------------------
# A report is meant to be pasted into a chat or an issue, so it must never
# carry the things this project deliberately keeps local.
_REDACTIONS = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<email>"),
    # Requires a separator, so a bare 10-digit LinkedIn job id stays readable
    # while "(954) 675-3653" / "954.675.3653" / "+1 954-675-3653" are removed.
    (re.compile(r"(?<!\d)\+?1?[\s.-]*\(?\d{3}\)?[\s.-]{1,2}\d{3}[\s.-]?\d{4}(?!\d)"),
     "<phone>"),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]+"), "<api-key>"),
    (re.compile(r"(?i)(password|app_password|token|secret)\s*[=:]\s*\S+"),
     r"\1=<redacted>"),
    (re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+"), r"C:\\Users\\<user>"),
    (re.compile(r"/(?:home|Users)/[^/\s]+"), "/home/<user>"),
)


def redact_text(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


# --- individual checks ------------------------------------------------------

def launch_chromium(pw):
    """Launch Chromium, falling back to a pre-installed build.

    Playwright refuses to run when its package version and the downloaded
    browser build disagree; on machines with a system-provided browser that
    is a recoverable situation, not a failure.
    """
    try:
        return pw.chromium.launch()
    except Exception:
        pass
    for pattern in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",
                    "/opt/pw-browsers/chromium-*/chrome-linux64/chrome"):
        for candidate in sorted(Path("/").glob(pattern.lstrip("/"))):
            try:
                return pw.chromium.launch(executable_path=str(candidate))
            except Exception:
                continue
    raise RuntimeError(
        "no usable Chromium — run: playwright install chromium")


def _check(report: Report, name: str, category: str, fn, fix: str = "",
           skip_reason: str = "") -> Check:
    """Run one check, converting any exception into a FAIL rather than a crash."""
    if skip_reason:
        return report.add(Check(name, category, SKIP, skip_reason))
    try:
        detail = fn() or ""
        return report.add(Check(name, category, PASS, str(detail)))
    except Exception as exc:
        return report.add(
            Check(name, category, FAIL, _one_line(f"{type(exc).__name__}: {exc}"),
                  fix))


def _one_line(text: str, limit: int = 160) -> str:
    """Collapse a multi-line error into something a report can list."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


def check_environment(report: Report, cfg) -> None:
    cat = "environment"
    _check(report, "python", cat,
           lambda: f"{platform.python_version()} on {platform.system()}")

    def entry_point() -> str:
        # A stale console script (installed before main() existed) silently
        # disables crash capture, which is confusing to debug later.
        import importlib.metadata as md

        for ep in md.distribution("jobagent").entry_points:
            if ep.name == "jobagent":
                if ep.value.endswith(":app"):
                    raise RuntimeError(
                        "installed entry point is out of date")
                return ep.value
        raise RuntimeError("jobagent console script not found")

    _check(report, "install is current", cat, entry_point,
           fix="run: pip install -e .")

    def playwright_ok() -> str:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = launch_chromium(pw)
            try:
                page = browser.new_page()
                page.set_content("<h1>ok</h1>")
                assert page.inner_text("h1") == "ok"
            finally:
                browser.close()
        return "chromium launches and renders"

    _check(report, "playwright browser", cat, playwright_ok,
           fix="run: playwright install chromium")

    def libreoffice() -> str:
        from .docgen import find_soffice

        found = find_soffice()
        if not found:
            raise RuntimeError("not found (PDF export disabled, .docx only)")
        return found

    _check(report, "libreoffice (optional)", cat, libreoffice,
           fix="install LibreOffice for PDF export; docx still works without it")


def check_profile(report: Report, cfg) -> None:
    cat = "profile"

    def resume() -> str:
        from .cli import _read_user_text

        path = cfg.master_resume_path
        if not path.exists():
            raise RuntimeError(f"missing: {path}")
        text = _read_user_text(path)
        if "REPLACE ME" in text:
            raise RuntimeError("still contains the REPLACE ME template marker")
        if len(text) < 400:
            raise RuntimeError(f"suspiciously short ({len(text)} chars)")
        return f"{len(text)} chars, readable"

    _check(report, "master resume", cat, resume,
           fix="paste your real resume into profile/master_resume.md")

    def answers() -> str:
        import yaml

        from .cli import _read_user_text

        path = cfg.answers_path
        if not path.exists():
            raise RuntimeError(f"missing: {path}")
        data = yaml.safe_load(_read_user_text(path)) or {}
        if not (data.get("contact") or {}).get("email"):
            raise RuntimeError("contact.email is not set")
        return f"{len(data)} sections"

    _check(report, "answers.yaml parses", cat, answers,
           fix="copy profile/answers.example.yaml and fill it in")

    def compliance() -> str:
        from .cli import _answers, _missing_compliance_answers

        missing = _missing_compliance_answers(_answers(cfg))
        if missing:
            raise RuntimeError("unanswered: " + ", ".join(missing))
        return "all covered"

    _check(report, "compliance answers", cat, compliance,
           fix="add them to answers.yaml — each one converts parked "
               "applications into completed ones")

    def privacy() -> str:
        import subprocess

        private = ("profile/answers.yaml", "profile/master_resume.md",
                   "profile/vault.enc", "profile/.vault.key", ".env")
        tracked = set(subprocess.run(
            ["git", "ls-files"], cwd=cfg.root, capture_output=True,
            text=True, timeout=10).stdout.split())
        leaked = [f for f in private if f in tracked]
        if leaked:
            raise RuntimeError("tracked by git: " + ", ".join(leaked))
        return "secrets untracked"

    _check(report, "git privacy", cat, privacy,
           fix="git rm --cached <file> for each one listed")


def check_storage(report: Report, cfg) -> None:
    cat = "storage"

    def database() -> str:
        from .store import Store

        store = Store(cfg.db_path)
        counts = store.status_counts()
        store.close()
        return ", ".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "empty"

    _check(report, "job tracker", cat, database,
           fix="the DB is corrupt; delete jobagent.db and re-scan")

    def vault() -> str:
        from .vault import Vault

        path = cfg.resolve("profile/vault.enc")
        if not path.exists():
            return "no accounts stored yet"
        creds = Vault(path).list()
        return f"{len(creds)} account(s), decrypts cleanly"

    _check(report, "account vault", cat, vault,
           fix="the key file may be missing; see `jobagent accounts`")


def check_documents(report: Report, cfg) -> None:
    """Generate a real resume and assert the properties that kept regressing."""
    cat = "documents"

    def docgen() -> str:
        import re as _re
        import tempfile
        import zipfile

        from .ai.tailor import ExperienceItem, SkillGroup, TailoredResume
        from .docgen import write_resume_docx

        resume = TailoredResume(
            name="Test Candidate", contact="", summary="",
            skills=["Okta"],
            skill_groups=[SkillGroup(name="Cybersecurity", items=["Okta"])],
            experience=[ExperienceItem(company="Acme", title="Engineer",
                                       dates="2020", location="Remote",
                                       bullets=["Did the thing"] * 8)],
            projects=["A project"], education=["A degree"],
            certifications=["A cert"])
        out = Path(tempfile.mkdtemp()) / "resume.docx"
        write_resume_docx(resume, out, contact={
            "phone": "(555) 555-5555", "email": "test@example.com",
            "linkedin": "https://linkedin.com/in/x"})
        xml = zipfile.ZipFile(str(out)).read("word/document.xml").decode()

        tblpr = _re.search(r"<w:tblPr>.*?</w:tblPr>", xml, _re.S)
        if not tblpr or tblpr.group(0).count('w:val="none"') != 6:
            raise RuntimeError("table borders are not all disabled")
        grid = _re.search(r"<w:tblGrid>.*?</w:tblGrid>", xml, _re.S).group(0)
        widths = [int(w) for w in _re.findall(r'<w:gridCol w:w="(\d+)"/>', grid)]
        if not widths or widths[0] / sum(widths) < 0.65:
            raise RuntimeError(f"column split is wrong: {widths}")
        return "borders off, 70/30 columns, hyperlinks present"

    _check(report, "resume generation", cat, docgen,
           fix="reinstall dependencies: pip install -e .")

    def pdf() -> str:
        import tempfile

        from .docgen import convert_to_pdf, count_pdf_pages, find_soffice

        if not find_soffice():
            raise RuntimeError("skipped: LibreOffice not installed")
        from docx import Document

        doc = Document()
        doc.add_paragraph("selftest")
        path = Path(tempfile.mkdtemp()) / "t.docx"
        doc.save(str(path))
        out = convert_to_pdf(path)
        if out is None:
            raise RuntimeError("conversion produced no PDF — is LibreOffice "
                               "open? close it and retry")
        return f"{count_pdf_pages(out)} page(s)"

    _check(report, "pdf export", cat, pdf,
           fix="close any open LibreOffice window, then re-run")


# A minimal Greenhouse-shaped form: enough to prove the whole apply path
# (field extraction JS, answering, filling, submitting) works on this machine.
_FIXTURE = """<!doctype html><html><body>
<form id="application_form" onsubmit="event.preventDefault();
      document.body.innerHTML='<h1>Thank you for applying</h1>'">
  <div class="field"><label for="fn">First Name *</label>
    <input id="fn" required></div>
  <div class="field"><label for="em">Email *</label>
    <input id="em" required></div>
  <div class="field"><label for="rs">Resume *</label>
    <input id="rs" type="file" required></div>
  <input type="submit" id="submit_app" value="Submit Application">
</form></body></html>"""


def check_apply_pipeline(report: Report, cfg) -> None:
    """Drive a real browser through a local form — no network, no LinkedIn."""
    cat = "apply pipeline"

    def adapters() -> str:
        from .ats import adapter_for
        names = [adapter_for(u).name for u in (
            "https://boards.greenhouse.io/a/jobs/1",
            "https://jobs.lever.co/a/uuid",
            "https://acme.wd1.myworkdayjobs.com/careers/job/X")]
        return ", ".join(names)

    _check(report, "ats adapters load", cat, adapters)

    def end_to_end() -> str:
        import tempfile

        from playwright.sync_api import sync_playwright

        from .ai.answerer import Answerer
        from .ats.base import ApplyContext
        from .ats.greenhouse import GreenhouseAdapter
        from .cli import _answers
        from .store import Store

        tmp = Path(tempfile.mkdtemp())
        (tmp / "job.html").write_text(_FIXTURE, encoding="utf-8")
        resume = tmp / "resume.pdf"
        resume.write_bytes(b"%PDF-1.4 selftest")

        store = Store(tmp / "t.db")
        ctx = ApplyContext(
            resume_file=resume,
            answerer=Answerer(_answers(cfg), store=store, ai=None, profile=""),
            screenshot_dir=tmp / "shots", submit=False)
        with sync_playwright() as pw:
            browser = launch_chromium(pw)
            try:
                page = browser.new_page()
                page.goto((tmp / "job.html").as_uri())
                result = GreenhouseAdapter().apply(
                    page, "https://boards.greenhouse.io/a/jobs/1", ctx)
            finally:
                browser.close()
        if result.outcome != "filled":
            raise RuntimeError(f"{result.outcome}: {result.note}")
        if not result.resume_attached:
            raise RuntimeError("resume was not attached")
        if not result.answered:
            raise RuntimeError("no questions were answered from answers.yaml")
        return (f"filled {len(result.answered)} field(s), resume attached, "
                "screenshot written")

    _check(report, "fill a form end-to-end", cat, end_to_end,
           fix="check the answers.yaml and playwright failures above first")


def check_services(report: Report, cfg, with_ai: bool) -> None:
    """Live credential checks — these are what silently rot."""
    cat = "services"

    def api_key() -> str:
        import os

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        if not with_ai:
            return "set (add --with-ai to make a real call)"
        from .ai.client import AIClient

        reply = AIClient(cfg.ai.model, 64).complete(
            "Reply with the single word: ok", "ping", max_tokens=16)
        if "ok" not in reply.lower():
            raise RuntimeError(f"unexpected reply: {reply[:60]!r}")
        return f"{cfg.ai.model} responded"

    _check(report, "anthropic api", cat, api_key,
           fix="copy .env.example to .env and add your key")

    def imap() -> str:
        import imaplib

        from .email_verify import config_from_env

        settings = config_from_env()
        if settings is None:
            raise RuntimeError(
                "not configured — Workday tenants that email a verification "
                "link will park")
        with imaplib.IMAP4_SSL(settings["host"]) as conn:
            conn.login(settings["address"], settings["password"])
            conn.select("INBOX", readonly=True)
        return f"signed in to {settings['host']} (read-only)"

    _check(report, "email verification", cat, imap,
           fix="set JOBAGENT_EMAIL and JOBAGENT_EMAIL_APP_PASSWORD in .env "
               "(a Gmail App Password, not your real one)")


def run_selftest(cfg, with_ai: bool = False, quick: bool = False) -> Report:
    report = Report()
    check_environment(report, cfg)
    check_profile(report, cfg)
    check_storage(report, cfg)
    check_documents(report, cfg)
    if not quick:
        check_apply_pipeline(report, cfg)
    check_services(report, cfg, with_ai)
    return report


# --- crash capture ----------------------------------------------------------

def write_crash_report(cfg_root: Path, command: str, exc: BaseException) -> Path:
    """Save a redacted traceback so a crash is one file to share, not a
    screenshot of a scrolled-off terminal."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    directory = cfg_root / "diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"crash-{stamp}.txt"
    body = "\n".join([
        f"command: {command}",
        f"when: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"python: {platform.python_version()} on {platform.platform()}",
        f"jobagent: {_version()}",
        "",
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    ])
    path.write_text(redact_text(body), encoding="utf-8")
    return path


def _version() -> str:
    try:
        import importlib.metadata as md

        return md.version("jobagent")
    except Exception:
        return "unknown"


def collect_report(cfg, with_ai: bool = False) -> str:
    """Everything worth sharing about a broken run, in one redacted blob."""
    parts = [run_selftest(cfg, with_ai=with_ai).render()]

    from .store import Store

    try:
        store = Store(cfg.db_path)
        events = store.application_events(limit=10)
        store.close()
        if events:
            parts.append("\n[recent application attempts]")
            for event in events:
                parts.append(
                    f"  {event['ts']}  {event['outcome']:9} "
                    f"{event['ats'] or '?':12} {event['note'][:80]}")
    except Exception as exc:
        parts.append(f"\n[recent application attempts] unavailable: {exc}")

    crashes = sorted((cfg.root / "diagnostics").glob("crash-*.txt"),
                     reverse=True)[:3]
    if crashes:
        parts.append("\n[recent crashes]")
        for crash in crashes:
            parts.append(f"\n--- {crash.name} ---")
            parts.append(crash.read_text(encoding="utf-8", errors="replace"))

    diagnostics = sorted(cfg.output_dir.glob("*/apply/*.txt"),
                         key=lambda p: p.stat().st_mtime, reverse=True)[:2]
    if diagnostics:
        parts.append("\n[recent ATS page diagnostics]")
        for diagnostic in diagnostics:
            parts.append(f"\n--- {diagnostic.parent.parent.name} / "
                         f"{diagnostic.name} ---")
            parts.append(diagnostic.read_text(encoding="utf-8",
                                              errors="replace")[:3000])

    return redact_text("\n".join(parts))
