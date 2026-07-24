"""jobagent CLI — login | scan | score | review | tailor | apply | status | doctor."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .config import AppConfig, load_config
from .store import Job, Store

app = typer.Typer(help="Semi-automated job application copilot for LinkedIn and Indeed. "
                       "It scans, scores, tailors, and pre-fills — YOU click submit.",
                  no_args_is_help=True)
console = Console()


def _cfg() -> AppConfig:
    return load_config()


def _store(cfg: AppConfig) -> Store:
    return Store(cfg.db_path)


def _master_resume(cfg: AppConfig) -> str:
    path = cfg.master_resume_path
    if not path.exists():
        raise typer.Exit(code=_fail(f"master resume not found at {path}"))
    text = path.read_text(encoding="utf-8")
    if "REPLACE ME" in text:
        raise typer.Exit(code=_fail(
            f"{path} still contains the template marker — paste your real resume "
            "into it first (delete the REPLACE ME comment)."))
    return text


def _answers(cfg: AppConfig) -> dict:
    path = cfg.answers_path
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _ai(cfg: AppConfig):
    from .ai.client import AIClient
    return AIClient(cfg.ai.model, cfg.ai.max_tokens)


def _fail(msg: str) -> int:
    console.print(f"[red]{msg}[/red]")
    return 1


def _import_linkedin_cookies(cfg, cookies: list[dict]) -> None:
    from .browser import BrowserSession
    with BrowserSession(cfg, site="linkedin") as session:
        session.context.add_cookies(cookies)
        page = session.page
        page.goto("https://www.linkedin.com/feed/")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)
        if "feed" in page.url:
            console.print(f"[green]LinkedIn session imported "
                          f"({len(cookies)} cookie(s)) — you're logged in.[/green]")
        else:
            console.print(f"[yellow]Cookies set, but LinkedIn landed on "
                          f"{page.url} instead of the feed — the export may be "
                          "stale; re-export and try again.[/yellow]")
        Prompt.ask("Look at the browser window — you should see your LinkedIn "
                   "feed. Press Enter here to close it (your session is saved "
                   "on disk and the next command reuses it)", default="")


@app.command()
def login(
    linkedin_cookie: bool = typer.Option(
        False, "--linkedin-cookie",
        help="Import your LinkedIn li_at session cookie from your normal "
             "browser instead of signing in."),
    cookie_file: Optional[str] = typer.Option(
        None, "--cookie-file",
        help="Import a FULL LinkedIn cookie export (JSON from the "
             "Cookie-Editor extension). Stronger than --linkedin-cookie: the "
             "whole cookie family transfers, so LinkedIn sees a coherent "
             "session instead of a lone token."),
):
    """Open a browser to log in to LinkedIn and Indeed (cookies persist locally)."""
    from .browser import BrowserSession
    cfg = _cfg()

    if cookie_file:
        from .cookies import parse_cookie_export
        try:
            cookies = parse_cookie_export(Path(cookie_file).read_text(encoding="utf-8"))
        except Exception as exc:
            raise typer.Exit(code=_fail(f"could not parse {cookie_file}: {exc}"))
        if not cookies:
            raise typer.Exit(code=_fail(
                "no linkedin.com cookies found in that file — export while on "
                "linkedin.com so the extension captures its cookies"))
        _import_linkedin_cookies(cfg, cookies)
        return

    if linkedin_cookie:
        console.print(Panel(
            "Grab your LinkedIn session cookie from your NORMAL Chrome:\n\n"
            "1. In your regular Chrome (where you're logged in), open linkedin.com\n"
            "2. Press F12 to open DevTools -> [bold]Application[/bold] tab\n"
            "3. Left sidebar: Storage -> Cookies -> https://www.linkedin.com\n"
            "4. Find the cookie named [bold]li_at[/bold] and copy its Value\n\n"
            "Treat that value like a password — it IS your logged-in session.",
            title="Import LinkedIn session"))
        value = Prompt.ask("Paste the li_at value (input hidden)",
                           password=True).strip()
        if not value:
            raise typer.Exit(code=_fail("no cookie value provided"))
        _import_linkedin_cookies(cfg, [{
            "name": "li_at", "value": value,
            "domain": ".linkedin.com", "path": "/",
            "httpOnly": True, "secure": True, "sameSite": "None",
        }])
        return

    console.print("For LinkedIn, prefer [cyan]jobagent login --linkedin-cookie[/cyan] "
                  "(LinkedIn blocks password sign-in in automated browsers).")
    with BrowserSession(cfg, site="linkedin") as session:
        session.page.goto("https://www.linkedin.com/login")
        console.print("Log in to [bold]LinkedIn[/bold] in the browser window, "
                      "or close this step with Enter if you use the cookie import.")
        Prompt.ask("Press Enter here when done with LinkedIn", default="")
    with BrowserSession(cfg, site="indeed") as session:
        for attempt in range(3):
            try:
                session.page.goto("https://secure.indeed.com/auth",
                                  wait_until="domcontentloaded")
                break
            except Exception:
                if attempt == 2:
                    raise
                session.page.wait_for_timeout(2000)
        console.print("Now log in to [bold]Indeed[/bold] (tip: enter your email "
                      "and choose the sign-in code option — no password needed).")
        Prompt.ask("Press Enter here when Indeed is logged in", default="")
    console.print("[green]Sessions saved to the local browser profiles. "
                  "You won't need to log in again unless they expire.[/green]")


@app.command()
def scan(
    source: Optional[str] = typer.Option(None, help="Only scan one source: linkedin | indeed"),
    saved: bool = typer.Option(False, "--saved", help="Also import your LinkedIn saved jobs"),
    saved_only: bool = typer.Option(False, "--saved-only",
                                    help="Import ONLY your LinkedIn saved jobs; "
                                         "skip the searches in config.yaml"),
):
    """Run the searches in config.yaml and store discovered jobs."""
    from .browser import BrowserSession
    from .scrapers import indeed as indeed_scraper
    from .scrapers import linkedin as linkedin_scraper

    cfg = _cfg()
    store = _store(cfg)
    if saved_only:
        saved = True
        searches = []
    else:
        searches = [s for s in cfg.searches if source is None or s.source == source]
    if not searches and not saved:
        raise typer.Exit(code=_fail("no searches configured in config.yaml"))

    total_new = 0
    by_source: dict[str, list] = {}
    for spec in searches:
        by_source.setdefault(spec.source, []).append(spec)
    for src, specs in by_source.items():
        scraper = {"linkedin": linkedin_scraper, "indeed": indeed_scraper}.get(src)
        if scraper is None:
            console.print(f"[yellow]unknown source '{src}' — skipping[/yellow]")
            continue
        with BrowserSession(cfg, site=src) as session:
            for spec in specs:
                total_new += scraper.scan(session, store, spec, console)
                session.job_pause()
    if saved and (source in (None, "linkedin")):
        with BrowserSession(cfg, site="linkedin") as session:
            total_new += linkedin_scraper.scan_saved(session, store, console)
    console.print(f"\n[bold]{total_new} new job(s) discovered.[/bold] "
                  "Next: [cyan]jobagent score[/cyan]")


@app.command()
def add(
    urls: Optional[list[str]] = typer.Argument(
        None, help="Job posting URLs (LinkedIn /jobs/view/... or Indeed "
                   "viewjob?jk=...) — or use --paste for many at once"),
    paste: bool = typer.Option(
        False, "--paste",
        help="Paste many URLs at once (one per line; empty line finishes). "
             "Pairs with the saved-jobs bookmarklet in the README."),
):
    """Add specific jobs by pasted URL — no LinkedIn login needed.

    Jobs enter the pipeline tagged as saved (work with tailor/apply --saved).
    """
    from .browser import BrowserSession
    from .scrapers import indeed as indeed_scraper
    from .scrapers import linkedin as linkedin_scraper

    cfg = _cfg()
    store = _store(cfg)
    urls = list(urls or [])
    if paste:
        console.print("Paste job URLs (one per line). Press Enter on an "
                      "empty line to finish:")
        while True:
            try:
                line = input().strip()
            except EOFError:
                break
            if not line:
                break
            urls.extend(line.split())
    if not urls:
        raise typer.Exit(code=_fail("no URLs provided — pass them as arguments "
                                    "or use --paste"))
    groups = {
        "linkedin": [u for u in urls if "linkedin.com" in u],
        "indeed": [u for u in urls if "indeed.com" in u],
    }
    for url in urls:
        if "linkedin.com" not in url and "indeed.com" not in url:
            console.print(f"[yellow]skipping unrecognized URL: {url}[/yellow]")
    added = 0
    for src, src_urls in groups.items():
        if not src_urls:
            continue
        fetch = (linkedin_scraper if src == "linkedin" else indeed_scraper).fetch_job
        with BrowserSession(cfg, site=src) as session:
            for url in src_urls:
                job = fetch(session, url, console)
                if job is None:
                    continue
                is_new = store.upsert_job(job)
                note = "" if job.description else (
                    "  [yellow](no description captured — jobagent score will "
                    "skip it; tell Claude if the posting is public)[/yellow]")
                console.print(f"  [green]{'+' if is_new else '~'}[/green] "
                              f"{job.title or job.url} — {job.company}{note}")
                added += 1
    console.print(f"\n[bold]{added} job(s) added[/bold] (tagged saved ★). "
                  "Next: [cyan]jobagent score[/cyan]")


@app.command()
def score():
    """Score all unscored jobs against your master resume (uses the Claude API)."""
    from .ai.scorer import score_job

    cfg = _cfg()
    store = _store(cfg)
    resume = _master_resume(cfg)
    jobs = store.list_jobs(status="discovered")
    if not jobs:
        console.print("Nothing to score. Run [cyan]jobagent scan[/cyan] first.")
        return
    ai = _ai(cfg)
    for job in jobs:
        if not job.description:
            console.print(f"[yellow]no description for {job.url} — skipping[/yellow]")
            continue
        try:
            result = score_job(ai, resume, job)
        except Exception as exc:
            console.print(f"[red]scoring failed for {job.url}: {exc}[/red]")
            continue
        store.update(job.url, status="scored", score=result.score,
                     score_reasons=result.summary())
        color = "green" if result.score >= cfg.scoring.min_score_to_tailor else "dim"
        console.print(f"[{color}]{result.score:>3}[/{color}]  {job.title} — {job.company}")
    console.print(f"\nDone. Next: [cyan]jobagent review[/cyan] (optional) or "
                  f"[cyan]jobagent tailor[/cyan]")


@app.command()
def review():
    """Review scored jobs and queue/skip them interactively."""
    cfg = _cfg()
    store = _store(cfg)
    jobs = store.list_jobs(status=("scored", "queued"))
    if not jobs:
        console.print("Nothing to review. Run [cyan]jobagent score[/cyan] first.")
        return
    for job in jobs:
        console.print(Panel(
            f"[bold]{job.title}[/bold] at {job.company} ({job.location})\n"
            f"score: {job.score}   easy-apply: {'yes' if job.easy_apply else 'no'}\n"
            f"{job.score_reasons}\n{job.url}",
            title=f"[{job.status}]",
        ))
        choice = Prompt.ask("(q)ueue / (s)kip / Enter to leave as-is / (x) stop reviewing",
                            default="").strip().lower()
        if choice == "q":
            store.update(job.url, status="queued")
        elif choice == "s":
            store.update(job.url, status="skipped")
        elif choice == "x":
            break


@app.command()
def tailor(
    min_score: Optional[int] = typer.Option(None, help="Override scoring.min_score_to_tailor"),
    url: Optional[str] = typer.Option(None, help="Tailor a single job by URL"),
    saved: bool = typer.Option(False, "--saved",
                               help="Only tailor jobs imported from your saved list"),
):
    """Generate a tailored resume + cover letter (.docx/.pdf) per qualifying job."""
    from .ai.tailor import tailor_for_job
    from .docgen import (convert_to_pdf, slugify, write_cover_letter_docx,
                         write_resume_docx)

    cfg = _cfg()
    store = _store(cfg)
    resume_text = _master_resume(cfg)
    threshold = cfg.scoring.min_score_to_tailor if min_score is None else min_score

    if url:
        job = store.get_job(url)
        if job is None:
            raise typer.Exit(code=_fail(f"job not found in tracker: {url}"))
        jobs = [job]
    else:
        saved_filter = True if saved else None
        # queued jobs are explicitly user-approved regardless of score
        jobs = store.list_jobs(status="queued", saved=saved_filter) + [
            j for j in store.list_jobs(status="scored", min_score=threshold,
                                       saved=saved_filter)
        ]
    if not jobs:
        console.print(f"No jobs at/above score {threshold} to tailor. "
                      "Run [cyan]jobagent score[/cyan] or queue jobs in "
                      "[cyan]jobagent review[/cyan].")
        return

    ai = _ai(cfg)
    for job in jobs:
        console.print(f"Tailoring for [bold]{job.title}[/bold] at {job.company} ...")
        try:
            package = tailor_for_job(ai, resume_text, job,
                                     extra_instructions=cfg.tailoring.instructions)
        except Exception as exc:
            console.print(f"[red]tailoring failed: {exc}[/red]")
            continue
        job_dir = cfg.output_dir / f"{slugify(job.company or job.source)}-{slugify(job.title)}"
        resume_docx = write_resume_docx(package.resume, job_dir / "resume.docx")
        cover_docx = write_cover_letter_docx(
            package.cover_letter, package.resume.name, job_dir / "cover_letter.docx")
        resume_pdf = convert_to_pdf(resume_docx)
        convert_to_pdf(cover_docx)
        store.update(job.url, status="tailored",
                     resume_path=str(resume_pdf or resume_docx),
                     cover_letter_path=str(cover_docx))
        console.print(f"  [green]->[/green] {job_dir}"
                      + ("" if resume_pdf else "  [yellow](no PDF — LibreOffice not "
                         "installed, docx only)[/yellow]"))
    console.print("\nNext: [cyan]jobagent apply[/cyan]")


@app.command(name="apply")
def apply_cmd(
    source: Optional[str] = typer.Option(None, help="Only apply on one source: linkedin | indeed"),
    saved: bool = typer.Option(False, "--saved",
                               help="Only apply to jobs imported from your saved list"),
):
    """Pre-fill applications for tailored jobs. YOU review and click Submit."""
    from .apply import indeed_apply, linkedin_easy_apply
    from .apply.formfill import FormContext
    from .browser import BrowserSession

    cfg = _cfg()
    store = _store(cfg)
    jobs = store.list_jobs(status="tailored", source=source,
                           saved=True if saved else None)
    if not jobs:
        console.print("No tailored jobs ready. Run [cyan]jobagent tailor[/cyan] first.")
        return

    try:
        ai = _ai(cfg)
        master = _master_resume(cfg)
    except Exception:
        ai, master = None, ""  # AI drafting of unknown answers is optional here

    answers = _answers(cfg)
    applied_today = store.count_applied_today()
    cap = cfg.limits.max_applications_per_day

    for src in ("linkedin", "indeed"):
        src_jobs = [j for j in jobs if j.source == src]
        if not src_jobs or applied_today >= cap:
            continue
        with BrowserSession(cfg, site=src) as session:
            for job in src_jobs:
                if applied_today >= cap:
                    console.print(f"[yellow]Daily cap reached ({cap}). "
                                  "Run again tomorrow or raise "
                                  "limits.max_applications_per_day.[/yellow]")
                    break
                resume_file = Path(job.resume_path) if job.resume_path else None
                if resume_file is not None and not resume_file.exists():
                    resume_file = None
                ctx = FormContext(answers, resume_file, console, ai=ai,
                                  master_resume=master, answers_path=cfg.answers_path)
                flow = linkedin_easy_apply if job.source == "linkedin" else indeed_apply
                console.print(f"\n[bold]Applying:[/bold] {job.title} at "
                              f"{job.company} ({job.source})")
                try:
                    outcome = flow.apply_to_job(session, job, ctx, console)
                except Exception as exc:
                    console.print(f"[red]apply flow failed: {exc}[/red]")
                    outcome = "failed"
                if outcome == "applied":
                    store.update(job.url, status="applied")
                    applied_today += 1
                    console.print("[green]Marked applied.[/green]")
                elif outcome == "skipped":
                    store.update(job.url, status="skipped")
                elif outcome == "manual":
                    console.print(Panel(
                        f"No in-platform apply for this job (external ATS).\n"
                        f"Your tailored docs: {job.resume_path}\nApply here: {job.url}\n"
                        "It stays in the tracker as 'tailored'.",
                        title="Manual apply needed"))
                session.job_pause()
    console.print(f"\nApplied today: {store.count_applied_today()}/{cap}")


@app.command()
def status():
    """Show the pipeline: counts per status and the most recent jobs."""
    cfg = _cfg()
    store = _store(cfg)
    counts = store.status_counts()
    summary = "  ".join(f"{s}: [bold]{counts.get(s, 0)}[/bold]"
                        for s in ("discovered", "scored", "queued", "tailored",
                                  "applied", "skipped"))
    console.print(Panel(summary, title="pipeline"))

    table = Table(show_lines=False)
    for col in ("score", "status", "title", "company", "source", "easy", "saved"):
        table.add_column(col)
    for job in store.list_jobs()[:25]:
        table.add_row(str(job.score if job.score is not None else "-"), job.status,
                      job.title[:48], job.company[:28], job.source,
                      "yes" if job.easy_apply else "no",
                      "★" if job.saved else "")
    console.print(table)


@app.command()
def doctor():
    """Check that config, profile, API key, and browser are ready to go."""
    import shutil as _shutil

    cfg = _cfg()
    ok = True

    def check(label: str, passed: bool, hint: str = "") -> None:
        nonlocal ok
        mark = "[green]OK[/green]" if passed else f"[red]MISSING[/red] {hint}"
        console.print(f"  {label}: {mark}")
        ok = ok and passed

    console.print(f"project root: {cfg.root}")
    check("config.yaml", (cfg.root / "config.yaml").exists())
    check("searches configured", bool(cfg.searches))
    resume_path = cfg.master_resume_path
    resume_ready = resume_path.exists() and "REPLACE ME" not in resume_path.read_text(encoding="utf-8")
    check("master resume filled in", resume_ready,
          f"— edit {resume_path} (remove the REPLACE ME comment)")
    answers_path = cfg.answers_path
    answers_ready = answers_path.exists() and "REPLACE ME" not in answers_path.read_text(encoding="utf-8")
    check("answers.yaml filled in", answers_ready,
          f"— edit {answers_path} (remove the REPLACE ME line)")
    import os
    check("ANTHROPIC_API_KEY set", bool(os.environ.get("ANTHROPIC_API_KEY")),
          "— copy .env.example to .env and add your key")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            check("playwright chromium installed",
                  Path(pw.chromium.executable_path).exists(),
                  "— run: playwright install chromium")
    except Exception as exc:
        check("playwright chromium installed", False, f"({exc})")
    has_soffice = bool(_shutil.which("soffice") or _shutil.which("libreoffice"))
    console.print(f"  LibreOffice for PDF export (optional): "
                  f"{'[green]found — will attempt PDF, falls back to .docx[/green]' if has_soffice else '[yellow]not found — .docx only[/yellow]'}")
    console.print("\n[green]All set — run: jobagent login[/green]" if ok
                  else "\n[yellow]Fix the items above, then rerun jobagent doctor.[/yellow]")


if __name__ == "__main__":
    app()
