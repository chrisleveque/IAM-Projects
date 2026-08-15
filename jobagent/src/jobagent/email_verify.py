"""Read ATS verification emails over IMAP so account creation can complete
without a human opening their inbox.

Configuration (in .env):
    JOBAGENT_EMAIL=you@gmail.com
    JOBAGENT_EMAIL_APP_PASSWORD=abcdefghijklmnop   # Gmail App Password, not
                                                   # your real password
    JOBAGENT_IMAP_HOST=imap.gmail.com              # optional, this is default

The reader only ever searches for recent messages from the ATS's domain and
extracts a verification link or one-time code — it never deletes, marks, or
sends anything.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape

VERIFYISH_SUBJECT = re.compile(
    r"verif|confirm|activate|one.?time|passcode|security code|access code", re.I)

# Links whose path suggests verification, preferred over bare links.
VERIFYISH_LINK = re.compile(r"verif|confirm|activate|token=|key=|redeem", re.I)

_LINK_RE = re.compile(r'https?://[^\s"\'<>\]\)]+')
# A standalone 4-8 digit code on its own line or after "code is/:"
_CODE_RE = re.compile(
    r"(?:code(?:\s+is)?|passcode|pin)[:\s]*([0-9]{4,8})\b|^\s*([0-9]{6})\s*$",
    re.I | re.M)


@dataclass
class Verification:
    link: str = ""
    code: str = ""
    subject: str = ""

    @property
    def found(self) -> bool:
        return bool(self.link or self.code)


def config_from_env() -> dict | None:
    """IMAP settings from .env, or None when not configured."""
    address = os.environ.get("JOBAGENT_EMAIL", "").strip()
    password = os.environ.get("JOBAGENT_EMAIL_APP_PASSWORD", "").strip()
    if not address or not password:
        return None
    return {
        "address": address,
        "password": password,
        "host": os.environ.get("JOBAGENT_IMAP_HOST", "imap.gmail.com").strip(),
    }


def extract_verification(body_text: str, body_html: str,
                         sender_hint: str = "") -> Verification:
    """Pull the verification link or one-time code out of an email body."""
    blob = f"{body_html}\n{body_text}"
    links = [unescape(l.rstrip(".,;")) for l in _LINK_RE.findall(blob)]
    # Prefer links that look like verification and (when known) match the ATS.
    def rank(link: str) -> tuple[int, int]:
        return (int(bool(VERIFYISH_LINK.search(link))),
                int(bool(sender_hint) and sender_hint.lower() in link.lower()))
    links.sort(key=rank, reverse=True)
    best_link = links[0] if links and rank(links[0]) > (0, 0) else ""

    code = ""
    match = _CODE_RE.search(body_text or "") or _CODE_RE.search(body_html or "")
    if match:
        code = next(g for g in match.groups() if g)
    return Verification(link=best_link, code=code)


def _bodies(msg) -> tuple[str, str]:
    text, html = "", ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_content()
        except Exception:
            continue
        if ctype == "text/plain":
            text += str(payload)
        else:
            html += str(payload)
    return text, html


def wait_for_verification(sender_domains: tuple[str, ...],
                          timeout_seconds: int = 180,
                          poll_seconds: int = 10,
                          config: dict | None = None,
                          console=None) -> Verification:
    """Poll the inbox for a fresh verification email from any of the domains.

    Only messages younger than ten minutes count, so an old verification mail
    from a previous signup can't be replayed into the wrong flow.
    """
    settings = config or config_from_env()
    if settings is None:
        return Verification()
    deadline = time.monotonic() + timeout_seconds
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)

    while time.monotonic() < deadline:
        found = _check_once(settings, sender_domains, cutoff)
        if found.found:
            return found
        if console is not None:
            console.print("    [dim]waiting for the verification email...[/dim]")
        time.sleep(poll_seconds)
    return Verification()


def _check_once(settings: dict, sender_domains: tuple[str, ...],
                cutoff: datetime) -> Verification:
    try:
        with imaplib.IMAP4_SSL(settings["host"]) as imap:
            imap.login(settings["address"], settings["password"])
            imap.select("INBOX", readonly=True)
            since = cutoff.strftime("%d-%b-%Y")
            candidates: list[bytes] = []
            for domain in sender_domains:
                status, data = imap.search(None, "SINCE", since, "FROM", domain)
                if status == "OK" and data and data[0]:
                    candidates.extend(data[0].split())
            for num in reversed(candidates[-20:]):  # newest first
                status, data = imap.fetch(num, "(RFC822)")
                if status != "OK" or not data or data[0] is None:
                    continue
                msg = email.message_from_bytes(
                    data[0][1], policy=email.policy.default)
                msg_date = email.utils.parsedate_to_datetime(msg.get("Date", ""))
                if msg_date is not None and msg_date < cutoff:
                    continue
                subject = str(msg.get("Subject", ""))
                if not VERIFYISH_SUBJECT.search(subject):
                    continue
                text, html = _bodies(msg)
                hint = sender_domains[0].split(".")[0] if sender_domains else ""
                found = extract_verification(text, html, hint)
                if found.found:
                    found.subject = subject
                    return found
    except Exception:
        pass  # transient IMAP failures just mean "not yet"
    return Verification()
