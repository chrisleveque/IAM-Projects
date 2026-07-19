"""Ideation agent: picks the next video's concept.

The orchestrator decides original vs public-domain deterministically (from
the store's 80/20 ledger) and TELLS the agent which one this run is — the
agent's creativity goes into theme, angle, and hook, not into drifting the
content mix."""

from __future__ import annotations

import json

from .base import JSONAgent
from .contracts import ConceptOutput


class IdeationAgent(JSONAgent):
    name = "ideation"
    output_model = ConceptOutput

    def system_prompt(self) -> str:
        return (
            "You are the ideation lead for a men's fitness motivation YouTube "
            "channel in the classic style: dark cinematic b-roll, deep voiceover, "
            "epic music.\n\n"
            f"{self.channel_context()}\n\n"
            "Pick ONE video concept. Rules:\n"
            "- Themes that work: discipline, adversity, consistency, solitude, "
            "comeback, purpose, delayed gratification, controlling what you can.\n"
            "- The angle must be specific enough to sustain 5-10 minutes without "
            "repeating itself. 'Work hard' is not an angle; 'discipline is a form "
            "of self-respect' is.\n"
            "- Avoid anything close to the recent topics you are given.\n"
            "- No health/medical claims, no shaming, no supplements, no toxic "
            "grindset cliches.\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"concept": {"working_title": str, "theme": str, "angle": str, '
            '"source_type": str (exactly as instructed), "pd_source": str|null '
            "(the source key you were given, if public_domain), "
            '"hook": str (one cold-open sentence), '
            '"emotional_arc": [4 short phase descriptions], '
            '"target_minutes": number, '
            '"visual_world": str (comma-separated imagery settings), '
            '"rationale": str}}'
        )

    def run(self, source_type: str, recent_topics: list[dict],
            pd_sources: list[dict], target_minutes: float) -> ConceptOutput:
        task = (
            f"This video's source_type MUST be: {source_type}\n"
            f"Target length: about {target_minutes:.0f} minutes.\n"
            f"Recent topics to avoid repeating:\n"
            f"{json.dumps(recent_topics, indent=2) if recent_topics else '(none yet)'}\n"
        )
        if source_type == "public_domain":
            task += (
                "\nAvailable public-domain sources (pick ONE, return its key as "
                f"pd_source):\n{json.dumps(pd_sources, indent=2)}\n"
            )
        else:
            task += "\nWrite an original concept; pd_source must be null.\n"
        return self.run_json(task)
