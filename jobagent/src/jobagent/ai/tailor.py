"""Tailor the master resume + write a cover letter for one specific job.

The hard rule baked into the prompt: the model may select, reorder, and reword
content from the master resume, but must never invent employers, titles, dates,
degrees, certifications, metrics, or skills that aren't there. Fabricated
resumes fail background checks and burn bridges.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..store import Job

SYSTEM = """You are an expert resume writer tailoring a candidate's resume to one \
specific job posting.

HARD RULES — violating these harms the candidate:
1. Use ONLY facts present in the master resume. You may select, reorder, reword,
   and emphasize; you may NOT invent employers, job titles, dates, locations,
   degrees, certifications, tools, metrics, or skills that are not in it.
2. Keep every employer name, job title, and date range exactly as written.
3. Prefer the master resume's own numbers/metrics; never fabricate new ones.
4. Mirror the job posting's terminology only where the master resume genuinely
   supports it (e.g. rename a skills grouping, lead with the most relevant bullets).
5. Resume: at most 4-5 bullets per role, most relevant first. Summary: 2-3 lines
   targeted at this posting.
6. Cover letter: 3 short paragraphs, specific to this company and role, plain
   text, no addresses or date header, greeting "Dear Hiring Manager," unless a
   name appears in the posting. Same no-invention rule applies.

Return JSON only, no prose, matching exactly this schema:
{
  "resume": {
    "name": "...", "contact": "...", "summary": "...",
    "skills": ["...", ...],
    "experience": [{"company": "...", "title": "...", "dates": "...",
                     "location": "...", "bullets": ["...", ...]}, ...],
    "education": ["...", ...],
    "certifications": ["...", ...]
  },
  "cover_letter": "..."
}"""


class ExperienceItem(BaseModel):
    company: str
    title: str
    dates: str = ""
    location: str = ""
    bullets: list[str] = Field(default_factory=list)


class TailoredResume(BaseModel):
    name: str
    contact: str = ""
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


class TailoredPackage(BaseModel):
    resume: TailoredResume
    cover_letter: str = ""


def tailor_for_job(ai, master_resume: str, job: Job) -> TailoredPackage:
    user = (
        f"MASTER RESUME:\n{master_resume}\n\n"
        f"JOB POSTING ({job.title} at {job.company}, {job.location}):\n"
        f"{job.description}\n\n"
        "Tailor the resume and write the cover letter for this posting."
    )
    data = ai.complete_json(SYSTEM, user)
    return TailoredPackage.model_validate(data)
