"""Best-effort application form filling shared by the LinkedIn and Indeed flows.

Questions are matched against profile/answers.yaml; anything unmatched is
drafted by the AI (from your profile) and shown in the terminal for you to
confirm, edit, or skip — confirmed answers are saved back to answers.yaml so
you're only asked once. Nothing here submits anything: you always review the
filled form in the browser and click Submit yourself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import yaml
from rich.console import Console
from rich.prompt import Prompt

# JS run against each input to find its question text (label / aria / placeholder).
_LABEL_JS = """el => {
  const clean = t => (t || '').replace(/\\s+/g, ' ').trim();
  if (el.id) {
    const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    if (l) return clean(l.innerText);
  }
  const wrap = el.closest('label');
  if (wrap) return clean(wrap.innerText);
  const grp = el.closest('fieldset, div, section');
  if (grp) {
    const l = grp.querySelector('legend, label, .artdeco-text-input--label');
    if (l) return clean(l.innerText);
  }
  return clean(el.getAttribute('aria-label') || el.getAttribute('placeholder'));
}"""

_TEXT_INPUTS = ("input[type='text'], input[type='tel'], input[type='email'], "
                "input[type='number'], input:not([type]), textarea")


def yesno(value) -> str | None:
    if value is None:
        return None
    return "Yes" if value else "No"


def match_answer(question: str, answers: dict) -> str | None:
    """Match a form question against answers.yaml. Returns None when unknown."""
    q = question.lower()
    if not q:
        return None

    for rule in answers.get("custom_answers") or []:
        keywords = rule.get("match") or []
        if any(str(k).lower() in q for k in keywords):
            return str(rule.get("answer", ""))

    wa = answers.get("work_authorization") or {}
    if "sponsor" in q:
        return yesno(wa.get("require_sponsorship"))
    if "authorized" in q or "legally" in q or "right to work" in q:
        return yesno(wa.get("authorized_to_work_us"))

    contact = answers.get("contact") or {}
    if "phone" in q or "mobile" in q:
        return contact.get("phone")
    if "email" in q:
        return contact.get("email")
    if "linkedin" in q:
        return contact.get("linkedin")
    if "first name" in q:
        return (contact.get("full_name") or "").split(" ")[0] or None
    if "last name" in q:
        parts = (contact.get("full_name") or "").split(" ")
        return parts[-1] if len(parts) > 1 else None
    if "city" in q or ("location" in q and "relocat" not in q):
        return contact.get("city")

    prefs = answers.get("preferences") or {}
    if "relocat" in q:
        return yesno(prefs.get("willing_to_relocate"))
    if "salary" in q or "compensation" in q or "desired pay" in q:
        v = prefs.get("desired_salary")
        return str(v) if v is not None else None
    if "notice" in q:
        v = prefs.get("notice_period_days")
        return str(v) if v is not None else None

    ye = answers.get("years_experience") or {}
    if "years" in q and "experience" in q:
        for skill, val in (ye.get("by_skill") or {}).items():
            if str(skill).lower() in q:
                return str(val)
        v = ye.get("default")
        return str(v) if v is not None else None

    return None


AI_ANSWER_SYSTEM = """You draft one short answer to a job-application form question \
on behalf of a candidate, using only their profile below. Answer in the first \
person, 1-3 sentences max (or a single number/word if the question calls for it). \
Never invent credentials or facts not in the profile. Return only the answer text."""


class FormContext:
    def __init__(
        self,
        answers: dict,
        resume_file: Path | None,
        console: Console,
        ai=None,  # AIClient | None
        master_resume: str = "",
        answers_path: Path | None = None,
    ):
        self.answers = answers
        self.resume_file = resume_file
        self.console = console
        self.ai = ai
        self.master_resume = master_resume
        self.answers_path = answers_path
        self.learned: dict[str, str] = {}

    def resolve(self, question: str) -> str | None:
        answer = match_answer(question, self.answers)
        if answer:
            return answer
        if question in self.learned:
            return self.learned[question]
        return self._ask_with_ai(question)

    def _ask_with_ai(self, question: str) -> str | None:
        draft = ""
        if self.ai is not None:
            try:
                draft = self.ai.complete(
                    AI_ANSWER_SYSTEM,
                    f"PROFILE:\n{self.master_resume}\n\nQUESTION: {question}",
                    max_tokens=300,
                ).strip()
            except Exception as exc:
                self.console.print(f"[yellow]AI draft failed: {exc}[/yellow]")
        self.console.print(f"\n[bold]Form question:[/bold] {question}")
        if draft:
            self.console.print(f"[cyan]Suggested:[/cyan] {draft}")
        reply = Prompt.ask(
            "Press Enter to accept the suggestion, type an answer, or 'skip'",
            default="",
        ).strip()
        if reply.lower() == "skip":
            return None
        answer = reply or draft
        if not answer:
            return None
        self.learned[question] = answer
        self._save_learned(question, answer)
        return answer

    def _save_learned(self, question: str, answer: str) -> None:
        """Persist a confirmed answer to answers.yaml so it's never asked again."""
        if self.answers_path is None:
            return
        rule = {"match": [question.lower()[:60]], "answer": answer}
        self.answers.setdefault("custom_answers", []).append(rule)
        try:
            self.answers_path.write_text(
                yaml.safe_dump(self.answers, sort_keys=False, allow_unicode=True)
            )
        except OSError as exc:
            self.console.print(f"[yellow]Could not save answer: {exc}[/yellow]")


def fill_scope(scope, ctx: FormContext, pause: Callable[[], None]) -> list[str]:
    """Fill file/text/select/radio fields inside `scope`. Returns skipped questions."""
    skipped: list[str] = []

    for file_input in scope.locator("input[type='file']").all():
        try:
            if ctx.resume_file is not None:
                file_input.set_input_files(str(ctx.resume_file))
                ctx.console.print(f"  uploaded resume: {ctx.resume_file.name}")
                pause()
        except Exception:
            continue

    for inp in scope.locator(_TEXT_INPUTS).all():
        try:
            if not inp.is_visible() or inp.input_value().strip():
                continue  # hidden or already pre-filled by the site
            question = inp.evaluate(_LABEL_JS) or ""
            answer = ctx.resolve(question) if question else None
            if answer:
                inp.fill(answer)
                pause()
            elif question:
                skipped.append(question)
        except Exception:
            continue

    for sel in scope.locator("select").all():
        try:
            if not sel.is_visible():
                continue
            question = sel.evaluate(_LABEL_JS) or ""
            answer = ctx.resolve(question) if question else None
            if not answer:
                if question:
                    skipped.append(question)
                continue
            options = sel.evaluate(
                "el => Array.from(el.options).map(o => o.textContent.trim())"
            )
            target = next(
                (o for o in options if o.lower() == answer.lower()), None
            ) or next(
                (o for o in options if answer.lower() in o.lower()), None
            )
            if target:
                sel.select_option(label=target)
                pause()
            else:
                skipped.append(question)
        except Exception:
            continue

    for fs in scope.locator("fieldset").all():
        try:
            if fs.locator("input[type='radio']").count() == 0:
                continue
            legend = fs.locator("legend").first
            question = legend.inner_text().strip() if legend.count() else ""
            answer = ctx.resolve(question) if question else None
            if not answer:
                if question:
                    skipped.append(question)
                continue
            option = fs.locator("label", has_text=answer).first
            if option.count():
                option.click()
                pause()
            else:
                skipped.append(question)
        except Exception:
            continue

    return skipped
