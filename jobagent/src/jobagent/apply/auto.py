"""Autonomous external applying: resolve the ATS URL, drive its form, report.

Two safety rails are structural rather than advisory:
  * nothing is submitted unless `submit=True` is passed explicitly, and
  * an application with an unanswered *required* question is never submitted,
    no matter what mode it runs in (enforced in BaseATSAdapter.apply).

Every attempt is logged to the tracker with the answers it used, so any
application can be reviewed — or withdrawn — after the fact.
"""

from __future__ import annotations

import json
import re
from html import unescape as html_unescape
from pathlib import Path
from urllib.parse import urlsplit

from ..ai.answerer import Answerer
from ..ats import adapter_for, detect_ats
from ..ats.base import BLOCKED, FAILED, SUBMITTED, ApplyContext, ApplyReport

# Buttons on a LinkedIn/Indeed posting that lead to the employer's own ATS.
EXTERNAL_APPLY_SELECTORS = (
    ".jobs-apply-button",
    "button:has-text('Apply')",
    "a:has-text('Apply now')",
    "a:has-text('Apply on company')",
    "#indeedApplyButton",
    "a[href*='/applystart']",
)

# LinkedIn interposes a modal ("You're applying on the company's website")
# between the Apply click and the new tab.
MODAL_SELECTORS = ("[role='dialog']", ".artdeco-modal")
MODAL_CONTINUE_SELECTORS = (
    "[role='dialog'] a[href^='http']",
    ".artdeco-modal a[href^='http']",
    "[role='dialog'] a:has-text('Continue')",
    "[role='dialog'] button:has-text('Continue')",
    "[role='dialog'] a:has-text('Apply')",
    "[role='dialog'] button:has-text('Apply')",
)

# LinkedIn ships the offsite URL in the page's embedded JSON. Reading it beats
# clicking: no modal, no popup, no timing.
_APPLY_URL_KEYS = ("companyApplyUrl", "applyUrl", "companyApplyURL")
_APPLY_URL_RE = re.compile(
    r'"(?:' + "|".join(_APPLY_URL_KEYS) + r')"\s*:\s*"([^"]{10,2000})"')

# Hosts that mean "still on the aggregator", not a real apply target.
_AGGREGATOR_HOSTS = ("linkedin.com", "indeed.com", "licdn.com")


def _decode(raw: str) -> str:
    """Undo JSON (\\u002F) and HTML (&amp;) escaping from embedded page data."""
    try:
        value = json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        value = raw
    return html_unescape(value).strip()


def is_offsite(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return bool(host) and not any(host == h or host.endswith("." + h)
                                  for h in _AGGREGATOR_HOSTS)


def extract_company_apply_url(page_html: str) -> str:
    """Pull the employer's apply URL out of a LinkedIn posting's page source."""
    for match in _APPLY_URL_RE.finditer(page_html or ""):
        url = _decode(match.group(1))
        if url.startswith("http") and is_offsite(url):
            return url
    return ""


def _url_from_dom(page) -> str:
    """Any link on the posting that already points at a known ATS."""
    try:
        hrefs = page.eval_on_selector_all(
            "a[href^='http']", "els => els.map(e => e.href)") or []
    except Exception:
        return ""
    return next((h for h in hrefs if detect_ats(h)), "")


def _follow_popup(page, action, timeout: int = 8000) -> str:
    """Run `action`, and return the URL of the tab it opens (if any)."""
    try:
        with page.context.expect_page(timeout=timeout) as popup_info:
            action()
        popup = popup_info.value
    except Exception:
        return ""
    try:
        popup.wait_for_load_state("domcontentloaded", timeout=30000)
        return popup.url
    except Exception:
        return popup.url or ""
    finally:
        try:
            popup.close()
        except Exception:
            pass


def _url_via_click(page) -> str:
    """Last resort: click Apply and follow the modal / popup / redirect."""
    for selector in EXTERNAL_APPLY_SELECTORS:
        button = page.locator(selector).first
        try:
            if not button.count() or not button.is_visible():
                continue
        except Exception:
            continue

        url = _follow_popup(page, button.click)
        if url and is_offsite(url):
            return url

        # No tab opened: LinkedIn most likely showed its "applying on the
        # company website" modal. Prefer reading the link over clicking it.
        page.wait_for_timeout(1200)
        if any(_count(page, m) for m in MODAL_SELECTORS):
            for link in MODAL_CONTINUE_SELECTORS:
                target = page.locator(link).first
                if not _count(page, link):
                    continue
                try:
                    href = target.get_attribute("href") or ""
                except Exception:
                    href = ""
                if href.startswith("http") and is_offsite(href):
                    return href
                url = _follow_popup(page, target.click, timeout=10000)
                if url and is_offsite(url):
                    return url

        # Some postings navigate the current tab instead of opening one.
        if is_offsite(page.url):
            return page.url
    return ""


def _count(page, selector: str) -> int:
    try:
        return page.locator(selector).count()
    except Exception:
        return 0


def resolve_apply_url(session, job, console=None,
                      debug_dir: Path | None = None) -> str:
    """Find the employer-side apply URL for a posting.

    Tried in order of reliability: the URL embedded in the posting's own JSON,
    a known-ATS link in the DOM, then clicking Apply and following the modal
    or popup LinkedIn puts in the way.
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
    page.wait_for_timeout(2000)

    try:
        found = extract_company_apply_url(page.content())
    except Exception:
        found = ""
    if not found:
        found = _url_from_dom(page) or _url_via_click(page)
    if not found and debug_dir is not None:
        _dump_for_diagnosis(page, debug_dir, console)
    return found


_ANY_APPLY_KEY_RE = re.compile(r'"(\w*[aA]pply\w*(?:Url|URL|Link))"\s*:\s*"([^"]{5,2000})"')
_APPLY_ELEMENT_RE = re.compile(
    r"<(a|button)\b([^>]*(?:apply|Apply)[^>]*)>", re.I)
_HREF_RE = re.compile(r'href="([^"]+)"')
_CLASS_RE = re.compile(r'class="([^"]*)"')


def describe_apply_markup(page_html: str) -> str:
    """Summarize a posting's apply-related markup, without personal content.

    Emitted by `jobagent debug-apply` so an unresolvable posting can be
    diagnosed from a short paste instead of a whole rendered page.
    """
    html = page_html or ""
    lines = [f"page length: {len(html)} chars"]

    seen: set[tuple[str, str]] = set()
    for match in _ANY_APPLY_KEY_RE.finditer(html):
        key, raw = match.group(1), match.group(2)
        url = _decode(raw)
        host = urlsplit(url).hostname or "(relative)"
        mark = "OFFSITE" if is_offsite(url) else "internal"
        ats = detect_ats(url)
        entry = (key, host)
        if entry in seen:
            continue
        seen.add(entry)
        lines.append(f'  json key "{key}" -> {host}  [{mark}'
                     + (f", ats={ats}" if ats else "") + "]")
    if len(lines) == 1:
        lines.append("  no *ApplyUrl* keys found in the page JSON")

    elements = []
    for match in _APPLY_ELEMENT_RE.finditer(html):
        tag, attrs = match.group(1), match.group(2)
        href_match = _HREF_RE.search(attrs)
        class_match = _CLASS_RE.search(attrs)
        href = href_match.group(1) if href_match else ""
        host = (urlsplit(href).hostname or "") if href.startswith("http") else ""
        classes = " ".join((class_match.group(1) if class_match else "").split()[:4])
        entry = f"  <{tag}> class={classes!r}" + (f" -> {host}" if host else "")
        if entry not in elements:
            elements.append(entry)
    lines.append(f"apply-ish elements: {len(elements)}")
    lines.extend(elements[:12])

    for marker, label in (("artdeco-modal", "artdeco modal"),
                          ('role="dialog"', "role=dialog"),
                          ("jobs-apply-button", "jobs-apply-button")):
        if marker in html:
            lines.append(f"  contains {label}")

    resolved = extract_company_apply_url(html)
    lines.append(f"resolver would extract: {resolved or '(nothing)'}")
    return "\n".join(lines)


def _dump_for_diagnosis(page, debug_dir: Path, console=None) -> None:
    """Save the posting so an unresolvable apply link can be diagnosed."""
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "posting.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(debug_dir / "posting.png"), full_page=True)
        if console is not None:
            console.print("    [dim]saved posting HTML + screenshot to "
                          f"{debug_dir} for diagnosis[/dim]")
    except Exception:
        pass


def apply_to_job(session, job, cfg, store, ai, master_resume: str,
                 answers: dict, submit: bool, console) -> ApplyReport:
    """Resolve, fill, and (optionally) submit one external application."""
    job_dir = (Path(job.resume_path).parent if job.resume_path
               else cfg.output_dir / "apply")
    apply_url = resolve_apply_url(session, job, console,
                                  debug_dir=job_dir / "apply")
    if not apply_url:
        return ApplyReport(
            url=job.url, outcome=BLOCKED,
            note="could not find an external apply link on the posting")
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
