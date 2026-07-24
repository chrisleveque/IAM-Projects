from jobagent.ai.tailor import TailoredPackage, tailor_for_job
from jobagent.cli import _contact_from_answers
from jobagent.store import Job


def test_contact_line_includes_all_links():
    answers = {"contact": {
        "full_name": "Chris Leveque", "city": "Austin, TX",
        "phone": "(555) 555-5555", "email": "c@example.com",
        "linkedin": "https://www.linkedin.com/in/chris",
        "github": "https://github.com/chris",
        "tryhackme": "https://tryhackme.com/p/chris",
    }}
    line = _contact_from_answers(answers)
    for expected in ("Austin, TX", "(555) 555-5555", "c@example.com",
                     "linkedin.com/in/chris", "github.com/chris",
                     "tryhackme.com/p/chris"):
        assert expected in line
    assert line.count("·") == 5


def test_contact_line_skips_missing_fields():
    line = _contact_from_answers({"contact": {"email": "c@example.com"}})
    assert line == "c@example.com"
    assert _contact_from_answers({}) == ""


class CapturingAI:
    def __init__(self):
        self.user_prompt = ""

    def parse(self, system, user, output_model, max_tokens=None):
        self.user_prompt = user
        return TailoredPackage.model_validate({
            "resume": {"name": "X", "contact": "", "summary": "", "skills": [],
                       "experience": [], "education": [], "certifications": []},
            "cover_letter": "",
        })


def make_job() -> Job:
    return Job(url="u", source="linkedin", title="T", company="C", description="d")


def test_no_summary_instruction_when_disabled():
    ai = CapturingAI()
    tailor_for_job(ai, "resume", make_job(), include_summary=False)
    assert "Do NOT write a professional summary" in ai.user_prompt


def test_summary_kept_by_default():
    ai = CapturingAI()
    tailor_for_job(ai, "resume", make_job())
    assert "Do NOT write a professional summary" not in ai.user_prompt
