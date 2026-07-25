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
   Copy the candidate's name and contact line from the master resume EXACTLY,
   preserving every URL (LinkedIn, GitHub, TryHackMe, etc.) character-for-character.
3. Prefer the master resume's own numbers/metrics; never fabricate new ones.
4. Mirror the job posting's terminology only where the master resume genuinely
   supports it (e.g. rename a skills grouping, lead with the most relevant bullets).
5. PRESERVE the master resume's density — the goal is a FULL two pages, not a
   shorter resume. Keep nearly every bullet from the master resume, rewording
   and reordering so the most relevant come first; drop or merge a bullet only
   when it is clearly irrelevant to this posting. Never condense a role to a
   handful of bullets when the master resume gives it more. Each bullet stays
   a single sentence (~25 words max). Summary (when requested): 2-3 lines.
6. Group skills into "skill_groups" — short subheadings like "Cybersecurity",
   "Technical Support", "Languages" (use groupings that fit the master resume
   and this posting). Include EVERY skill from the master resume, ordering the
   most relevant groups and items first — do not trim the list. Also fill the
   flat "skills" list with the same items for compatibility.
7. If the master resume has personal/technical projects, keep them all in
   "projects" (most relevant first, one concise bullet each) unless one is
   clearly irrelevant; otherwise return an empty list — never invent projects.
8. Cover letter: 3 short paragraphs, specific to this company and role, plain
   text, no addresses or date header, greeting "Dear Hiring Manager," unless a
   name appears in the posting. Same no-invention rule applies.

Return JSON only, no prose, matching exactly this schema:
{
  "resume": {
    "name": "...", "contact": "...", "summary": "...",
    "skills": ["...", ...],
    "skill_groups": [{"name": "...", "items": ["...", ...]}, ...],
    "experience": [{"company": "...", "title": "...", "dates": "...",
                     "location": "...", "bullets": ["...", ...]}, ...],
    "projects": ["...", ...],
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


class SkillGroup(BaseModel):
    name: str
    items: list[str] = Field(default_factory=list)


class TailoredResume(BaseModel):
    name: str
    contact: str = ""
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    skill_groups: list[SkillGroup] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


class TailoredPackage(BaseModel):
    resume: TailoredResume
    cover_letter: str = ""


def tailor_for_job(ai, master_resume: str, job: Job,
                   extra_instructions: str = "",
                   include_summary: bool = True) -> TailoredPackage:
    user = (
        f"MASTER RESUME:\n{master_resume}\n\n"
        f"JOB POSTING ({job.title} at {job.company}, {job.location}):\n"
        f"{job.description}\n\n"
        "Tailor the resume and write the cover letter for this posting."
    )
    if not include_summary:
        user += (
            "\n\nDo NOT write a professional summary — set the 'summary' field "
            "to an empty string. Instead, make the experience bullets carry the "
            "candidate's strongest, most relevant points for this posting."
        )
    if extra_instructions.strip():
        user += (
            "\n\nSTYLE INSTRUCTIONS FROM THE CANDIDATE (follow these for tone "
            f"and wording):\n{extra_instructions.strip()}"
        )
    return ai.parse(SYSTEM, user, TailoredPackage)
