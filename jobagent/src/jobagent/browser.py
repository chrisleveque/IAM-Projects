"""Playwright session with a persistent (logged-in) profile and human-like pacing.

Always headed: you watch everything the agent does, and login/2FA/captchas are
handled by you in the real window. Cookies persist in the profile dir, so
`jobagent login` is only needed once (or when a session expires).
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright
from rich.console import Console

from .config import AppConfig

ENGINE_MARKER = ".engine"


def read_pinned_engine(profile_dir: Path) -> str | None:
    """Which engine created this profile, if recorded."""
    marker = profile_dir / ENGINE_MARKER
    if marker.exists():
        value = marker.read_text(encoding="utf-8").strip()
        if value in ("chrome", "chromium"):
            return value
    return None


def pin_engine(profile_dir: Path, engine: str) -> None:
    (profile_dir / ENGINE_MARKER).write_text(engine, encoding="utf-8")


def profile_dir_for(cfg: AppConfig, site: str) -> Path:
    """Each site gets its own browser profile (browser_profile-linkedin, ...).

    LinkedIn and Indeed have opposite needs: LinkedIn sessions persist
    reliably under bundled Chromium's cookie store but not real Chrome's,
    while Indeed's Cloudflare check passes real Chrome but blocks Chromium.
    Site-specific profiles let each run on its proven engine.
    """
    base = cfg.resolve(cfg.paths.browser_profile)
    if site in ("", "default"):
        return base
    return base.parent / f"{base.name}-{site}"


class BrowserSession:
    def __init__(self, cfg: AppConfig, site: str = "default"):
        self.cfg = cfg
        self.site = site
        self._pw = None
        self.context: BrowserContext | None = None

    def __enter__(self) -> "BrowserSession":
        profile_dir = profile_dir_for(self.cfg, self.site)
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        launch_kwargs = dict(
            headless=False,
            viewport={"width": 1440, "height": 900},
            # Playwright disables the Chrome sandbox by default, which puts
            # Chrome in a degraded automation mode (visible "--no-sandbox"
            # warning banner). Run with the sandbox on, like normal Chrome.
            chromium_sandbox=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                # Chrome 127+ encrypts cookies with "app-bound encryption",
                # which does not survive automation-launched sessions on
                # Windows — cookies written in one run can't be decrypted in
                # the next, presenting as a logout after every restart. Use
                # the legacy per-user encryption so sessions persist.
                "--disable-features=AppBoundEncryption",
            ],
        )
        # The engine is PINNED per profile: Chrome and Chromium encrypt the
        # cookie store differently, so a silent switch between runs makes all
        # saved logins unreadable — which looks like being mysteriously logged
        # out. Whichever engine creates the profile is the only one allowed to
        # open it.
        pinned = read_pinned_engine(profile_dir)
        if self.site == "linkedin":
            # LinkedIn sessions persist reliably only under bundled Chromium's
            # cookie store (empirically: they survived for days on Chromium
            # and died between runs on real Chrome). Cloudflare isn't a factor
            # on LinkedIn, so Chromium is strictly better here.
            pinned = "chromium"
        if pinned == "chrome":
            try:
                self.context = self._pw.chromium.launch_persistent_context(
                    str(profile_dir), channel="chrome", **launch_kwargs
                )
                self.engine = "chrome"
            except Exception as exc:
                self._pw.stop()
                raise RuntimeError(
                    "This browser profile belongs to real Chrome, but Chrome "
                    "failed to launch just now. Falling back to Chromium would "
                    "silently log you out, so stopping instead. Wait for any "
                    "Chrome update to finish and retry — or delete the "
                    "browser_profile folder to start fresh."
                ) from exc
        elif pinned == "chromium":
            self.context = self._pw.chromium.launch_persistent_context(
                str(profile_dir), **launch_kwargs
            )
            self.engine = "chromium"
            if read_pinned_engine(profile_dir) != "chromium":
                pin_engine(profile_dir, "chromium")
        else:
            # Fresh profile: prefer the user's real Google Chrome (bot
            # protection trusts it far more than bundled Chromium), then pin.
            try:
                self.context = self._pw.chromium.launch_persistent_context(
                    str(profile_dir), channel="chrome", **launch_kwargs
                )
                self.engine = "chrome"
            except Exception:
                self.context = self._pw.chromium.launch_persistent_context(
                    str(profile_dir), **launch_kwargs
                )
                self.engine = "chromium"
            pin_engine(profile_dir, self.engine)
        Console().print(f"[dim]browser engine: {self.engine} "
                        f"(profile: {profile_dir.name})[/dim]")
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
