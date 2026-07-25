"""Lever job postings (jobs.lever.co).

Lever also needs no account. The posting page carries an "Apply for this job"
link to `<posting-url>/apply`, which holds the real form.
"""

from __future__ import annotations

from .base import BaseATSAdapter

APPLY_TRIGGERS = (
    "a.postings-btn[href*='/apply']",
    "a[href$='/apply']",
    "a:has-text('Apply for this job')",
    "a:has-text('Apply')",
)


class LeverAdapter(BaseATSAdapter):
    name = "lever"
    form_root = "form"
    submit_selectors = (
        "button#btn-submit",
        "button[type='submit']:has-text('Submit')",
        "input[type='submit']",
        "button:has-text('Submit application')",
    )

    def open_form(self, page) -> bool:
        if self._form_present(page):
            return True
        # Prefer navigating straight to /apply — clicking can be intercepted
        # by cookie banners on some postings.
        url = page.url.split("?")[0].rstrip("/")
        if not url.endswith("/apply"):
            try:
                page.goto(f"{url}/apply", wait_until="domcontentloaded",
                          timeout=45000)
                page.wait_for_timeout(1200)
                if self._form_present(page):
                    return True
            except Exception:
                pass
        for trigger in APPLY_TRIGGERS:
            button = page.locator(trigger).first
            try:
                if button.count() and button.is_visible():
                    button.click()
                    page.wait_for_timeout(1500)
                    if self._form_present(page):
                        return True
            except Exception:
                continue
        return self._form_present(page)

    def _form_present(self, page) -> bool:
        try:
            return page.locator("form input[name='resume'], "
                                "form input[type='file'], "
                                "input[name='name']").count() > 0
        except Exception:
            return False
