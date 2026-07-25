"""Decide answers for application-form questions.

Resolution order, most trustworthy first:
  1. answers.yaml rules (deterministic, written by the candidate)
  2. the answer cache (something the candidate already answered before)
  3. the AI, restricted to facts in the profile
  4. nothing — the question is parked and the application is not submitted

The AI may NOT guess. Legal/compliance questions (work authorization, salary,
criminal history, degree verification) must come from answers.yaml or be
parked, because a wrong answer submitted under the candidate's real name is a
false statement on a job application. Voluntary EEO/demographic questions are
the one exception: choosing an explicit "decline to self-identify" option is
truthful and keeps the form movable.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

# Questions whose answers carry legal weight — never AI-guessed. If
# answers.yaml doesn't cover them, the application is parked.
COMPLIANCE_PATTERNS = (
    r"\bsponsor",
    r"\bvisa\b",
    r"authoriz(ed|ation) to work",
    r"\bright to work\b",
    r"\bwork permit\b",
    r"\bfelony\b|\bconvict|criminal (history|record|background)",
    r"\bdrug (test|screen)",
    r"security clearance",
    r"\bsalary\b|\bcompensation\b|desired pay|pay expectation",
    r"non-?compete",
    r"\bage\b.*\b(18|21)\b|are you at least",
)

# Voluntary self-identification — a declination is a truthful answer.
DEMOGRAPHIC_PATTERNS = (
    r"\bgender\b",
    r"\brace\b|ethnicity|hispanic|latino",
    r"\bveteran\b|military service",
    r"\bdisabilit",
    r"self-?identif",
    r"\bpronouns?\b",
)

DECLINE_PATTERNS = (
    r"decline to self.?identif",
    r"(don'?t|do not|prefer not|wish not|choose not|rather not).{0,20}"
    r"(answer|say|identify|disclose|specify)",
    r"^prefer not to say$",
    r"i don'?t wish to answer",
)


def _matches(question: str, patterns) -> bool:
    q = question.lower()
    return any(re.search(p, q) for p in patterns)


def is_compliance_question(question: str) -> bool:
    return _matches(question, COMPLIANCE_PATTERNS)


def is_demographic_question(question: str) -> bool:
    return _matches(question, DEMOGRAPHIC_PATTERNS)


def find_decline_option(options: list[str]) -> str | None:
    """Return the option that declines to self-identify, when one exists."""
    for opt in options:
        if _matches(opt, DECLINE_PATTERNS):
            return opt
    return None


def cache_key(question: str) -> str:
    """Normalize a question so trivial wording/format differences still hit."""
    q = re.sub(r"\s+", " ", question.lower()).strip()
    q = re.sub(r"[*✱]|\(required\)|\(optional\)", "", q)
    return re.sub(r"[^a-z0-9 ]", "", q).strip()[:200]


SYSTEM = """You answer job-application form questions for one candidate, using \
ONLY the facts in their profile.

RULES — breaking these harms the candidate:
1. Never invent or estimate. If the profile does not contain the answer, set
   "known": false and leave "value" empty. A parked question is fine; a wrong
   answer submitted under the candidate's real name is not.
2. For select/radio/checkbox questions, "value" MUST be copied exactly from
   that question's provided options. If no option is truthful, set
   "known": false.
3. Do not answer questions about work authorization, visa sponsorship, salary,
   criminal history, clearances, or drug screening — those are handled
   elsewhere. Set "known": false for them.
4. Keep free-text answers short and first-person: 1-3 sentences, or a single
   number/word when that is what is asked. Website/profile URL questions take
   the matching URL from the profile.
5. "Why do you want to work here" style questions may be answered from the
   candidate's real background and the job description only — no flattery
   about the company that you cannot support from the provided text.

Return one entry per question, keyed by its id."""


class FieldAnswer(BaseModel):
    id: int
    value: str = ""
    known: bool = False
    reason: str = ""  # short note when known=false, for the audit log


class AnswerSet(BaseModel):
    answers: list[FieldAnswer] = Field(default_factory=list)


def _describe(field) -> str:
    parts = [f"id={field.idx}", f"kind={field.kind}", f"question={field.question!r}"]
    if field.required:
        parts.append("required")
    if field.options:
        parts.append("options=" + " | ".join(field.options))
    return "  ".join(parts)


def ai_answers(ai, fields, profile: str, job=None) -> dict[int, FieldAnswer]:
    """Ask the model for answers to `fields`. One call for the whole batch."""
    if not fields:
        return {}
    lines = "\n".join(_describe(f) for f in fields)
    context = f"CANDIDATE PROFILE:\n{profile}\n"
    if job is not None:
        context += (
            f"\nJOB: {job.title} at {job.company}\n"
            f"JOB DESCRIPTION (for 'why this role' style questions only):\n"
            f"{(job.description or '')[:4000]}\n"
        )
    result = ai.parse(SYSTEM, f"{context}\nQUESTIONS:\n{lines}", AnswerSet,
                      max_tokens=2000)
    return {a.id: a for a in result.answers}


class Answerer:
    """Resolves form fields to answers, recording where each one came from."""

    def __init__(self, answers: dict, store=None, ai=None, profile: str = "",
                 job=None):
        self.answers = answers
        self.store = store
        self.ai = ai
        self.profile = profile
        self.job = job
        # question -> (value, source); source is used for the audit log
        self.decisions: dict[str, tuple[str, str]] = {}

    def _from_rules(self, field) -> str | None:
        from ..apply.formfill import match_answer

        return match_answer(field.question, self.answers)

    def _from_cache(self, field) -> str | None:
        if self.store is None:
            return None
        return self.store.get_cached_answer(cache_key(field.question))

    def resolve(self, fields) -> tuple[dict[int, str], list[FormFieldParked]]:
        """Return {field idx: answer} plus the fields that must stay unanswered."""
        resolved: dict[int, str] = {}
        parked: list[FormFieldParked] = []
        needs_ai = []

        for f in fields:
            if f.kind == "file" or not f.question:
                continue
            if f.is_answered and f.kind not in ("radio", "checkbox"):
                continue  # the site pre-filled it; leave it alone

            rule = self._from_rules(f)
            if rule:
                resolved[f.idx] = str(rule)
                self.decisions[f.question] = (str(rule), "answers.yaml")
                continue

            cached = self._from_cache(f)
            if cached:
                resolved[f.idx] = cached
                self.decisions[f.question] = (cached, "cache")
                continue

            # Demographic self-ID never reaches the model: these facts aren't
            # in the profile, so a "helpful" guess would be an invented answer
            # about a protected characteristic. Decline if we can, else park.
            if is_demographic_question(f.question):
                decline = find_decline_option(f.options)
                if decline:
                    resolved[f.idx] = decline
                    self.decisions[f.question] = (decline, "declined")
                else:
                    parked.append(FormFieldParked(
                        f, "demographic self-identification with no "
                           "decline-to-answer option"))
                continue

            if is_compliance_question(f.question):
                parked.append(FormFieldParked(
                    f, "compliance question not covered by answers.yaml"))
                continue

            needs_ai.append(f)

        if needs_ai and self.ai is not None:
            try:
                drafted = ai_answers(self.ai, needs_ai, self.profile, self.job)
            except Exception as exc:  # AI unavailable -> park, never guess
                for f in needs_ai:
                    parked.append(FormFieldParked(f, f"AI answer failed: {exc}"))
                drafted = {}
            for f in needs_ai:
                answer = drafted.get(f.idx)
                if answer is None or not answer.known or not answer.value.strip():
                    reason = (answer.reason if answer and answer.reason
                              else "not answerable from the profile")
                    parked.append(FormFieldParked(f, reason))
                    continue
                # Enforce rule 2 in code, not just in the prompt.
                if f.options and answer.value not in f.options:
                    from ..ats.fields import match_option

                    match = match_option(f.options, answer.value)
                    if match is None:
                        parked.append(FormFieldParked(
                            f, f"AI answer {answer.value!r} is not one of the options"))
                        continue
                    answer.value = match
                resolved[f.idx] = answer.value
                self.decisions[f.question] = (answer.value, "ai")
        elif needs_ai:
            for f in needs_ai:
                parked.append(FormFieldParked(f, "no AI client configured"))

        return resolved, parked

    def remember(self) -> None:
        """Persist AI-derived answers so later applications reuse them."""
        if self.store is None:
            return
        for question, (value, source) in self.decisions.items():
            if source == "ai":
                self.store.put_cached_answer(cache_key(question), question, value)


class FormFieldParked:
    """A question the agent refused to answer, with the reason why."""

    __slots__ = ("field", "reason")

    def __init__(self, field, reason: str):
        self.field = field
        self.reason = reason

    def __repr__(self) -> str:  # shows up in reports and test failures
        return f"<parked {self.field.question!r}: {self.reason}>"
