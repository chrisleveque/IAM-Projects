"""Walk an Indeed Apply flow (smartapply wizard), fill what we can, and STOP
before Submit for the human to review + click.

Returns one of: "applied", "skipped", "manual" (external ATS), "failed".
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from ..browser import BrowserSession
from ..store import Job
from .formfill import FormContext, fill_scope

SELECTORS = {
    "apply_button": "#indeedApplyButton, button:has-text('Apply now')",
    "continue": "button:has-text('Continue'), button:has-text('Next'), "
                "button[data-testid='continue-button']",
    "submit": "button:has-text('Submit your application'), "
              "button:has-text('Submit application'), button:has-text('Submit')",
}

MAX_STEPS = 15


def apply_to_job(session: BrowserSession, job: Job, ctx: FormContext,
                 console: Console) -> str:
    page = session.page
    page.goto(job.url)
    page.wait_for_load_state("domcontentloaded")
    session.pause()

    button = page.locator(SELECTORS["apply_button"]).first
    try:
        if button.count() == 0 or not button.is_visible():
            return "manual"
    except Exception:
        return "manual"

    # Indeed Apply sometimes opens a new tab (smartapply.indeed.com).
    apply_page = page
    try:
        with page.context.expect_page(timeout=8000) as new_page_info:
            button.click()
        apply_page = new_page_info.value
    except Exception:
        pass  # stayed in the same tab
    apply_page.wait_for_load_state("domcontentloaded")
    session.pause()

    all_skipped: list[str] = []
    for _ in range(MAX_STEPS):
        all_skipped += fill_scope(apply_page.locator("body"), ctx, session.pause)
        submit = apply_page.locator(SELECTORS["submit"]).first
        if submit.count() and submit.is_visible():
            break
        cont = apply_page.locator(SELECTORS["continue"]).first
        if cont.count() and cont.is_visible():
            cont.click()
            session.pause()
        else:
            break

    lines = [f"[bold]{job.title}[/bold] at {job.company}",
             "The wizard is filled as far as I could take it."]
    if all_skipped:
        lines.append("[yellow]Left blank (please fill in the browser):[/yellow]")
        lines += [f"  • {q}" for q in dict.fromkeys(all_skipped)]
    lines.append("\n[bold green]Review each page in the browser and click "
                 "Submit yourself if it looks right.[/bold green]")
    console.print(Panel("\n".join(lines), title="Indeed Apply — your turn"))

    reply = Prompt.ask(
        "Press Enter AFTER you submitted, or type 's' to skip this job",
        default="",
    ).strip().lower()
    if apply_page is not page:
        try:
            apply_page.close()
        except Exception:
            pass
    return "skipped" if reply == "s" else "applied"
