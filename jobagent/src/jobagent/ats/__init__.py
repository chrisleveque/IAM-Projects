"""Applicant Tracking System (ATS) adapters for autonomous external applying.

`detect_ats` classifies an external apply URL; `adapter_for` returns the
adapter that knows how to drive that system's form. Adapters for systems we
can't complete unattended (account creation, bot walls) are absent on
purpose — those jobs get parked as `blocked` rather than half-applied.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# host pattern -> ATS name. Order matters: first match wins.
_HOST_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(^|\.)(job-boards|boards)(\.eu)?\.greenhouse\.io$", "greenhouse"),
    (r"(^|\.)greenhouse\.io$", "greenhouse"),
    (r"(^|\.)jobs(\.eu)?\.lever\.co$", "lever"),
    (r"(^|\.)lever\.co$", "lever"),
    (r"(^|\.)myworkdayjobs\.com$", "workday"),
    (r"(^|\.)myworkdaysite\.com$", "workday"),
    (r"(^|\.)icims\.com$", "icims"),
    (r"(^|\.)taleo\.net$", "taleo"),
    (r"(^|\.)smartrecruiters\.com$", "smartrecruiters"),
    (r"(^|\.)ashbyhq\.com$", "ashby"),
    (r"(^|\.)workable\.com$", "workable"),
    (r"(^|\.)jobvite\.com$", "jobvite"),
    (r"(^|\.)bamboohr\.com$", "bamboohr"),
    (r"(^|\.)paylocity\.com$", "paylocity"),
    (r"(^|\.)dayforcehcm\.com$", "dayforce"),
)

# ATS we can drive end-to-end today. Everything else is detected (so the
# report can say what it was) but parked instead of attempted.
SUPPORTED = ("greenhouse", "lever")


def detect_ats(url: str) -> str:
    """Return the ATS name for an apply URL, or "" when unrecognized."""
    host = urlsplit(url.strip()).hostname or ""
    host = host.lower().removeprefix("www.")
    for pattern, name in _HOST_PATTERNS:
        if re.search(pattern, host):
            return name
    return ""


def is_supported(url: str) -> bool:
    return detect_ats(url) in SUPPORTED


def adapter_for(url: str):
    """Return an adapter instance for `url`, or None when unsupported."""
    name = detect_ats(url)
    if name == "greenhouse":
        from .greenhouse import GreenhouseAdapter

        return GreenhouseAdapter()
    if name == "lever":
        from .lever import LeverAdapter

        return LeverAdapter()
    return None
