"""End-to-end adapter tests against a local Greenhouse-shaped form.

These exercise the real field-extraction JavaScript in a real browser, which
unit tests can't cover. Skipped when Playwright/Chromium isn't installed.
"""

from __future__ import annotations

import pytest

from jobagent.ai.answerer import AnswerSet, Answerer
from jobagent.ats.base import BLOCKED, FILLED, SUBMITTED, ApplyContext
from jobagent.ats.fields import fill_field, read_fields
from jobagent.ats.greenhouse import GreenhouseAdapter
from jobagent.store import Store

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed").sync_playwright

FORM_HTML = """
<!doctype html><html><body>
<h1>Senior IAM Engineer</h1>
<form id="application_form" action="#" onsubmit="submitted(event)">
  <div class="field">
    <label for="first_name">First Name *</label>
    <input type="text" id="first_name" name="first_name" required>
  </div>
  <div class="field">
    <label for="last_name">Last Name *</label>
    <input type="text" id="last_name" name="last_name" required>
  </div>
  <div class="field">
    <label for="email">Email *</label>
    <input type="text" id="email" name="email" required>
  </div>
  <div class="field">
    <label for="phone">Phone</label>
    <input type="text" id="phone" name="phone">
  </div>
  <div class="field">
    <label for="resume">Resume/CV *</label>
    <input type="file" id="resume" name="resume" required>
  </div>
  <div class="field">
    <label for="cover_letter">Cover Letter</label>
    <input type="file" id="cover_letter" name="cover_letter">
  </div>
  <div class="field">
    <label for="linkedin">LinkedIn Profile</label>
    <input type="text" id="linkedin" name="linkedin">
  </div>
  <div class="field">
    <label for="years">Years of IAM experience *</label>
    <select id="years" name="years" required>
      <option value=""></option>
      <option>0-2 years</option>
      <option>3-5 years</option>
      <option>6+ years</option>
    </select>
  </div>
  <div class="field">
    <label for="why">Why do you want to work here? *</label>
    <textarea id="why" name="why" required></textarea>
  </div>
  <fieldset class="field">
    <legend>Will you now or in the future require visa sponsorship? *</legend>
    <label><input type="radio" name="sponsor" value="Yes" required> Yes</label>
    <label><input type="radio" name="sponsor" value="No"> No</label>
  </fieldset>
  <div class="field">
    <label for="gender">Gender</label>
    <select id="gender" name="gender">
      <option value=""></option>
      <option>Male</option>
      <option>Female</option>
      <option>Decline to self-identify</option>
    </select>
  </div>
  <input type="submit" id="submit_app" value="Submit Application">
</form>
<script>
function submitted(e){
  e.preventDefault();
  document.body.innerHTML = "<h1>Thank you for applying</h1>";
}
</script>
</body></html>
"""


class StubAI:
    """Answers only what a real profile would support."""

    def __init__(self, by_question: dict[str, str]):
        self.by_question = by_question

    def parse(self, system, user, output_model, max_tokens=None):
        answers = []
        for line in user.splitlines():
            if not line.startswith("id="):
                continue
            idx = int(line.split()[0].removeprefix("id="))
            question = line.split("question=", 1)[1].split("  options=")[0].strip("'\" ")
            match = next((v for k, v in self.by_question.items() if k in question), None)
            answers.append({"id": idx, "value": match or "", "known": bool(match)})
        return AnswerSet.model_validate({"answers": answers})


ANSWERS_YAML = {
    "contact": {"full_name": "Chris Leveque", "email": "c@example.com",
                "phone": "(555) 555-5555", "city": "Boca Raton, FL",
                "linkedin": "https://linkedin.com/in/chris"},
    "work_authorization": {"authorized_to_work_us": True,
                           "require_sponsorship": False},
    "years_experience": {"default": 5},
}


def _launch(pw):
    """Launch Chromium, falling back to a pre-installed build whose version
    doesn't match this Playwright package (common in CI images)."""
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


@pytest.fixture()
def page(tmp_path):
    form = tmp_path / "job.html"
    form.write_text(FORM_HTML, encoding="utf-8")
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        page.goto(form.as_uri())
        yield page
        browser.close()


def make_ctx(tmp_path, store, submit: bool, ai=None) -> ApplyContext:
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake")
    cover = tmp_path / "cover_letter.pdf"
    cover.write_bytes(b"%PDF-1.4 fake")
    answerer = Answerer(ANSWERS_YAML, store=store,
                        ai=ai if ai is not None else StubAI({
                            "Why do you want to work here": "I've spent five years in IAM.",
                            "Years of IAM experience": "3-5 years",
                        }),
                        profile="Chris Leveque, 5 years IAM.")
    return ApplyContext(resume_file=resume, cover_letter_file=cover,
                        answerer=answerer, screenshot_dir=tmp_path / "shots",
                        submit=submit)


def test_read_fields_finds_every_question(page):
    fields = read_fields(page, "#application_form")
    by_label = {f.label: f for f in fields}
    assert "First Name *" in by_label
    assert by_label["First Name *"].required
    assert by_label["Resume/CV *"].kind == "file"
    assert by_label["Why do you want to work here? *"].kind == "textarea"

    years = by_label["Years of IAM experience *"]
    assert years.kind == "select"
    assert "3-5 years" in years.options

    # the radio group collapses into ONE question with two clickable options
    sponsor = next(f for f in fields if "sponsorship" in f.label.lower())
    assert sponsor.kind == "radio"
    assert sorted(o.strip() for o in sponsor.options) == ["No", "Yes"]
    assert len(sponsor.option_idx) == 2


def test_fill_field_sets_text_select_and_radio(page):
    fields = {f.label: f for f in read_fields(page, "#application_form")}
    assert fill_field(page, fields["First Name *"], "Chris")
    assert page.input_value("#first_name") == "Chris"

    assert fill_field(page, fields["Years of IAM experience *"], "3-5 years")
    assert page.input_value("#years") == "3-5 years"

    sponsor = next(f for f in fields.values() if "sponsorship" in f.label.lower())
    assert fill_field(page, sponsor, "No")
    assert page.is_checked("input[name='sponsor'][value='No']")


def test_dry_run_fills_everything_but_does_not_submit(tmp_path, page):
    store = Store(tmp_path / "t.db")
    ctx = make_ctx(tmp_path, store, submit=False)
    report = GreenhouseAdapter().apply(page, "https://boards.greenhouse.io/a/jobs/1", ctx)

    assert report.outcome == FILLED
    assert report.resume_attached
    # sponsorship came from answers.yaml, not the model
    assert page.is_checked("input[name='sponsor'][value='No']")
    # demographic question declined rather than guessed
    assert page.input_value("#gender") == "Decline to self-identify"
    assert page.input_value("#first_name") == "Chris"
    assert page.input_value("#email") == "c@example.com"
    # the form is untouched by any submit
    assert "Thank you for applying" not in page.inner_text("body")
    assert (tmp_path / "shots" / "filled.png").exists()


def test_submit_mode_submits_and_detects_confirmation(tmp_path, page):
    store = Store(tmp_path / "t.db")
    ctx = make_ctx(tmp_path, store, submit=True)
    report = GreenhouseAdapter().apply(page, "https://boards.greenhouse.io/a/jobs/1", ctx)

    assert report.outcome == SUBMITTED, report.note
    assert "Thank you for applying" in page.inner_text("body")


def test_unanswerable_required_question_blocks_submission(tmp_path, page):
    """The whole safety story: a required question the AI can't answer must
    stop the submission, even in --submit mode."""
    store = Store(tmp_path / "t.db")
    ctx = make_ctx(tmp_path, store, submit=True,
                   ai=StubAI({}))  # model can answer nothing
    report = GreenhouseAdapter().apply(page, "https://boards.greenhouse.io/a/jobs/1", ctx)

    assert report.outcome == BLOCKED
    assert "required question" in report.note
    assert "Thank you for applying" not in page.inner_text("body")


def test_bot_wall_blocks_before_touching_the_form(tmp_path, page):
    page.set_content("<body><div class='g-recaptcha'></div>"
                     "<p>Please verify you are human</p></body>")
    store = Store(tmp_path / "t.db")
    report = GreenhouseAdapter().apply(page, "https://boards.greenhouse.io/a/jobs/1",
                                       make_ctx(tmp_path, store, submit=True))
    assert report.outcome == BLOCKED
    assert "bot wall" in report.note


def test_missing_resume_field_blocks(tmp_path, page):
    page.set_content("<form id='application_form'>"
                     "<label for='n'>Full name *</label>"
                     "<input id='n' required></form>")
    store = Store(tmp_path / "t.db")
    report = GreenhouseAdapter().apply(page, "https://boards.greenhouse.io/a/jobs/1",
                                       make_ctx(tmp_path, store, submit=True))
    assert report.outcome == BLOCKED
    assert "resume" in report.note


LEVER_HTML = """
<!doctype html><html><body>
<form>
  <input type="text" name="name" placeholder="Full name" required>
  <input type="text" name="email" placeholder="Email" required>
  <input type="file" name="resume" required>
  <input type="text" name="urls[LinkedIn]" placeholder="LinkedIn URL">
  <button id="btn-submit" type="submit">Submit application</button>
</form>
<script>
document.querySelector('form').addEventListener('submit', e => {
  e.preventDefault();
  document.body.innerHTML = "<h1>Thanks for applying</h1>";
});
</script>
</body></html>
"""


def test_lever_form_uses_placeholders_as_questions(tmp_path):
    """Lever labels its inputs with placeholders only — extraction must still
    produce usable questions."""
    from jobagent.ats.lever import LeverAdapter

    form = tmp_path / "lever.html"
    form.write_text(LEVER_HTML, encoding="utf-8")
    store = Store(tmp_path / "t.db")
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        page.goto(form.as_uri())
        fields = read_fields(page, "form")
        labels = {f.label for f in fields}
        assert "Full name" in labels and "Email" in labels

        ctx = make_ctx(tmp_path, store, submit=True, ai=StubAI({}))
        report = LeverAdapter().apply(page, "https://jobs.lever.co/a/uuid", ctx)
        # name/email/resume all resolvable from answers.yaml -> submits
        assert report.outcome == SUBMITTED, report.note
        assert "Thanks for applying" in page.inner_text("body")
        browser.close()
