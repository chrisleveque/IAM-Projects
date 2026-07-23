from jobagent.ai.tailor import SYSTEM, TailoredPackage, tailor_for_job
from jobagent.store import Job


class CapturingAI:
    def __init__(self):
        self.user_prompt = ""

    def parse(self, system, user, output_model, max_tokens=None):
        self.user_prompt = user
        return TailoredPackage.model_validate({
            "resume": {"name": "Chris", "contact": "", "summary": "", "skills": [],
                       "experience": [], "education": [], "certifications": []},
            "cover_letter": "",
        })


def make_job() -> Job:
    return Job(url="u", source="linkedin", title="IAM Engineer",
               company="Acme", description="desc")


def test_extra_instructions_are_included():
    ai = CapturingAI()
    tailor_for_job(ai, "resume text", make_job(),
                   extra_instructions="First person, no buzzwords.")
    assert "First person, no buzzwords." in ai.user_prompt
    assert "STYLE INSTRUCTIONS" in ai.user_prompt


def test_no_instructions_block_when_empty():
    ai = CapturingAI()
    tailor_for_job(ai, "resume text", make_job(), extra_instructions="   ")
    assert "STYLE INSTRUCTIONS" not in ai.user_prompt


def test_system_prompt_demands_verbatim_contact():
    assert "character-for-character" in SYSTEM
