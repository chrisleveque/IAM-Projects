"""LinkedIn job scraping (search results + saved jobs) via the logged-in browser.

LinkedIn changes its markup regularly. Every selector lives in SELECTORS below —
if scanning stops finding jobs, this block is the first (usually only) thing
that needs updating. Each entry is a comma-separated list of fallbacks tried
in order by Playwright.
"""

from __future__ import annotations

from urllib.parse import quote_plus, urlsplit

from rich.console import Console

from ..browser import BrowserSession
from ..config import SearchSpec
from ..store import Job, Store

SELECTORS = {
    "card": "li[data-occludable-job-id], ul.jobs-search__results-list > li",
    "card_link": "a.job-card-list__title--link, a.job-card-list__title, "
                 "a.job-card-container__link, a.base-card__full-link",
    "detail_title": ".job-details-jobs-unified-top-card__job-title, "
                    ".jobs-unified-top-card__job-title, h1",
    "detail_company": ".job-details-jobs-unified-top-card__company-name, "
                      ".jobs-unified-top-card__company-name, .topcard__org-name-link",
    "detail_location": ".job-details-jobs-unified-top-card__primary-description-container, "
                       ".jobs-unified-top-card__primary-description, .jobs-unified-top-card__bullet",
    "description": "#job-details, .jobs-description__content, .jobs-box__html-content, "
                   ".description__text",
    "easy_apply_button": "button.jobs-apply-button",
    "saved_job_link": "a[href*='/jobs/view/']",
}

SEARCH_URL = "https://www.linkedin.com/jobs/search/"
SAVED_JOBS_URL = "https://www.linkedin.com/my-items/saved-jobs/"


def canonical_job_url(href: str) -> str:
    """Normalize to https://www.linkedin.com/jobs/view/<id>/ without tracking params."""
    parts = urlsplit(href)
    path = parts.path.rstrip("/") + "/"
    return f"https://www.linkedin.com{path}" if not parts.netloc else \
        f"{parts.scheme or 'https'}://{parts.netloc}{path}"


def _text(page_or_scope, selector: str) -> str:
    try:
        loc = page_or_scope.locator(selector).first
        if loc.count() == 0:
            return ""
        return " ".join(loc.inner_text(timeout=4000).split())
    except Exception:
        return ""


def _read_detail_pane(page) -> dict:
    return {
        "title": _text(page, SELECTORS["detail_title"]),
        "company": _text(page, SELECTORS["detail_company"]),
        "location": _text(page, SELECTORS["detail_location"]),
        "description": _text(page, SELECTORS["description"]),
        "easy_apply": _detect_easy_apply(page),
    }


def _detect_easy_apply(page) -> bool:
    try:
        btn = page.locator(SELECTORS["easy_apply_button"]).first
        return btn.count() > 0 and "easy apply" in btn.inner_text(timeout=3000).lower()
    except Exception:
        return False


def scan(session: BrowserSession, store: Store, spec: SearchSpec, console: Console) -> int:
    """Run one search, click through result cards, store jobs. Returns # new."""
    page = session.page
    url = f"{SEARCH_URL}?keywords={quote_plus(spec.query)}"
    if spec.location:
        url += f"&location={quote_plus(spec.location)}"
    if spec.easy_apply_only:
        url += "&f_AL=true"

    console.print(f"[bold]LinkedIn:[/bold] searching '{spec.query}' ({spec.location or 'any'})")
    page.goto(url)
    page.wait_for_load_state("domcontentloaded")
    session.pause()

    if "/login" in page.url or "authwall" in page.url or "/checkpoint" in page.url:
        console.print("[red]Not logged in to LinkedIn — run `jobagent login` first.[/red]")
        return 0

    cards = page.locator(SELECTORS["card"])
    total = min(cards.count(), spec.max_results)
    if total == 0:
        console.print("[yellow]No result cards found — selectors may need updating "
                      "(see SELECTORS in scrapers/linkedin.py).[/yellow]")
        return 0

    new_count = 0
    for i in range(total):
        try:
            card = cards.nth(i)
            card.scroll_into_view_if_needed()
            link = card.locator(SELECTORS["card_link"]).first
            href = link.get_attribute("href") or ""
            if "/jobs/view/" not in href:
                continue
            job_url = canonical_job_url(href)
            card.click()
            session.pause()
            detail = _read_detail_pane(page)
            job = Job(url=job_url, source="linkedin", **detail)
            if store.upsert_job(job):
                new_count += 1
                console.print(f"  [green]+[/green] {job.title or job_url} — {job.company}")
        except Exception as exc:  # keep scanning; one bad card shouldn't stop the run
            console.print(f"  [yellow]card {i}: {type(exc).__name__}: {exc}[/yellow]")
    console.print(f"LinkedIn: {new_count} new job(s) of {total} seen.")
    return new_count


def scan_saved(session: BrowserSession, store: Store, console: Console, limit: int = 50) -> int:
    """Import jobs you saved on LinkedIn while browsing."""
    page = session.page
    console.print("[bold]LinkedIn:[/bold] importing saved jobs")
    page.goto(SAVED_JOBS_URL)
    page.wait_for_load_state("domcontentloaded")
    session.pause()

    hrefs: list[str] = []
    for a in page.locator(SELECTORS["saved_job_link"]).all():
        href = a.get_attribute("href") or ""
        if "/jobs/view/" in href:
            u = canonical_job_url(href)
            if u not in hrefs:
                hrefs.append(u)
    new_count = 0
    for job_url in hrefs[:limit]:
        try:
            page.goto(job_url)
            page.wait_for_load_state("domcontentloaded")
            session.pause()
            detail = _read_detail_pane(page)
            if store.upsert_job(Job(url=job_url, source="linkedin", **detail)):
                new_count += 1
                console.print(f"  [green]+[/green] {detail['title'] or job_url}")
        except Exception as exc:
            console.print(f"  [yellow]{job_url}: {type(exc).__name__}: {exc}[/yellow]")
    console.print(f"LinkedIn saved jobs: {new_count} new of {len(hrefs)} found.")
    return new_count
