"""Workday adapter driven through a local multi-page fixture that mimics a
tenant's automation ids, account gate, and validation.

Covers the scenario matrix the adapter promises: dry run stops before submit,
account creation only in --submit mode and vaulted first, sign-in with an
existing account, sign-in rejection parked, unanswerable required question
parked, CAPTCHA parked, and already-applied recognized.
"""

from __future__ import annotations

import pytest

from jobagent.ai.answerer import AnswerSet, Answerer
from jobagent.ats.base import BLOCKED, FILLED, SUBMITTED, ApplyContext
from jobagent.ats.workday import WorkdayAdapter
from jobagent.store import Store
from jobagent.vault import Vault

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


D = "data-automation-id"

# A self-contained SPA: posting -> auth (sign-in or create) -> two form pages
# -> review -> confirmation. State lives in window.state; buttons advance it.
TENANT = """
<!doctype html><html><body>
<div id="app"></div>
<script>
window.state = INITIAL_STATE;
window.accountExists = ACCOUNT_EXISTS;
const app = () => document.getElementById('app');
function render() {
  const s = window.state;
  if (s === 'posting') {
    app().innerHTML = "<h1>Security Engineer</h1>" +
      "<a data-automation-id='adventureButton' onclick='go(\\"auth\\")'>Apply</a>";
  } else if (s === 'auth') {
    app().innerHTML =
      "<input data-automation-id='email'>" +
      "<input data-automation-id='password' type='password'>" +
      "<input data-automation-id='verifyPassword' type='password'>" +
      "<input data-automation-id='createAccountCheckbox' type='checkbox'>" +
      "<button data-automation-id='createAccountSubmitButton' onclick='submitAuth(true)'>Create Account</button>" +
      "<button data-automation-id='signInSubmitButton' onclick='submitAuth(false)'>Sign In</button>";
  } else if (s === 'form1') {
    app().innerHTML =
      "<label for='fn'>First Name</label><input id='fn' data-automation-id='legalNameSection_firstName' required>" +
      "<label for='ln'>Last Name</label><input id='ln' data-automation-id='legalNameSection_lastName' required>" +
      "<input type='file' data-automation-id='resumeUpload'>" +
      "<div data-automation-id='errorBanner' style='display:none'></div>" +
      "<button data-automation-id='pageFooterNextButton' onclick='next1()'>Save and Continue</button>";
  } else if (s === 'form2') {
    app().innerHTML =
      "<label for='auth'>Are you legally authorized to work in the US?</label>" +
      "<select id='auth' data-automation-id='workAuth' required>" +
        "<option value=''></option><option>Yes</option><option>No</option></select>" +
      "<button data-automation-id='pageFooterNextButton' onclick='state=\\"review\\";render()'>Next</button>";
  } else if (s === 'review') {
    app().innerHTML = "<h2>Review</h2><p>Please review and submit.</p>" +
      "<button data-automation-id='pageFooterNextButton' onclick='state=\\"done\\";render()'>Submit</button>";
  } else if (s === 'done') {
    app().innerHTML = "<h1>Application submitted</h1><p>Thanks for applying.</p>";
  } else if (s === 'already') {
    app().innerHTML = "<h1>You have already applied to this job</h1>";
  } else if (s === 'captcha') {
    app().innerHTML = "<div class='g-recaptcha'></div><p>verify you are human</p>";
  }
}
function go(s){ window.state = s; render(); }
function submitAuth(creating){
  const email = document.querySelector("[data-automation-id=email]").value;
  const pw = document.querySelector("[data-automation-id=password]").value;
  window.lastEmail = email; window.lastPw = pw; window.lastCreating = creating;
  if (creating) {
    const verify = document.querySelector("[data-automation-id=verifyPassword]").value;
    if (pw !== verify) { showErr("Passwords do not match"); return; }
    window.accountExists = true; window.state = 'form1'; render(); return;
  }
  // sign in
  if (email === window.goodEmail && pw === window.goodPw) {
    window.state = 'form1'; render();
  } else {
    showErr("Invalid email or password");
  }
}
function showErr(msg){
  window.state = window.state; render();
  const b = document.querySelector("[data-automation-id=errorBanner]") ||
            (()=>{ const d=document.createElement('div');
                   d.setAttribute('data-automation-id','errorBanner');
                   app().appendChild(d); return d; })();
  b.style.display='block'; b.innerText = msg;
}
function next1(){
  const fn = document.getElementById('fn').value;
  if (!fn) { showErr('First Name is required'); return; }
  window.state='form2'; render();
}
render();
</script>
</body></html>
"""


def build_page(pw, tmp_path, initial="posting", account_exists="false",
               good=("", "")):
    html = (TENANT.replace("INITIAL_STATE", f"'{initial}'")
                  .replace("ACCOUNT_EXISTS", account_exists))
    f = tmp_path / "tenant.html"
    f.write_text(html, encoding="utf-8")
    browser = _launch(pw)
    page = browser.new_page()
    page.goto(f.as_uri())
    page.evaluate(f"window.goodEmail = {good[0]!r}; window.goodPw = {good[1]!r};")
    return browser, page


class StubAI:
    def __init__(self, by_question):
        self.by_question = by_question

    def parse(self, system, user, output_model, max_tokens=None):
        answers = []
        for line in user.splitlines():
            if not line.startswith("id="):
                continue
            idx = int(line.split()[0].removeprefix("id="))
            q = line.split("question=", 1)[1].split("  options=")[0].strip("'\" ")
            v = next((val for k, val in self.by_question.items() if k in q), None)
            answers.append({"id": idx, "value": v or "", "known": bool(v)})
        return AnswerSet.model_validate({"answers": answers})


ANSWERS = {
    "contact": {"full_name": "Chris Leveque", "email": "chris@example.com"},
    "work_authorization": {"authorized_to_work_us": True,
                           "require_sponsorship": False},
}


def make_ctx(tmp_path, submit, vault=None, email="chris@example.com"):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 x")
    store = Store(tmp_path / "t.db")
    answerer = Answerer(ANSWERS, store=store, ai=StubAI({}),
                        profile="Chris Leveque")
    return ApplyContext(resume_file=resume, answerer=answerer,
                        screenshot_dir=tmp_path / "shots", submit=submit,
                        vault=vault, account_email=email)


URL = "https://acme.wd1.myworkdayjobs.com/careers/job/Security-Engineer"


def test_dry_run_with_existing_account_stops_at_review(tmp_path):
    vault = Vault(tmp_path / "vault.enc")
    vault.create("acme.wd1.myworkdayjobs.com", "chris@example.com")
    cred = vault.get("acme.wd1.myworkdayjobs.com")
    with sync_playwright() as pw:
        browser, page = build_page(pw, tmp_path, "posting", "true",
                                   good=(cred.email, cred.password))
        try:
            report = WorkdayAdapter().apply(page, URL,
                                            make_ctx(tmp_path, submit=False, vault=vault))
        finally:
            browser.close()
    assert report.outcome == FILLED, report.note
    assert "final page" in report.note
    assert report.resume_attached


def test_submit_with_existing_account_reaches_confirmation(tmp_path):
    vault = Vault(tmp_path / "vault.enc")
    vault.create("acme.wd1.myworkdayjobs.com", "chris@example.com")
    cred = vault.get("acme.wd1.myworkdayjobs.com")
    with sync_playwright() as pw:
        browser, page = build_page(pw, tmp_path, "posting", "true",
                                   good=(cred.email, cred.password))
        try:
            report = WorkdayAdapter().apply(page, URL,
                                            make_ctx(tmp_path, submit=True, vault=vault))
        finally:
            browser.close()
    assert report.outcome == SUBMITTED, report.note


def test_account_creation_only_happens_in_submit_mode(tmp_path):
    vault = Vault(tmp_path / "vault.enc")
    with sync_playwright() as pw:
        browser, page = build_page(pw, tmp_path, "auth", "false")
        try:
            report = WorkdayAdapter().apply(page, URL,
                                            make_ctx(tmp_path, submit=False, vault=vault))
        finally:
            browser.close()
    # a dry run on an account-gated tenant is "ready, waiting for --submit",
    # NOT blocked — so a plain --submit run picks it back up
    assert report.outcome == FILLED
    assert "--submit" in report.note
    # nothing was vaulted during a dry run
    assert vault.get("acme.wd1.myworkdayjobs.com") is None


def test_submit_creates_and_vaults_the_account(tmp_path):
    vault = Vault(tmp_path / "vault.enc")
    with sync_playwright() as pw:
        browser, page = build_page(pw, tmp_path, "auth", "false")
        try:
            report = WorkdayAdapter().apply(page, URL,
                                            make_ctx(tmp_path, submit=True, vault=vault))
            created_pw = page.evaluate("window.lastPw")
            was_creating = page.evaluate("window.lastCreating")
        finally:
            browser.close()
    assert report.outcome == SUBMITTED, report.note
    assert was_creating is True
    cred = vault.get("acme.wd1.myworkdayjobs.com")
    assert cred is not None
    assert cred.password == created_pw          # vaulted the real password
    assert cred.email == "chris@example.com"


def test_rejected_sign_in_is_parked_not_retried(tmp_path):
    vault = Vault(tmp_path / "vault.enc")
    vault.create("acme.wd1.myworkdayjobs.com", "chris@example.com")
    with sync_playwright() as pw:
        # tenant's real password differs from the vaulted one -> rejected
        browser, page = build_page(pw, tmp_path, "auth", "true",
                                   good=("chris@example.com", "different-pw"))
        try:
            report = WorkdayAdapter().apply(page, URL,
                                            make_ctx(tmp_path, submit=True, vault=vault))
        finally:
            browser.close()
    assert report.outcome == BLOCKED
    assert "rejected" in report.note and "lockout" in report.note


def test_captcha_is_parked(tmp_path):
    with sync_playwright() as pw:
        browser, page = build_page(pw, tmp_path, "captcha", "true")
        try:
            report = WorkdayAdapter().apply(page, URL,
                                            make_ctx(tmp_path, submit=True,
                                                     vault=Vault(tmp_path / "v.enc")))
        finally:
            browser.close()
    assert report.outcome == BLOCKED
    assert "CAPTCHA" in report.note or "bot wall" in report.note


def test_already_applied_is_reported_as_submitted(tmp_path):
    with sync_playwright() as pw:
        browser, page = build_page(pw, tmp_path, "already", "true")
        try:
            report = WorkdayAdapter().apply(page, URL,
                                            make_ctx(tmp_path, submit=True,
                                                     vault=Vault(tmp_path / "v.enc")))
        finally:
            browser.close()
    assert report.outcome == SUBMITTED
    assert "already on file" in report.note


def test_unanswerable_required_question_blocks(tmp_path):
    # AI can't answer work authorization and it's not in answers.yaml here
    vault = Vault(tmp_path / "vault.enc")
    vault.create("acme.wd1.myworkdayjobs.com", "chris@example.com")
    cred = vault.get("acme.wd1.myworkdayjobs.com")
    store = Store(tmp_path / "t.db")
    resume = tmp_path / "r.pdf"
    resume.write_bytes(b"%PDF x")
    answerer = Answerer({"contact": {"full_name": "Chris Leveque"}},
                        store=store, ai=StubAI({}), profile="p")
    ctx = ApplyContext(resume_file=resume, answerer=answerer,
                       screenshot_dir=tmp_path / "s", submit=True, vault=vault,
                       account_email="chris@example.com")
    with sync_playwright() as pw:
        browser, page = build_page(pw, tmp_path, "posting", "true",
                                   good=(cred.email, cred.password))
        try:
            report = WorkdayAdapter().apply(page, URL, ctx)
        finally:
            browser.close()
    assert report.outcome == BLOCKED
    assert "authorized to work" in report.note.lower()
