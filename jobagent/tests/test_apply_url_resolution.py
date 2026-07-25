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
