"""Indeed job scraping via the logged-in browser.

All selectors live in SELECTORS — first place to look when scanning breaks.
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from rich.console import Console

from ..browser import BrowserSession
from ..config import SearchSpec
from ..store import Job, Store

SELECTORS = {
    "card": "div.job_seen_beacon",
    "card_title_link": "h2.jobTitle a, a.jcs-JobTitle",
    "detail_title": "h2[data-testid='jobsearch-JobInfoHeader-title'], "
                    ".jobsearch-JobInfoHeader-title",
    "detail_company": "[data-testid='inlineHeader-companyName'], "
                      "[data-testid='company-name'], .jobsearch-CompanyInfoContainer a",
    "detail_location": "[data-testid='inlineHeader-companyLocation'], "
                       "[data-testid='job-location'], [data-testid='text-location']",
    "description": "#jobDescriptionText",
    "easy_apply_marker": "[data-testid='indeedApply'], .indeedApply, "
                         "span:has-text('Easily apply')",
    "apply_button": "#indeedApplyButton, button:has-text('Apply now')",
}

SEARCH_URL = "https://www.indeed.com/jobs"


def job_url_from_jk(jk: str) -> str:
    return f"https://www.indeed.com/viewjob?jk={jk}"


def jk_from_url(url: str) -> str | None:
    """Extract the job key from any Indeed URL shape (viewjob?jk=, rc/clk?jk=...)."""
    m = re.search(r"\bjk=([A-Za-z0-9]+)", url)
    return m.group(1) if m else None


def fetch_job(session: BrowserSession, url: str, console: Console) -> Job | None:
    """Fetch one job by URL (e.g. pasted from the user's saved list)."""
    jk = jk_from_url(url)
    job_url = job_url_from_jk(jk) if jk else url
    page = session.page
    try:
        page.goto(job_url, wait_until="domcontentloaded")
        session.pause()
    except Exception as exc:
        console.print(f"[red]could not open {job_url}: {type(exc).__name__}[/red]")
        return None
    return Job(
        url=job_url,
        source="indeed",
        saved=True,
        title=_text(page, SELECTORS["detail_title"]),
        company=_text(page, SELECTORS["detail_company"]),
        location=_text(page, SELECTORS["detail_location"]),
        description=_text(page, SELECTORS["description"]),
        easy_apply=page.locator(SELECTORS["easy_apply_marker"]).count() > 0,
    )


def _text(scope, selector: str) -> str:
    try:
        loc = scope.locator(selector).first
        if loc.count() == 0:
            return ""
        return " ".join(loc.inner_text(timeout=4000).split())
    except Exception:
        return ""


def scan(session: BrowserSession, store: Store, spec: SearchSpec, console: Console) -> int:
    page = session.page
    url = f"{SEARCH_URL}?q={quote_plus(spec.query)}"
    if spec.location:
        url += f"&l={quote_plus(spec.location)}"
    if spec.easy_apply_only:
        url += "&iafilter=1"  # Indeed Apply only

    console.print(f"[bold]Indeed:[/bold] searching '{spec.query}' ({spec.location or 'any'})")
    page.goto(url)
    page.wait_for_load_state("domcontentloaded")
    session.pause()

    cards = page.locator(SELECTORS["card"])
    total = min(cards.count(), spec.max_results)
    if total == 0:
        console.print("[yellow]No result cards found — you may be facing a captcha "
                      "(solve it in the window and rerun), or selectors need updating "
                      "(see SELECTORS in scrapers/indeed.py).[/yellow]")
        return 0

    new_count = 0
    for i in range(total):
        try:
            card = cards.nth(i)
            card.scroll_into_view_if_needed()
            title_link = card.locator(SELECTORS["card_title_link"]).first
            jk = title_link.get_attribute("data-jk") or ""
            if not jk:
                href = title_link.get_attribute("href") or ""
                if "jk=" in href:
                    jk = href.split("jk=")[1].split("&")[0]
            if not jk:
                continue
            job_url = job_url_from_jk(jk)
            easy = card.locator(SELECTORS["easy_apply_marker"]).count() > 0 or \
                "easily apply" in card.inner_text().lower()
            title_link.click()
            session.pause()
            job = Job(
                url=job_url,
                source="indeed",
                title=_text(page, SELECTORS["detail_title"]) or _text(card, "h2.jobTitle"),
                company=_text(page, SELECTORS["detail_company"]),
                location=_text(page, SELECTORS["detail_location"]),
                description=_text(page, SELECTORS["description"]),
                easy_apply=easy,
            )
            if store.upsert_job(job):
                new_count += 1
                console.print(f"  [green]+[/green] {job.title or job_url} — {job.company}")
        except Exception as exc:
            console.print(f"  [yellow]card {i}: {type(exc).__name__}: {exc}[/yellow]")
    console.print(f"Indeed: {new_count} new job(s) of {total} seen.")
    return new_count
