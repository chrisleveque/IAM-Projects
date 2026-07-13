"""Playwright session with a persistent (logged-in) profile and human-like pacing.

Always headed: you watch everything the agent does, and login/2FA/captchas are
handled by you in the real window. Cookies persist in the profile dir, so
`jobagent login` is only needed once (or when a session expires).
"""

from __future__ import annotations

import random
import time

from playwright.sync_api import BrowserContext, Page, sync_playwright

from .config import AppConfig


class BrowserSession:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._pw = None
        self.context: BrowserContext | None = None

    def __enter__(self) -> "BrowserSession":
        profile_dir = self.cfg.resolve(self.cfg.paths.browser_profile)
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.context.set_default_timeout(15_000)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.context is not None:
            try:
                self.context.close()
            except Exception:
                pass
        if self._pw is not None:
            self._pw.stop()

    @property
    def page(self) -> Page:
        assert self.context is not None, "session not started"
        return self.context.pages[0] if self.context.pages else self.context.new_page()

    def new_page(self) -> Page:
        assert self.context is not None, "session not started"
        return self.context.new_page()

    def pause(self, lo: float | None = None, hi: float | None = None) -> None:
        """Short randomized delay between on-page actions."""
        lo = self.cfg.limits.min_action_delay_seconds if lo is None else lo
        hi = self.cfg.limits.max_action_delay_seconds if hi is None else hi
        time.sleep(random.uniform(lo, max(lo, hi)))

    def job_pause(self) -> None:
        """Longer randomized delay between jobs."""
        self.pause(
            self.cfg.limits.min_job_delay_seconds,
            self.cfg.limits.max_job_delay_seconds,
        )
