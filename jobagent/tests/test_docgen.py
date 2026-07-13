from docx import Document

from jobagent.ai.tailor import ExperienceItem, TailoredResume
from jobagent.docgen import slugify, write_cover_letter_docx, write_resume_docx


def sample_resume() -> TailoredResume:
    return TailoredResume(
        name="Chris Leveque",
        contact="City, ST · chris@example.com · (555) 555-5555",
        summary="IAM engineer focused on Okta and Entra ID.",
        skills=["Okta", "Entra ID", "SailPoint"],
        experience=[
            ExperienceItem(company="Acme", title="IAM Engineer",
                           dates="2021 – Present", location="Remote",
                           bullets=["Migrated 5k users to Okta", "Automated JML with SCIM"]),
        ],
        education=["B.S. Something, Some University"],
        certifications=["Okta Certified Professional"],
    )


def all_text(path) -> str:
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def test_write_resume_docx(tmp_path):
    path = write_resume_docx(sample_resume(), tmp_path / "out" / "resume.docx")
    assert path.exists()
    text = all_text(path)
    for expected in ("Chris Leveque", "Okta", "IAM Engineer — Acme".replace("—", "—"),
                     "Migrated 5k users to Okta", "Okta Certified Professional"):
        assert expected in text or expected.replace("—", "-") in text


def test_write_cover_letter_docx(tmp_path):
    letter = "Dear Hiring Manager,\n\nFirst paragraph.\n\nSecond paragraph."
    path = write_cover_letter_docx(letter, "Chris Leveque", tmp_path / "cl.docx")
    text = all_text(path)
    assert "Dear Hiring Manager," in text
    assert "Second paragraph." in text


def test_slugify():
    assert slugify("Sr. IAM Engineer @ Acme, Inc.") == "sr-iam-engineer-acme-inc"
    assert slugify("///") == "job"
