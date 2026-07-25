import pytest

from jobagent.ai.answerer import (Answerer, AnswerSet, cache_key,
                                  find_decline_option, is_compliance_question,
                                  is_demographic_question)
from jobagent.ats.fields import FormField
from jobagent.store import Store


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "t.db")


class StubAI:
    """Returns canned answers; records what it was asked."""

    def __init__(self, answers: dict[int, tuple[str, bool]] | None = None):
        self.answers = answers or {}
        self.asked: list[str] = []

    def parse(self, system, user, output_model, max_tokens=None):
        self.asked.append(user)
        return AnswerSet.model_validate({"answers": [
            {"id": i, "value": v, "known": k}
            for i, (v, k) in self.answers.items()
        ]})


def text(idx, label, required=False):
    return FormField(idx=idx, kind="text", label=label, required=required)


def select(idx, label, options, required=False):
    return FormField(idx=idx, kind="select", label=label, options=options,
                     required=required)


def test_compliance_questions_are_recognized():
    for q in ("Will you now or in the future require sponsorship?",
              "Are you legally authorized to work in the United States?",
              "What are your salary expectations?",
              "Have you ever been convicted of a felony?",
              "Do you hold an active security clearance?",
              "Are you willing to submit to a drug screen?"):
        assert is_compliance_question(q), q


def test_ordinary_questions_are_not_compliance():
    for q in ("How many years of Okta experience do you have?",
              "Why are you interested in this role?",
              "What is your LinkedIn profile URL?"):
        assert not is_compliance_question(q), q


def test_compliance_question_is_parked_not_guessed(store):
    ai = StubAI({0: ("No", True)})  # AI would happily answer — it must not be asked
    answerer = Answerer({}, store=store, ai=ai, profile="p")
    field = text(0, "Will you require visa sponsorship?", required=True)
    resolved, parked = answerer.resolve([field])
    assert resolved == {}
    assert len(parked) == 1
    assert "answers.yaml" in parked[0].reason
    assert not ai.asked  # never even sent to the model


def test_compliance_question_answered_from_answers_yaml(store):
    answers = {"work_authorization": {"authorized_to_work_us": True,
                                      "require_sponsorship": False}}
    answerer = Answerer(answers, store=store, ai=StubAI(), profile="p")
    field = text(0, "Are you legally authorized to work in the US?")
    resolved, parked = answerer.resolve([field])
    assert resolved == {0: "Yes"}
    assert parked == []


def test_demographic_question_declines_when_option_exists(store):
    answerer = Answerer({}, store=store, ai=StubAI(), profile="p")
    field = select(0, "Gender", ["Male", "Female", "Decline to self-identify"],
                   required=True)
    resolved, parked = answerer.resolve([field])
    assert resolved == {0: "Decline to self-identify"}
    assert parked == []


def test_demographic_question_without_decline_option_is_parked(store):
    answerer = Answerer({}, store=store, ai=StubAI({0: ("Male", True)}),
                        profile="p")
    field = select(0, "Gender", ["Male", "Female"], required=True)
    resolved, parked = answerer.resolve([field])
    assert resolved == {}
    assert parked and parked[0].field is field


def test_find_decline_option_wordings():
    for wording in ("Decline to self-identify", "I don't wish to answer",
                    "Prefer not to say", "I do not wish to disclose",
                    "I prefer not to answer"):
        assert find_decline_option(["Yes", "No", wording]) == wording
    assert find_decline_option(["Yes", "No"]) is None


def test_unknown_answer_is_parked_never_invented(store):
    ai = StubAI({0: ("", False)})
    answerer = Answerer({}, store=store, ai=ai, profile="p")
    field = text(0, "Describe your experience with COBOL on mainframes",
                 required=True)
    resolved, parked = answerer.resolve([field])
    assert resolved == {}
    assert parked


def test_ai_answer_must_be_one_of_the_options(store):
    # model returns something not in the options -> parked, not forced in
    ai = StubAI({0: ("Six to eight years", True)})
    answerer = Answerer({}, store=store, ai=ai, profile="p")
    field = select(0, "Years of IAM experience", ["0-2", "3-5", "10+"])
    resolved, parked = answerer.resolve([field])
    assert resolved == {}
    assert "not one of the options" in parked[0].reason


def test_ai_answer_close_to_an_option_is_snapped_to_it(store):
    ai = StubAI({0: ("3-5", True)})
    answerer = Answerer({}, store=store, ai=ai, profile="p")
    field = select(0, "Years of IAM experience", ["0-2 years", "3-5 years", "10+"])
    resolved, _ = answerer.resolve([field])
    assert resolved == {0: "3-5 years"}


def test_answers_are_cached_and_reused(store):
    ai = StubAI({0: ("Chris Leveque", True)})
    first = Answerer({}, store=store, ai=ai, profile="p")
    field = text(0, "Preferred name")
    assert first.resolve([field])[0] == {0: "Chris Leveque"}
    first.remember()

    # a second application, no AI available at all
    second = Answerer({}, store=store, ai=None, profile="p")
    resolved, parked = second.resolve([text(0, "Preferred name")])
    assert resolved == {0: "Chris Leveque"}
    assert parked == []


def test_cache_key_normalizes_wording():
    assert cache_key("Preferred name *") == cache_key("preferred   name")
    assert cache_key("Years of experience? (required)") == \
        cache_key("years of experience")


def test_prefilled_fields_are_left_alone(store):
    answerer = Answerer({}, store=store, ai=StubAI(), profile="p")
    field = FormField(idx=0, kind="text", label="Email", value="c@example.com")
    resolved, parked = answerer.resolve([field])
    assert resolved == {} and parked == []


def test_no_ai_client_parks_instead_of_guessing(store):
    answerer = Answerer({}, store=store, ai=None, profile="p")
    resolved, parked = answerer.resolve([text(0, "Why this role?", required=True)])
    assert resolved == {}
    assert "no AI client" in parked[0].reason


def test_ai_failure_parks_every_question(store):
    class Boom:
        def parse(self, *a, **k):
            raise RuntimeError("api down")

    answerer = Answerer({}, store=store, ai=Boom(), profile="p")
    resolved, parked = answerer.resolve([text(0, "Why this role?")])
    assert resolved == {}
    assert "AI answer failed" in parked[0].reason


def test_file_fields_are_not_answered(store):
    answerer = Answerer({}, store=store, ai=StubAI(), profile="p")
    field = FormField(idx=0, kind="file", label="Resume", required=True)
    resolved, parked = answerer.resolve([field])
    assert resolved == {} and parked == []


def test_full_name_field_resolves_from_contact():
    """Lever-style single 'Full name' fields, and the first/last variants."""
    from jobagent.apply.formfill import match_answer

    answers = {"contact": {"full_name": "Chris Leveque"}}
    for question in ("Full name", "Full name *", "Name", "Your name",
                     "Legal name", "Preferred name"):
        assert match_answer(question, answers) == "Chris Leveque", question
    assert match_answer("First name", answers) == "Chris"
    assert match_answer("Last name", answers) == "Leveque"
    assert match_answer("Surname", answers) == "Leveque"
    # not a person-name question
    assert match_answer("Company name", answers) != "Chris Leveque"


def test_missing_compliance_answers_reports_gaps():
    from jobagent.cli import _missing_compliance_answers

    assert "work authorization" in _missing_compliance_answers({})
    complete = {
        "work_authorization": {"authorized_to_work_us": True,
                               "require_sponsorship": False},
        "preferences": {"desired_salary": "120000"},
        "custom_answers": [
            {"match": ["felony"], "answer": "No"},
            {"match": ["security clearance"], "answer": "No"},
            {"match": ["drug screen"], "answer": "Yes"},
        ],
    }
    assert _missing_compliance_answers(complete) == []
