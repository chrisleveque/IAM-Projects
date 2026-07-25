"""Finding the employer's apply URL behind LinkedIn's apply modal.

Real failure this covers: every job reported
    BLOCKED · could not find an external apply link
because clicking Apply opens LinkedIn's "you're applying on the company's
website" dialog rather than a new tab, so waiting for a popup timed out.
"""

from __future__ import annotations

import pytest

from jobagent.apply.auto import (extract_company_apply_url, is_offsite,
                                 resolve_apply_url)
from jobagent.store import Job

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed").sync_playwright


def _launch(pw):
    from pathlib import Path

    try:
        return pw.chromium.launch(args=["--no-sandbox"])
    except Exception:
        pass
    for candidate in sorted(Path("/opt/pw-browsers").glob(
            "chromium-*/chrome-linux/chrome")):
        try:
            return pw.chromium.launch(args=["--no-sandbox"],
                                      executable_path=str(candidate))
        except Exception:
            continue
    pytest.skip("no usable Chromium build for Playwright")


# --- pure extraction -------------------------------------------------------

def test_extracts_company_apply_url_from_embedded_json():
    html = ('<html><body><code id="bpr-guid-1">{"data":{"companyApplyUrl":'
            '"https://boards.greenhouse.io/acme/jobs/4123456","title":"x"}}'
            '</code></body></html>')
    assert extract_company_apply_url(html) == \
        "https://boards.greenhouse.io/acme/jobs/4123456"


def test_extracts_url_with_json_and_html_escaping():
    """LinkedIn escapes slashes as \\u002F and ampersands as &amp;."""
    html = (r'{"companyApplyUrl":"https://jobs.lever.co/acme'
            r'/abc-123?src=linkedin&amp;lever-source=LinkedIn"}')
    assert extract_company_apply_url(html) == \
        "https://jobs.lever.co/acme/abc-123?src=linkedin&lever-source=LinkedIn"


def test_ignores_linkedin_internal_urls():
    html = ('{"applyUrl":"https://www.linkedin.com/jobs/view/123/apply",'
            '"companyApplyUrl":"https://acme.wd1.myworkdayjobs.com/job/R-9"}')
    assert extract_company_apply_url(html) == \
        "https://acme.wd1.myworkdayjobs.com/job/R-9"


def test_returns_empty_when_no_apply_url_present():
    assert extract_company_apply_url("<html><body>no json here</body></html>") == ""
    assert extract_company_apply_url("") == ""


def test_is_offsite_rejects_aggregators_and_subdomains():
    assert not is_offsite("https://www.linkedin.com/jobs/view/1")
    assert not is_offsite("https://uk.indeed.com/viewjob?jk=1")
    assert not is_offsite("https://static.licdn.com/x.js")
    assert is_offsite("https://boards.greenhouse.io/acme/jobs/1")
    assert is_offsite("https://careers.acme.com/apply")
    # a host merely ending in the same letters must not be treated as internal
    assert is_offsite("https://notlinkedin.com/jobs/1")


# --- browser flows ---------------------------------------------------------

class FakeSession:
    def __init__(self, page):
        self.page = page


POSTING_WITH_JSON = """
<!doctype html><html><body>
<h1>Security Engineer</h1>
<code>{"companyApplyUrl":"https://boards.greenhouse.io/acme/jobs/999"}</code>
<button class="jobs-apply-button">Apply</button>
</body></html>
"""

# Apply opens a modal whose link is built only on click, so the URL cannot be
# found in the initial DOM — the click path is the only way through.
POSTING_WITH_MODAL = """
<!doctype html><html><body>
<h1>Security Engineer</h1>
<button class="jobs-apply-button" onclick="showModal()">Apply</button>
<div id="host"></div>
<script>
function showModal(){
  document.getElementById('host').innerHTML =
    '<div role="dialog"><h2>You are applying on the company website</h2>' +
    '<a href="https://jobs.lever.co/acme/uuid-77" target="_blank">Continue</a>' +
    '</div>';
}
</script>
</body></html>
"""

# No embedded JSON, no modal — the apply button is a plain offsite link.
POSTING_WITH_PLAIN_LINK = """
<!doctype html><html><body>
<a class="jobs-apply-button" href="https://boards.greenhouse.io/acme/jobs/55">
  Apply now</a>
</body></html>
"""

POSTING_WITH_NOTHING = """
<!doctype html><html><body><h1>Job</h1>
<button class="jobs-apply-button">Apply</button></body></html>
"""


def run_resolver(html: str, tmp_path, debug_dir=None) -> str:
    posting = tmp_path / "posting.html"
    posting.write_text(html, encoding="utf-8")
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        job = Job(url=posting.as_uri(), source="linkedin")
        try:
            return resolve_apply_url(FakeSession(page), job,
                                     debug_dir=debug_dir)
        finally:
            browser.close()


def test_resolves_from_embedded_json_without_clicking(tmp_path):
    assert run_resolver(POSTING_WITH_JSON, tmp_path) == \
        "https://boards.greenhouse.io/acme/jobs/999"


def test_resolves_through_the_apply_modal(tmp_path):
    """The regression: Apply opens a dialog, not a tab."""
    assert run_resolver(POSTING_WITH_MODAL, tmp_path) == \
        "https://jobs.lever.co/acme/uuid-77"


def test_resolves_a_plain_offsite_apply_link(tmp_path):
    assert run_resolver(POSTING_WITH_PLAIN_LINK, tmp_path) == \
        "https://boards.greenhouse.io/acme/jobs/55"


def test_unresolvable_posting_saves_diagnostics(tmp_path):
    debug_dir = tmp_path / "dbg"
    assert run_resolver(POSTING_WITH_NOTHING, tmp_path, debug_dir) == ""
    assert (debug_dir / "posting.html").exists()
    assert (debug_dir / "posting.png").exists()


def test_known_apply_url_short_circuits(tmp_path):
    """A resolved URL is stored on the job and never re-discovered."""
    job = Job(url="https://www.linkedin.com/jobs/view/1", source="linkedin",
              apply_url="https://jobs.lever.co/acme/known")

    class ExplodingPage:
        def goto(self, *a, **k):
            raise AssertionError("should not open a browser at all")

    assert resolve_apply_url(FakeSession(ExplodingPage()), job) == \
        "https://jobs.lever.co/acme/known"


def test_ats_url_in_tracker_is_used_directly():
    job = Job(url="https://boards.greenhouse.io/acme/jobs/7", source="linkedin")

    class ExplodingPage:
        def goto(self, *a, **k):
            raise AssertionError("should not open a browser at all")

    assert resolve_apply_url(FakeSession(ExplodingPage()), job) == \
        "https://boards.greenhouse.io/acme/jobs/7"


# --- diagnosis report ------------------------------------------------------

def test_describe_apply_markup_reports_structure_not_content():
    from jobagent.apply.auto import describe_apply_markup

    html = ('<html><body>'
            '<p>Chris Leveque applied to this job on Tuesday</p>'
            '<code>{"companyApplyUrl":"https://boards.greenhouse.io/acme/jobs/1",'
            '"applyUrl":"https://www.linkedin.com/jobs/view/1/apply"}</code>'
            '<button class="jobs-apply-button artdeco-button">Apply</button>'
            '<div role="dialog"><a href="https://jobs.lever.co/x/1">Continue</a></div>'
            '</body></html>')
    report = describe_apply_markup(html)

    assert "boards.greenhouse.io" in report and "OFFSITE" in report
    assert "ats=greenhouse" in report
    assert "www.linkedin.com" in report and "internal" in report
    assert "jobs-apply-button" in report
    assert "role=dialog" in report
    assert "resolver would extract: https://boards.greenhouse.io/acme/jobs/1" in report
    # page text must not leak into something the user will paste publicly
    assert "Chris Leveque" not in report
    assert "applied to this job" not in report


def test_describe_apply_markup_on_a_posting_with_no_apply_data():
    from jobagent.apply.auto import describe_apply_markup

    report = describe_apply_markup("<html><body><h1>Job</h1></body></html>")
    assert "no *ApplyUrl* keys found" in report
    assert "resolver would extract: (nothing)" in report


# --- signed-out detection --------------------------------------------------

def test_detects_linkedin_guest_page():
    """Shape of the real failing posting: hashed classes, no applyUrl JSON,
    no jobs-apply-button, apply links pointing back at linkedin.com."""
    from jobagent.apply.auto import looks_logged_out

    guest = ('<html><body><nav><a class="nav__button-secondary">Join now</a>'
             '<a class="nav__button-secondary">Sign in</a></nav>'
             '<a class="b1c0ad9e b0b671a8" href="https://www.linkedin.com/'
             'authwall?sessionRedirect=x">Apply</a></body></html>')
    assert looks_logged_out(guest)


def test_authenticated_page_is_not_flagged_signed_out():
    from jobagent.apply.auto import looks_logged_out

    signed_in = ('<html><body><div class="global-nav__me"></div>'
                 '<button class="jobs-apply-button">Apply</button>'
                 '<a href="/login">sign in to view more</a></body></html>')
    assert not looks_logged_out(signed_in)


def test_page_with_apply_url_json_is_never_signed_out():
    from jobagent.apply.auto import looks_logged_out

    # authenticated markers win even if guest wording appears somewhere
    html = ('{"companyApplyUrl":"https://boards.greenhouse.io/a/jobs/1"}'
            '<a>Join LinkedIn</a>')
    assert not looks_logged_out(html)


def test_page_with_no_signal_either_way_is_treated_as_signed_out():
    """A page proving nothing must not be assumed authenticated.

    Reporting 'looks signed in' for a page that merely lacked guest markers
    is what misdirected an earlier diagnosis — LinkedIn's guest page uses
    hashed classes and no fixed wording, so 'unknown' is the common case.
    """
    from jobagent.apply.auto import looks_logged_out, session_state

    assert session_state("<html><body><h1>Some job</h1></body></html>") == "unknown"
    assert looks_logged_out("<html><body><h1>Some job</h1></body></html>")
    assert looks_logged_out("")


def test_session_state_is_three_valued():
    from jobagent.apply.auto import session_state

    assert session_state('<button class="jobs-apply-button">Apply</button>') \
        == "signed-in"
    assert session_state('<a href="/authwall">x</a>') == "signed-out"
    assert session_state("<p>nothing conclusive</p>") == "unknown"


def test_debug_report_calls_out_a_signed_out_page():
    from jobagent.apply.auto import describe_apply_markup

    report = describe_apply_markup(
        '<html><body><a class="nav__button-secondary">Join now</a>'
        '<a href="https://www.linkedin.com/authwall">Apply</a></body></html>')
    assert "SIGNED OUT" in report
    assert "re-import your cookie" in report


def test_debug_report_says_signed_in_for_a_real_posting():
    from jobagent.apply.auto import describe_apply_markup

    report = describe_apply_markup(
        '<code>{"companyApplyUrl":"https://jobs.lever.co/a/1"}</code>'
        '<button class="jobs-apply-button">Apply</button>')
    assert "signed in (authenticated markers present)" in report


POSTING_SIGNED_OUT = """
<!doctype html><html><body>
<nav><a class="nav__button-secondary">Join now</a>
     <a class="nav__button-secondary">Sign in</a></nav>
<h1>Security Engineer</h1>
<a class="b1c0ad9e b0b671a8" href="https://www.linkedin.com/authwall"
   onclick="stall()">Apply</a>
<script>
// a signed-out Apply control that opens nothing — the stall being avoided
function stall(){ }
</script>
</body></html>
"""


def test_signed_out_posting_returns_fast_without_clicking(tmp_path):
    """The click path costs a popup timeout per attempt and can never succeed
    on the guest page, so it must be skipped entirely."""
    import time

    started = time.monotonic()
    assert run_resolver(POSTING_SIGNED_OUT, tmp_path) == ""
    elapsed = time.monotonic() - started
    # one popup timeout alone would be ~5s; the whole call should beat that
    assert elapsed < 5, f"took {elapsed:.1f}s — the click path was not skipped"


# --- closed postings -------------------------------------------------------

def test_detects_a_closed_posting():
    from jobagent.apply.auto import posting_is_closed

    for wording in ("No longer accepting applications",
                    "This job is no longer available",
                    "Applications are closed",
                    "This job posting has expired"):
        assert posting_is_closed(f"<body><p>{wording}</p></body>"), wording


def test_open_posting_is_not_flagged_closed():
    from jobagent.apply.auto import posting_is_closed

    assert not posting_is_closed("<body>Apply now — we are hiring!</body>")
    assert not posting_is_closed("")


POSTING_CLOSED = """
<!doctype html><html><body>
<div class="global-nav__me"></div>
<h1>Security Engineer</h1>
<p>No longer accepting applications</p>
</body></html>
"""


def test_closed_posting_leaves_the_queue(tmp_path):
    """A year-old saved job shouldn't keep coming back as 'blocked'."""
    from jobagent.ats.base import CLOSED

    posting = tmp_path / "closed.html"
    posting.write_text(POSTING_CLOSED, encoding="utf-8")

    from types import SimpleNamespace

    from jobagent.apply.auto import apply_to_job
    from jobagent.store import Store

    store = Store(tmp_path / "t.db")
    job = Job(url=posting.as_uri(), source="linkedin", title="T", company="C")
    store.upsert_job(job)
    cfg = SimpleNamespace(output_dir=tmp_path / "out")

    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        try:
            report = apply_to_job(FakeSession(page), job, cfg, store, None, "",
                                  {}, False, _QuietConsole())
        finally:
            browser.close()

    assert report.outcome == CLOSED
    assert "no longer accepting" in report.note


class _QuietConsole:
    def print(self, *a, **k):
        pass


# --- richer diagnostics ----------------------------------------------------

def test_debug_report_lists_offsite_hosts():
    from jobagent.apply.auto import describe_apply_markup

    report = describe_apply_markup(
        '<div class="global-nav__me"></div>'
        '<a href="https://acme.wd5.myworkdayjobs.com/en-US/careers/job/R-1">Apply</a>'
        '<a href="https://acme.wd5.myworkdayjobs.com/en-US/careers/job/R-1">Again</a>'
        '<a href="https://www.linkedin.com/feed">Feed</a>')
    assert "acme.wd5.myworkdayjobs.com" in report
    assert "ats=workday" in report
    assert "x2" in report                      # counted, not just listed
    assert "www.linkedin.com" not in report.split("distinct offsite")[1]


def test_debug_report_flags_an_unknown_session_honestly():
    """The exact shape of the posting that misled the earlier diagnosis:
    hashed classes, no apply JSON, links only back to linkedin.com."""
    from jobagent.apply.auto import describe_apply_markup

    report = describe_apply_markup(
        '<a class="b1c0ad9e b0b671a8 _95e2f203" href="https://www.linkedin.com/x">'
        'Apply</a><a class="ff123a63 _440408d7" href="https://www.linkedin.com/y">'
        'Apply</a>')
    assert "UNKNOWN" in report
    assert "most likely signed out" in report
    assert "distinct offsite link hosts: 0" in report
