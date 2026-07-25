"""Shared drive-the-form flow for every ATS adapter.

The template method in `BaseATSAdapter.apply` is deliberately conservative:
it refuses to submit when a required question could not be answered
truthfully, when a bot wall is present, or when the resume could not be
attached. "Parked" beats "submitted wrong" every time — a bad application
under the candidate's real name can't be taken back.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any

from .fields import attach_file, fill_field, read_fields

# Terminal states recorded on every attempt.
FILLED = "filled"        # dry run: filled and screenshotted, not submitted
SUBMITTED = "submitted"
BLOCKED = "blocked"      # bot wall, unanswerable required question, etc.
CLOSED = "closed"        # posting no longer accepting applications
FAILED = "failed"        # unexpected error

# Bot walls we do not attempt to work around.
BOT_WALL_SELECTORS = (
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[src*='challenges.cloudflare.com']",
    ".g-recaptcha",
    "#challenge-running",
    "[data-testid='captcha']",
)
BOT_WALL_TEXT = (
    "verify you are human",
    "are you a robot",
    "unusual traffic",
    "complete the security check",
)


@dataclass
class ApplyContext:
    resume_file: Path | None = None
    cover_letter_file: Path | None = None
    answerer: Any = None            # ai.answerer.Answerer
    screenshot_dir: Path | None = None
    submit: bool = False            # False = fill and screenshot only
    pause: Any = None               # callable for human-ish delays
    console: Any = None

    def wait(self) -> None:
        if self.pause is not None:
            self.pause()

    def log(self, message: str) -> None:
        if self.console is not None:
            self.console.print(message)


@dataclass
class ApplyReport:
    url: str
    ats: str = ""
    outcome: str = FAILED
    note: str = ""
    answered: dict[str, str] = dc_field(default_factory=dict)
    parked: list = dc_field(default_factory=list)
    screenshots: list[Path] = dc_field(default_factory=list)
    resume_attached: bool = False

    @property
    def ok(self) -> bool:
        return self.outcome in (FILLED, SUBMITTED)

    def summary(self) -> str:
        bits = [self.outcome.upper()]
        if self.answered:
            bits.append(f"{len(self.answered)} answered")
        if self.parked:
            bits.append(f"{len(self.parked)} parked")
        if self.note:
            bits.append(self.note)
        return " · ".join(bits)


def has_bot_wall(page) -> bool:
    for selector in BOT_WALL_SELECTORS:
        try:
            if page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:
        return False
    return any(phrase in body for phrase in BOT_WALL_TEXT)


class BaseATSAdapter:
    name = "base"
    form_root: str | None = None       # CSS root to limit field discovery
    submit_selectors: tuple[str, ...] = ()
    success_text: tuple[str, ...] = (
        "thank you for applying", "application submitted", "your application has been",
        "thanks for applying", "we have received your application",
        "application received",
    )
    # Substrings identifying a cover-letter file input, when the form has two.
    cover_letter_hints = ("cover", "letter")

    # --- hooks adapters may override -------------------------------------
    def open_form(self, page) -> bool:
        """Reveal the application form. Return False if it can't be opened."""
        return True

    def is_success(self, page) -> bool:
        try:
            body = (page.inner_text("body") or "").lower()
        except Exception:
            return False
        return any(t in body for t in self.success_text)

    # --- template method -------------------------------------------------
    def apply(self, page, url: str, ctx: ApplyContext) -> ApplyReport:
        report = ApplyReport(url=url, ats=self.name)

        if has_bot_wall(page):
            report.outcome, report.note = BLOCKED, "bot wall on the job page"
            return report

        if not self.open_form(page):
            report.outcome, report.note = BLOCKED, "could not open the application form"
            return report

        fields = read_fields(page, self.form_root)
        if not fields:
            report.outcome, report.note = BLOCKED, "no form fields found"
            return report

        report.resume_attached = self._attach_files(page, fields, ctx)
        if ctx.resume_file is not None and not report.resume_attached:
            report.outcome, report.note = BLOCKED, "no resume upload field found"
            return report

        resolved, parked = ctx.answerer.resolve(fields)
        report.parked = parked
        by_idx = {f.idx: f for f in fields}

        for idx, answer in resolved.items():
            target = by_idx.get(idx)
            if target is None:
                continue
            try:
                if fill_field(page, target, answer):
                    report.answered[target.question] = answer
                    ctx.wait()
                else:
                    parked.append(_Unfillable(target, answer))
            except Exception as exc:
                parked.append(_Unfillable(target, f"{answer!r} ({exc})"))

        report.screenshots.append(self._shot(page, ctx, "filled"))

        blockers = [p for p in report.parked if getattr(p.field, "required", False)]
        if blockers:
            report.outcome = BLOCKED
            report.note = (f"{len(blockers)} required question(s) unanswered: "
                           + "; ".join(p.field.question[:60] for p in blockers[:3]))
            return report

        if not ctx.submit:
            report.outcome = FILLED
            report.note = "dry run — nothing submitted"
            return report

        return self._submit(page, ctx, report)

    # --- internals -------------------------------------------------------
    def _attach_files(self, page, fields, ctx: ApplyContext) -> bool:
        """Attach the resume (and cover letter when the form takes one)."""
        file_fields = [f for f in fields if f.kind == "file"]
        if not file_fields or ctx.resume_file is None:
            return False
        cover_fields, resume_fields = [], []
        for f in file_fields:
            label = f.question.lower()
            (cover_fields if any(h in label for h in self.cover_letter_hints)
             else resume_fields).append(f)
        attached = False
        for f in resume_fields or file_fields[:1]:
            try:
                attach_file(page, f, ctx.resume_file)
                ctx.log(f"  attached resume: {ctx.resume_file.name}")
                attached = True
                ctx.wait()
                break
            except Exception:
                continue
        if ctx.cover_letter_file is not None:
            for f in cover_fields:
                try:
                    attach_file(page, f, ctx.cover_letter_file)
                    ctx.log(f"  attached cover letter: {ctx.cover_letter_file.name}")
                    ctx.wait()
                    break
                except Exception:
                    continue
        return attached

    def _submit(self, page, ctx: ApplyContext, report: ApplyReport) -> ApplyReport:
        button = None
        for selector in self.submit_selectors:
            candidate = page.locator(selector).first
            try:
                if candidate.count() and candidate.is_enabled():
                    button = candidate
                    break
            except Exception:
                continue
        if button is None:
            report.outcome, report.note = BLOCKED, "submit button not found"
            return report
        try:
            button.click()
        except Exception as exc:
            report.outcome, report.note = FAILED, f"submit click failed: {exc}"
            return report

        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        report.screenshots.append(self._shot(page, ctx, "after-submit"))

        if has_bot_wall(page):
            report.outcome, report.note = BLOCKED, "bot wall after submit"
            return report
        if self.is_success(page):
            report.outcome, report.note = SUBMITTED, "confirmation page detected"
            return report
        errors = self._validation_errors(page)
        report.outcome = BLOCKED
        report.note = ("no confirmation; form errors: " + "; ".join(errors[:3])
                       if errors else "no confirmation page detected after submit")
        return report

    def _validation_errors(self, page) -> list[str]:
        try:
            return [t.strip() for t in page.locator(
                "[aria-invalid='true'], .error, [class*='error']:not(:empty)"
            ).all_inner_texts() if t.strip()][:5]
        except Exception:
            return []

    def _shot(self, page, ctx: ApplyContext, tag: str) -> Path | None:
        if ctx.screenshot_dir is None:
            return None
        ctx.screenshot_dir.mkdir(parents=True, exist_ok=True)
        path = ctx.screenshot_dir / f"{tag}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
            return path
        except Exception:
            return None


class _Unfillable:
    """A resolved answer the browser wouldn't accept (mirrors FormFieldParked)."""

    __slots__ = ("field", "reason")

    def __init__(self, field, detail: str):
        self.field = field
        self.reason = f"could not set control to {detail}"

    def __repr__(self) -> str:
        return f"<unfillable {self.field.question!r}: {self.reason}>"
