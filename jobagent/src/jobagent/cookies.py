"""Parse browser cookie exports (Cookie-Editor / EditThisCookie JSON format)."""

from __future__ import annotations

import json

_SAMESITE = {
    "no_restriction": "None",
    "none": "None",
    "lax": "Lax",
    "strict": "Strict",
    "unspecified": "Lax",
}


def parse_cookie_export(text: str, domain_filter: str = "linkedin.com") -> list[dict]:
    """Convert a JSON cookie export into Playwright add_cookies() format,
    keeping only cookies for the given domain."""
    data = json.loads(text)
    if isinstance(data, dict) and "cookies" in data:
        data = data["cookies"]
    cookies: list[dict] = []
    for c in data:
        domain = str(c.get("domain", ""))
        if domain_filter not in domain:
            continue
        cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": domain,
            "path": c.get("path") or "/",
            "secure": bool(c.get("secure", False)),
            "httpOnly": bool(c.get("httpOnly", False)),
            "sameSite": _SAMESITE.get(str(c.get("sameSite", "")).lower(), "Lax"),
        }
        expires = c.get("expirationDate") or c.get("expires")
        if expires:
            cookie["expires"] = int(float(expires))
        cookies.append(cookie)
    return cookies
