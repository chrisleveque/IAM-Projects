"""Greenhouse job boards (boards.greenhouse.io, job-boards.greenhouse.io).

Greenhouse takes applications without an account, which is why it's a phase-1
target. Two layouts are in the wild: the classic `#application_form` and the
newer job-boards React app; both are plain forms underneath.
"""

from __future__ import annotations

from .base import BaseATSAdapter

APPLY_TRIGGERS = (
    "a#apply_button",
    "a[href='#application']",
    "button:has-text('Apply for this job')",
    "a:has-text('Apply for this job')",
    "button:has-text('Apply')",
)

FORM_ROOTS = ("#application_form", "form#application-form", "main form", "form")


class GreenhouseAdapter(BaseATSAdapter):
    name = "greenhouse"
    submit_selectors = (
        "#submit_app",
        "input[type='submit'][value*='Submit']",
        "button[type='submit']:has-text('Submit')",
        "button:has-text('Submit application')",
    )

    def open_form(self, page) -> bool:
        """Greenhouse usually renders the form inline; some boards gate it
        behind an Apply button that just scrolls/expands."""
        for selector in FORM_ROOTS:
            if page.locator(selector).count():
                self.form_root = selector
                return True
        for trigger in APPLY_TRIGGERS:
            button = page.locator(trigger).first
            try:
                if button.count() and button.is_visible():
                    button.click()
                    page.wait_for_timeout(1500)
                    break
            except Exception:
                continue
        for selector in FORM_ROOTS:
            if page.locator(selector).count():
                self.form_root = selector
                return True
        return False
