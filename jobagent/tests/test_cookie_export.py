import json

from jobagent.cookies import parse_cookie_export

EXPORT = [
    {"name": "li_at", "value": "AQE...", "domain": ".linkedin.com", "path": "/",
     "secure": True, "httpOnly": True, "sameSite": "no_restriction",
     "expirationDate": 1785000000.123},
    {"name": "JSESSIONID", "value": "ajax:123", "domain": ".www.linkedin.com",
     "path": "/", "secure": True, "httpOnly": False, "sameSite": "unspecified"},
    {"name": "bcookie", "value": "v=2&...", "domain": ".linkedin.com", "path": "/",
     "secure": True, "sameSite": "none", "expirationDate": 1790000000},
    {"name": "unrelated", "value": "x", "domain": ".google.com", "path": "/"},
]


def test_filters_to_linkedin_and_maps_fields():
    cookies = parse_cookie_export(json.dumps(EXPORT))
    names = {c["name"] for c in cookies}
    assert names == {"li_at", "JSESSIONID", "bcookie"}
    li_at = next(c for c in cookies if c["name"] == "li_at")
    assert li_at["sameSite"] == "None"
    assert li_at["expires"] == 1785000000
    assert li_at["httpOnly"] is True
    jsession = next(c for c in cookies if c["name"] == "JSESSIONID")
    assert jsession["sameSite"] == "Lax"  # 'unspecified' maps to Lax
    assert "expires" not in jsession      # session cookie keeps no expiry


def test_accepts_wrapped_export_format():
    wrapped = {"cookies": EXPORT}
    assert len(parse_cookie_export(json.dumps(wrapped))) == 3


def test_empty_for_other_domains():
    assert parse_cookie_export(json.dumps([EXPORT[3]])) == []
