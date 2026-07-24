"""Walk a LinkedIn Easy Apply modal: upload the tailored resume, fill fields,
advance through the steps, and STOP at Submit for the human to review + click.

Returns one of: "applied", "skipped", "manual" (no Easy Apply — external ATS),
"failed".
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from ..browser import BrowserSession
from ..store import Job
from .formfill import FormContext, fill_scope

SELECTORS = {
    "easy_apply_button": "button.jobs-apply-button, "
                         "div.jobs-apply-button--top-card button, "
                         "button[aria-label*='Easy Apply' i], "
                         "button:has-text('Easy Apply')",
    "modal": "div.jobs-easy-apply-modal, div[data-test-modal], div[role='dialog']",
    "next": "button[aria-label='Continue to next step'], "
            "button[aria-label='Review your application'], "
            "button:has-text('Review'), button:has-text('Next')",
    "submit": "button[aria-label='Submit application'], "
              "button:has-text('Submit application')",
    "dismiss": "button[aria-label='Dismiss']",
    "discard": "button[data-control-name='discard_application_confirm_btn'], "
               "button:has-text('Discard')",
}

MAX_STEPS = 12


def apply_to_job(session: BrowserSession, job: Job, ctx: FormContext,
                 console: Console) -> str:
    page = session.page
    page.goto(job.url)
    page.wait_for_load_state("domcontentloaded")
    session.pause()

    button = page.locator(SELECTORS["easy_apply_button"]).first
    try:
        if button.count() == 0:
            return "manual"
        label = (button.inner_text(timeout=5000) or "") + " " + \
            (button.get_attribute("aria-label") or "")
        if "easy apply" not in label.lower():
            return "manual"
        button.click()
        session.pause()
    except Exception:
        return "manual"

    modal = page.locator(SELECTORS["modal"]).first
    if modal.count() == 0:
        return "failed"

    all_skipped: list[str] = []
    for _ in range(MAX_STEPS):
        all_skipped += fill_scope(modal, ctx, session.pause)
        submit = modal.locator(SELECTORS["submit"]).first
        if submit.count() and submit.is_visible():
            break
        nxt = modal.locator(SELECTORS["next"]).first
        if nxt.count() and nxt.is_visible():
            nxt.click()
            session.pause()
        else:
            break

    lines = [f"[bold]{job.title}[/bold] at {job.company}",
             "The form is filled as far as I could take it."]
    if all_skipped:
        lines.append("[yellow]Left blank (please fill in the browser):[/yellow]")
        lines += [f"  • {q}" for q in dict.fromkeys(all_skipped)]
    lines.append("\n[bold green]Review the modal in the browser and click "
                 "Submit yourself if it looks right.[/bold green]")
    console.print(Panel("\n".join(lines), title="LinkedIn Easy Apply — your turn"))

    reply = Prompt.ask(
        "Press Enter AFTER you submitted, or type 's' to skip this job",
        default="",
    ).strip().lower()
    if reply == "s":
        _discard(page, console)
        return "skipped"
    return "applied"


def _discard(page, console: Console) -> None:
    try:
        dismiss = page.locator(SELECTORS["dismiss"]).first
        if dismiss.count():
            dismiss.click()
            discard = page.locator(SELECTORS["discard"]).first
            if discard.count():
                discard.click()
    except Exception:
        console.print("[yellow]Couldn't close the modal automatically — "
                      "close it in the browser.[/yellow]")
