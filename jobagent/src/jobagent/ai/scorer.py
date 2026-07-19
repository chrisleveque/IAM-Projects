"""Score how well a job matches the master resume, so tailoring effort goes
to the jobs worth applying to."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..store import Job

SYSTEM = """You are a pragmatic recruiting analyst helping a candidate triage job \
postings. Compare the candidate's master resume to the job description and return \
a fit assessment as JSON only, no prose, matching exactly:

{"score": <integer 0-100>, "reasons": ["short reason", ...], "concerns": ["short concern", ...]}

Scoring guide: 80+ strong match (most requirements met), 60-79 decent match worth \
applying, 40-59 stretch, below 40 poor fit. Be honest — an inflated score wastes \
the candidate's daily application budget. Consider required skills, seniority, \
domain, and location/remote constraints mentioned in the posting."""


class ScoreResult(BaseModel):
    score: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)

    def summary(self) -> str:
        parts = [f"+ {r}" for r in self.reasons] + [f"- {c}" for c in self.concerns]
        return "\n".join(parts)


def score_job(ai, master_resume: str, job: Job) -> ScoreResult:
    user = (
        f"MASTER RESUME:\n{master_resume}\n\n"
        f"JOB POSTING ({job.title} at {job.company}, {job.location}):\n{job.description}"
    )
    return ai.parse(SYSTEM, user, ScoreResult, max_tokens=1024)
