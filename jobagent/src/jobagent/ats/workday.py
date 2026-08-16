"""Workday (myworkdayjobs.com) — account-gated, multi-page applications.

Workday tags nearly every control with a stable ``data-automation-id``, which
is what this adapter keys on; the generic field reader covers the rest. The
flow is a state machine because tenants differ in which pages they show and
in what order:

    posting -> Apply -> (Apply Manually) -> sign in / create account
            -> (email verification) -> My Information -> My Experience
            -> Application Questions -> Voluntary Disclosures -> Self Identify
            -> Review -> Submit -> confirmation

Scenario handling, explicitly:
  * vault already has credentials for the tenant  -> sign in with them
  * no account yet                                -> created ONLY in --submit
    mode (an account under the candidate's email is an outward action a dry
    run must not take); the password is generated and vaulted first, so a
    crash after creation cannot lose it
  * tenant demands email verification             -> IMAP loop, if configured
  * sign-in rejected                              -> parked (retrying risks a
    lockout on the candidate's identity)
  * already applied to this job on this tenant    -> reported as submitted
  * CAPTCHA anywhere                              -> parked, never bypassed
  * validation errors after Next                  -> one re-fill attempt, then
    parked with the messages
  * required question we can't truthfully answer  -> parked (base-class rule)
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .base import (BLOCKED, FAILED, FILLED, SUBMITTED, ApplyContext, ApplyReport,
                   BaseATSAdapter, has_bot_wall)
from .fields import fill_field, option_index, read_fields

WDA = "data-automation-id"

APPLY_BUTTONS = (
    f"a[{WDA}='adventureButton']",
    f"[{WDA}='applyButton']",
    "a:has-text('Apply')",
)
MANUAL_APPLY = (
    f"a[{WDA}='applyManually']",
    f"[{WDA}='applyManuallyLink']",
    "a:has-text('Apply Manually')",
    "button:has-text('Apply Manually')",
)
NEXT_BUTTONS = (
    f"button[{WDA}='bottom-navigation-next-button']",
    f"button[{WDA}='pageFooterNextButton']",
    "button:has-text('Save and Continue')",
    "button:has-text('Next')",
    "button:has-text('Continue')",
    "button:has-text('Review')",
    "button:has-text('Submit')",
)
ERROR_BANNER = f"[{WDA}='errorBanner'], [{WDA}='errorMessage'], [role='alert']"

SUBMITTED_TEXT = (
    "application submitted", "you've applied", "you have applied",
    "thanks for applying", "thank you for applying", "successfully submitted",
)
ALREADY_APPLIED_TEXT = (
    "you have already applied", "already applied to this job",
    "previously applied",
)
VERIFY_TEXT = (
    "verify your email", "verification email", "check your email",
    "sent you an email", "confirm your email",
)

MAX_TRANSITIONS = 18  # multi-page apps are long; endless loops are longer


def tenant_host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


class WorkdayAdapter(BaseATSAdapter):
    name = "workday"

    # --- the whole flow is custom; the base template method doesn't fit ----
    def apply(self, page, url: str, ctx: ApplyContext) -> ApplyReport:
        report = ApplyReport(url=url, ats=self.name)
        host = tenant_host(url)
        error_retry_done = False

        for _ in range(MAX_TRANSITIONS):
            state = self._classify(page)

            if state == "captcha":
                report.outcome, report.note = BLOCKED, "bot wall / CAPTCHA"
                return report

            if state == "already-applied":
                report.outcome = SUBMITTED
                report.note = "tenant reports an application already on file"
                return report

            if state == "submitted":
                report.outcome, report.note = SUBMITTED, "confirmation page detected"
                self._shot(page, ctx, "confirmation")
                return report

            if state == "posting":
                if not self._click_first(page, APPLY_BUTTONS):
                    report.outcome, report.note = BLOCKED, "no Apply button on posting"
                    return report
                page.wait_for_timeout(1500)
                self._click_first(page, MANUAL_APPLY)  # optional chooser page
                page.wait_for_timeout(1500)
                continue

            if state == "auth":
                outcome = self._authenticate(page, host, ctx, report)
                if outcome is not None:
                    return outcome
                page.wait_for_timeout(2000)
                continue

            if state == "verify-email":
                outcome = self._verify_email(page, host, ctx, report)
                if outcome is not None:
                    return outcome
                continue

            if state == "form":
                self._fill_form_page(page, ctx, report)
                self._shot(page, ctx, f"page-{len(report.screenshots) + 1}")

                blockers = [p for p in report.parked
                            if getattr(p.field, "required", False)]
                if blockers:
                    report.outcome = BLOCKED
                    report.note = ("required question(s) unanswered: " + "; ".join(
                        p.field.question[:60] for p in blockers[:3]))
                    return report

                if not ctx.submit and self._is_final_page(page):
                    report.outcome = "filled"
                    report.note = ("dry run — stopped at the final page, "
                                   "nothing submitted")
                    return report

                if not self._click_first(page, NEXT_BUTTONS):
                    report.outcome, report.note = BLOCKED, "no way forward from this page"
                    return report
                page.wait_for_timeout(2500)

                errors = self._page_errors(page)
                if errors:
                    if error_retry_done:
                        report.outcome = BLOCKED
                        report.note = "form errors persist: " + "; ".join(errors[:3])
                        return report
                    error_retry_done = True  # one re-fill pass, then give up
                continue

            # unknown page: give it a moment, then park with diagnostics
            page.wait_for_timeout(2000)
            if self._classify(page) == "unknown":
                self._dump_state(page, ctx, "unrecognized")
                report.outcome = BLOCKED
                report.note = ("unrecognized Workday page — diagnostics saved "
                               "(share the .txt to teach the adapter this page)")
                return report

        report.outcome = FAILED
        report.note = f"gave up after {MAX_TRANSITIONS} page transitions"
        return report

    # --- state detection --------------------------------------------------
    def _classify(self, page) -> str:
        if has_bot_wall(page):
            return "captcha"
        body = self._body(page)
        if any(t in body for t in ALREADY_APPLIED_TEXT):
            return "already-applied"
        if any(t in body for t in SUBMITTED_TEXT):
            return "submitted"
        if self._count(page, f"input[{WDA}='email'], input[{WDA}='password']"):
            return "auth"
        if any(t in body for t in VERIFY_TEXT):
            return "verify-email"
        # A Workday application page is identified by its footer Next/Submit
        # button, or by carrying form controls / an error banner. The button
        # is the most reliable signal — a page can legitimately have a single
        # question (e.g. one dropdown) and still be a form page.
        if (any(self._count(page, s) for s in NEXT_BUTTONS)
                or self._count(page, f"[{WDA}='errorBanner']")
                or self._count(page, "input:not([type=hidden]), select, "
                                     "textarea, button[aria-haspopup='listbox']") >= 1):
            return "form"
        if any(self._count(page, s) for s in APPLY_BUTTONS):
            return "posting"
        return "unknown"

    # --- authentication ---------------------------------------------------
    def _authenticate(self, page, host: str, ctx: ApplyContext,
                      report: ApplyReport):
        """Sign in with vaulted credentials, or create the account.

        Returns a terminal ApplyReport to stop, or None to continue the loop.
        """
        vault = getattr(ctx, "vault", None)
        email = (getattr(ctx, "account_email", "") or "").strip()
        if vault is None or not email:
            report.outcome = BLOCKED
            report.note = ("Workday needs an account and no vault/email is "
                           "configured — set contact.email in answers.yaml")
            return report

        existing = vault.get(host)
        creating = self._on_create_form(page)

        if existing is not None:
            if creating:  # we're on Create Account but have creds: switch
                self._click_first(page, (
                    f"[{WDA}='signInLink']", "button:has-text('Sign In')",
                    "a:has-text('Sign In')"))
                page.wait_for_timeout(1200)
            self._fill_auth(page, existing.email, existing.password,
                            confirm=False)
            self._click_first(page, (
                f"button[{WDA}='signInSubmitButton']",
                f"button[{WDA}='click_filter']",
                "button:has-text('Sign In')"))
            page.wait_for_timeout(2500)
            if self._auth_failed(page):
                self._dump_state(page, ctx, "auth-signin-failed")
                report.outcome = BLOCKED
                report.note = (f"sign-in with the vaulted account for {host} "
                               "was rejected — not retrying to avoid a "
                               "lockout. See `jobagent accounts --show`, or "
                               "reset the password on the tenant and "
                               "`jobagent accounts --delete` the old one.")
                return report
            return None

        # No account yet: creating one is an outward-facing action a dry run
        # won't take. This is a "waiting for --submit", not a block — leave it
        # FILLED so a plain `auto-apply --submit` picks it right back up
        # (no --retry-blocked needed).
        if not ctx.submit:
            report.outcome = FILLED
            report.note = (f"ready — needs a new account on {host}, which is "
                           "created only in --submit mode. Re-run with --submit.")
            return report

        if not creating:
            self._click_first(page, (
                f"[{WDA}='createAccountLink']",
                "button:has-text('Create Account')",
                "a:has-text('Create Account')"))
            page.wait_for_timeout(1200)

        # Vault BEFORE typing it anywhere: a crash mid-signup must not
        # strand an account whose password nobody knows.
        cred = vault.create(host, email, note="created by auto-apply")
        self._fill_auth(page, cred.email, cred.password, confirm=True)
        checkbox = page.locator(f"input[{WDA}='createAccountCheckbox']").first
        try:
            if checkbox.count():
                checkbox.check()
        except Exception:
            pass
        self._click_first(page, (
            f"button[{WDA}='createAccountSubmitButton']",
            f"button[{WDA}='click_filter']",
            "button:has-text('Create Account')"))
        page.wait_for_timeout(2500)
        if self._auth_failed(page):
            self._dump_state(page, ctx, "auth-create-failed")
            errors = self._page_errors(page)
            report.outcome = BLOCKED
            report.note = ("account creation did not complete"
                           + (": " + "; ".join(errors[:2]) if errors else
                              " (no page error visible — see the saved "
                              "diagnostics)")
                           + ". The generated password IS saved — "
                             "`jobagent accounts --show` — so you can also "
                             "finish signup by hand with it, and the agent "
                             "will sign in with it next run.")
            return report
        ctx.log(f"  created Workday account on {host} (saved to the vault)")
        return None

    def _on_create_form(self, page) -> bool:
        return bool(self._count(page, f"input[{WDA}='verifyPassword']"))

    def _fill_auth(self, page, email: str, password: str, confirm: bool) -> None:
        for selector, value in ((f"input[{WDA}='email']", email),
                                (f"input[{WDA}='password']", password)):
            field = page.locator(selector).first
            if field.count():
                field.fill(value)
        if confirm:
            verify = page.locator(f"input[{WDA}='verifyPassword']").first
            if verify.count():
                verify.fill(password)

    def _auth_failed(self, page) -> bool:
        # still on an auth form, or an explicit error is showing
        if self._page_errors(page):
            return True
        return bool(self._count(page, f"input[{WDA}='password']"))

    # --- email verification ------------------------------------------------
    def _verify_email(self, page, host: str, ctx: ApplyContext,
                      report: ApplyReport):
        from ..email_verify import config_from_env, wait_for_verification

        if config_from_env() is None:
            report.outcome = BLOCKED
            report.note = ("tenant requires email verification and "
                           "JOBAGENT_EMAIL / JOBAGENT_EMAIL_APP_PASSWORD are "
                           "not set in .env — see README")
            return report
        ctx.log("  waiting for the verification email...")
        found = wait_for_verification(
            ("myworkday.com", "myworkdayjobs.com", "workday.com", host))
        if not found.found:
            report.outcome = BLOCKED
            report.note = "verification email did not arrive within 3 minutes"
            return report
        if found.link:
            page.goto(found.link, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2000)
            return None
        code_input = page.locator(
            "input[type='text'], input[type='number'], "
            f"input[{WDA}*='code' i]").first
        if code_input.count():
            code_input.fill(found.code)
            self._click_first(page, ("button[type='submit']",
                                     "button:has-text('Verify')",
                                     "button:has-text('Submit')"))
            page.wait_for_timeout(2000)
            return None
        report.outcome = BLOCKED
        report.note = "got a verification code but found no field to enter it"
        return report

    # --- form pages ---------------------------------------------------------
    def _fill_form_page(self, page, ctx: ApplyContext, report: ApplyReport) -> None:
        fields = read_fields(page)
        file_fields = [f for f in fields if f.kind == "file"]
        if file_fields and ctx.resume_file is not None and not report.resume_attached:
            try:
                page.locator(
                    f"[data-ja-field='{file_fields[0].idx}']"
                ).set_input_files(str(ctx.resume_file))
                report.resume_attached = True
                ctx.log(f"  attached resume: {ctx.resume_file.name}")
                page.wait_for_timeout(3000)  # Workday parses the resume
            except Exception:
                pass

        resolved, parked = ctx.answerer.resolve(fields)
        report.parked.extend(parked)
        by_idx = {f.idx: f for f in fields}
        for idx, answer in resolved.items():
            field = by_idx.get(idx)
            if field is None:
                continue
            try:
                if fill_field(page, field, answer):
                    report.answered[field.question] = answer
                    ctx.wait()
            except Exception:
                pass

        self._fill_listbox_dropdowns(page, ctx, report)

    def _fill_listbox_dropdowns(self, page, ctx: ApplyContext,
                                report: ApplyReport) -> None:
        """Workday selects are buttons with aria-haspopup=listbox, invisible
        to the generic <select> path. Open each, read its options, answer."""
        buttons = page.locator("button[aria-haspopup='listbox']")
        try:
            total = min(buttons.count(), 20)
        except Exception:
            return
        for i in range(total):
            button = buttons.nth(i)
            try:
                if not button.is_visible():
                    continue
                question = (button.get_attribute("aria-label")
                            or self._nearest_label(button) or "").strip()
                current = (button.inner_text() or "").strip().lower()
                if not question or current not in ("", "select one", "select"):
                    continue  # unlabeled, or already answered
                button.click()
                page.wait_for_timeout(600)
                options = [t.strip() for t in page.locator(
                    "[role='option'], [data-automation-id='menuItem']"
                ).all_inner_texts() if t.strip()]
                if not options:
                    page.keyboard.press("Escape")
                    continue
                answer = self._answer_for(question, options, ctx)
                if answer is None:
                    page.keyboard.press("Escape")
                    continue
                target = page.locator(
                    "[role='option'], [data-automation-id='menuItem']",
                    has_text=answer).first
                if target.count():
                    target.click()
                    report.answered[question] = answer
                    ctx.wait()
                else:
                    page.keyboard.press("Escape")
            except Exception:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass

    def _answer_for(self, question: str, options: list[str],
                    ctx: ApplyContext) -> str | None:
        from ..ats.fields import FormField

        field = FormField(idx=-1, kind="select", label=question, options=options)
        resolved, _ = ctx.answerer.resolve([field])
        answer = resolved.get(-1)
        if answer is None:
            return None
        i = option_index(options, answer)
        return options[i] if i is not None else None

    def _nearest_label(self, button) -> str:
        try:
            return button.evaluate(
                """el => {
                  const grp = el.closest('[data-automation-id]');
                  const l = grp && grp.querySelector('label');
                  return l ? l.innerText : '';
                }""")
        except Exception:
            return ""

    # --- small helpers ------------------------------------------------------
    def _dump_state(self, page, ctx: ApplyContext, tag: str) -> None:
        """Screenshot + a structural inventory of the page (visible
        data-automation-ids and button labels — no personal content), so a
        parked run on a real tenant can be diagnosed and the adapter taught."""
        self._shot(page, ctx, tag)
        if ctx.screenshot_dir is None:
            return
        try:
            ids = page.eval_on_selector_all(
                "[data-automation-id]",
                "els => els.filter(e => e.offsetParent !== null)"
                ".map(e => e.tagName.toLowerCase() + ':' "
                "+ e.getAttribute('data-automation-id'))") or []
            labels = page.eval_on_selector_all(
                "button, a",
                "els => els.filter(e => e.offsetParent !== null)"
                ".map(e => (e.innerText || '').trim())"
                ".filter(t => t && t.length < 50)") or []
            report = (f"url: {page.url}\n\nvisible data-automation-ids:\n"
                      + "\n".join(f"  {i}" for i in sorted(set(ids)))
                      + "\n\nvisible buttons/links:\n"
                      + "\n".join(f"  {t}" for t in dict.fromkeys(labels)))
            ctx.screenshot_dir.mkdir(parents=True, exist_ok=True)
            (ctx.screenshot_dir / f"{tag}.txt").write_text(
                report, encoding="utf-8")
            ctx.log(f"    [dim]diagnostics saved: {ctx.screenshot_dir / tag}"
                    ".png/.txt[/dim]")
        except Exception:
            pass

    def _is_final_page(self, page) -> bool:
        body = self._body(page)
        return ("review" in body and "submit" in body) or bool(
            self._count(page, "button:has-text('Submit')"))

    def _page_errors(self, page) -> list[str]:
        try:
            texts = page.locator(ERROR_BANNER).all_inner_texts()
        except Exception:
            return []
        return [t.strip() for t in texts if t.strip()][:5]

    def _click_first(self, page, selectors) -> bool:
        for selector in selectors:
            button = page.locator(selector).first
            try:
                if not (button.count() and button.is_visible()):
                    continue
                # Bounded: without a timeout Playwright scrolls-and-retries for
                # 30s on a button it can't reach, which looks like the page
                # endlessly scrolling. Fail fast and let the caller move on.
                button.click(timeout=6000)
                return True
            except Exception:
                try:  # last resort: a forced click ignores actionability
                    button.click(force=True, timeout=3000)
                    return True
                except Exception:
                    continue
        return False

    def _count(self, page, selector: str) -> int:
        try:
            return page.locator(selector).count()
        except Exception:
            return 0

    def _body(self, page) -> str:
        try:
            return (page.inner_text("body") or "").lower()
        except Exception:
            return ""
