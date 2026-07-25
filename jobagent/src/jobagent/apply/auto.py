"""Autonomous external applying: resolve the ATS URL, drive its form, report.

Two safety rails are structural rather than advisory:
  * nothing is submitted unless `submit=True` is passed explicitly, and
  * an application with an unanswered *required* question is never submitted,
    no matter what mode it runs in (enforced in BaseATSAdapter.apply).

Every attempt is logged to the tracker with the answers it used, so any
application can be reviewed — or withdrawn — after the fact.
"""

from __future__ import annotations

from pathlib import Path

from ..ai.answerer import Answerer
from ..ats import adapter_for, detect_ats
from ..ats.base import BLOCKED, FAILED, SUBMITTED, ApplyContext, ApplyReport

# Buttons on a LinkedIn/Indeed posting that lead to the employer's own ATS.
EXTERNAL_APPLY_SELECTORS = (
    "button:has-text('Apply')",
    "a:has-text('Apply now')",
    "a:has-text('Apply on company')",
    ".jobs-apply-button",
    "#indeedApplyButton",
    "a[href*='/applystart']",
)


def resolve_apply_url(session, job, console=None) -> str:
    """Find the employer-side apply URL for a posting.

    LinkedIn/Indeed postings link out to the real ATS; the tracker only holds
    the aggregator URL, so click through once and remember what we land on.
    """
    if job.apply_url:
        return job.apply_url
    if detect_ats(job.url):
        return job.url  # the tracked URL already points at an ATS

    page = session.page
    try:
        page.goto(job.url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        return ""
    page.wait_for_timeout(1500)

    for selector in EXTERNAL_APPLY_SELECTORS:
        button = page.locator(selector).first
        try:
            if not button.count() or not button.is_visible():
                continue
            with page.context.expect_page(timeout=15000) as popup_info:
                button.click()
            popup = popup_info.value
            popup.wait_for_load_state("domcontentloaded", timeout=30000)
            url = popup.url
            popup.close()
            if url and detect_ats(url):
                return url
            if url and not url.startswith(("https://www.linkedin.com",
                                           "https://www.indeed.com")):
                return url  # offsite, just not an ATS we know
        except Exception:
            continue
    # Some postings navigate in place instead of opening a tab.
    if detect_ats(page.url):
        return page.url
    return ""


def apply_to_job(session, job, cfg, store, ai, master_resume: str,
                 answers: dict, submit: bool, console) -> ApplyReport:
    """Resolve, fill, and (optionally) submit one external application."""
    apply_url = resolve_apply_url(session, job, console)
    if not apply_url:
        report = ApplyReport(url=job.url, outcome=BLOCKED,
                             note="could not find an external apply link")
        return report
    if apply_url != job.apply_url:
        store.update(job.url, apply_url=apply_url)

    ats = detect_ats(apply_url)
    adapter = adapter_for(apply_url)
    if adapter is None:
        return ApplyReport(
            url=apply_url, ats=ats, outcome=BLOCKED,
            note=(f"{ats} is not automated yet — apply by hand" if ats
                  else "unrecognized application system — apply by hand"))

    resume_file = Path(job.resume_path) if job.resume_path else None
    if resume_file is not None and not resume_file.exists():
        resume_file = None
    # Prefer the PDF: some ATS parsers reject .docx.
    if resume_file is not None and resume_file.suffix.lower() == ".docx":
        pdf = resume_file.with_suffix(".pdf")
        if pdf.exists():
            resume_file = pdf
    cover_file = Path(job.cover_letter_path) if job.cover_letter_path else None
    if cover_file is not None and not cover_file.exists():
        cover_file = None

    answerer = Answerer(answers, store=store, ai=ai, profile=master_resume, job=job)
    shots = (resume_file.parent / "apply") if resume_file else (cfg.output_dir / "apply")
    ctx = ApplyContext(resume_file=resume_file, cover_letter_file=cover_file,
                       answerer=answerer, screenshot_dir=shots, submit=submit,
                       pause=session.pause, console=console)

    page = session.page
    try:
        page.goto(apply_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        report = adapter.apply(page, apply_url, ctx)
    except Exception as exc:
        report = ApplyReport(url=apply_url, ats=ats, outcome=FAILED,
                             note=f"{type(exc).__name__}: {exc}")

    answerer.remember()
    store.log_application(
        job.url, report.ats, report.outcome, report.note,
        answers=report.answered,
        parked=[f"{p.field.question} :: {p.reason}" for p in report.parked],
    )
    return report


def run(session, jobs, cfg, store, ai, master_resume: str, answers: dict,
        submit: bool, console) -> dict[str, int]:
    """Apply to each job in turn. Returns a count per outcome."""
    counts: dict[str, int] = {}
    cap = cfg.limits.max_applications_per_day
    applied_today = store.count_applied_today()

    for job in jobs:
        if submit and applied_today >= cap:
            console.print(f"[yellow]Daily cap reached ({cap}) — stopping. Raise "
                          "limits.max_applications_per_day to do more.[/yellow]")
            break
        console.print(f"\n[bold]{job.title}[/bold] at {job.company}")
        report = apply_to_job(session, job, cfg, store, ai, master_resume,
                              answers, submit, console)
        counts[report.outcome] = counts.get(report.outcome, 0) + 1

        colour = {"submitted": "green", "filled": "cyan"}.get(report.outcome, "yellow")
        console.print(f"  [{colour}]{report.summary()}[/{colour}]")
        for parked in report.parked[:5]:
            console.print(f"    [dim]parked:[/dim] {parked.field.question[:70]} "
                          f"[dim]({parked.reason})[/dim]")
        if report.screenshots:
            shot = next((s for s in report.screenshots if s), None)
            if shot:
                console.print(f"    [dim]screenshot:[/dim] {shot}")

        if report.outcome == SUBMITTED:
            store.update(job.url, status="applied")
            applied_today += 1
        elif report.outcome == BLOCKED:
            store.update(job.url, status="blocked")
        elif report.outcome == "filled":
            store.update(job.url, status="filled")

        session.job_pause()

    return counts
