import json

import pytest

from jobagent.ai.client import extract_json
from jobagent.ai.scorer import ScoreResult
from jobagent.ai.tailor import TailoredPackage

TAILORED_FIXTURE = {
    "resume": {
        "name": "Chris Leveque",
        "contact": "chris@example.com",
        "summary": "IAM engineer.",
        "skills": ["Okta"],
        "experience": [
            {"company": "Acme", "title": "IAM Engineer", "dates": "2021 – Present",
             "location": "Remote", "bullets": ["Did a thing"]}
        ],
        "education": ["B.S."],
        "certifications": [],
    },
    "cover_letter": "Dear Hiring Manager,\n\nHello.",
}


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    text = "Here you go:\n```json\n{\"a\": 1}\n```\nthanks"
    assert extract_json(text) == {"a": 1}


def test_extract_json_with_surrounding_prose():
    assert extract_json('preamble {"a": {"b": 2}} trailing') == {"a": {"b": 2}}


def test_extract_json_no_object_raises():
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_tailored_package_validates_fixture():
    package = TailoredPackage.model_validate(TAILORED_FIXTURE)
    assert package.resume.name == "Chris Leveque"
    assert package.resume.experience[0].company == "Acme"


def test_tailored_package_roundtrip_via_extract_json():
    fenced = f"```json\n{json.dumps(TAILORED_FIXTURE)}\n```"
    package = TailoredPackage.model_validate(extract_json(fenced))
    assert package.cover_letter.startswith("Dear Hiring Manager")


def test_score_result_bounds():
    assert ScoreResult.model_validate({"score": 85, "reasons": ["r"]}).score == 85
    with pytest.raises(Exception):
        ScoreResult.model_validate({"score": 150})
