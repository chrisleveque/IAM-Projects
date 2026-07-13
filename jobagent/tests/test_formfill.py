from jobagent.apply.formfill import match_answer, yesno

ANSWERS = {
    "contact": {
        "full_name": "Chris Leveque",
        "email": "chris@example.com",
        "phone": "(555) 555-5555",
        "city": "Austin, TX",
        "linkedin": "https://www.linkedin.com/in/chris",
    },
    "work_authorization": {"authorized_to_work_us": True, "require_sponsorship": False},
    "preferences": {"willing_to_relocate": False, "desired_salary": "125000",
                    "notice_period_days": 14},
    "years_experience": {"default": "5", "by_skill": {"okta": "4"}},
    "custom_answers": [{"match": ["security clearance"], "answer": "No"}],
}


def test_yesno():
    assert yesno(True) == "Yes"
    assert yesno(False) == "No"
    assert yesno(None) is None


def test_work_authorization():
    assert match_answer("Are you legally authorized to work in the United States?",
                        ANSWERS) == "Yes"
    assert match_answer("Will you now or in the future require sponsorship?",
                        ANSWERS) == "No"


def test_contact_fields():
    assert match_answer("Mobile phone number", ANSWERS) == "(555) 555-5555"
    assert match_answer("First name", ANSWERS) == "Chris"
    assert match_answer("Last name", ANSWERS) == "Leveque"
    assert match_answer("What city are you based in?", ANSWERS) == "Austin, TX"


def test_preferences():
    assert match_answer("What is your desired salary?", ANSWERS) == "125000"
    assert match_answer("Are you willing to relocate?", ANSWERS) == "No"
    assert match_answer("What is your notice period?", ANSWERS) == "14"


def test_years_experience_skill_specific_then_default():
    assert match_answer("How many years of experience do you have with Okta?",
                        ANSWERS) == "4"
    assert match_answer("How many years of work experience do you have?",
                        ANSWERS) == "5"


def test_custom_rules_win():
    assert match_answer("Do you have an active security clearance?", ANSWERS) == "No"


def test_unknown_question_returns_none():
    assert match_answer("Describe your favorite project", ANSWERS) is None
    assert match_answer("", ANSWERS) is None
