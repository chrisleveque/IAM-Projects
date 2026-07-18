"""Scriptwriter agent: the full voiceover script, segment by segment.

Two modes: original writing, or arranging public-domain excerpts with
original bridging narration (verbatim PD segments are tagged so the video
description can carry an attribution line)."""

from __future__ import annotations

import json

from .base import JSONAgent
from .contracts import ScriptOutput

STYLE_GUIDE = """\
GENRE STYLE GUIDE (classic motivation voiceover):
- Second person. You are talking to one man, alone, at a low point.
- Short declarative sentences. Fragments allowed. Present tense.
- Concrete imagery over abstraction: the 5am alarm, the empty gym, the last rep,
  rain on the window — not "success" and "greatness" in the abstract.
- Strategic repetition: plant a phrase in the hook, bring it back at the peak
  and again in the close.
- Earned intensity: start quiet and matter-of-fact, rise through the middle,
  peak once, then resolve calm and certain. Never start at 10/10.
- Speaking pace budget: 130-145 words per minute INCLUDING pauses. A 7-minute
  video is roughly 900-1000 words total.
- Pauses are part of the writing. Put longer pause_after_ms (900-1500) after
  lines that need to land; 300-600 for flowing passages.
- Banned: hustle-culture cliches ("rise and grind", "no days off", "sigma"),
  shaming the viewer, medical or financial promises, naming real people.
- Every segment gets a visual_theme a footage editor can search stock video
  for: concrete, filmable, 3-8 words.
"""


class ScriptwriterAgent(JSONAgent):
    name = "scriptwriter"
    output_model = ScriptOutput

    def system_prompt(self) -> str:
        return (
            "You write voiceover scripts for a men's fitness motivation YouTube "
            "channel.\n\n"
            f"{self.channel_context()}\n\n{STYLE_GUIDE}\n"
            "Segment the script into 12-24 segments of 1-3 sentences each — a "
            "segment is one breath of delivery and one visual beat.\n"
            "Also nominate 2-4 shorts_candidates: runs of consecutive segments "
            "(under ~55 seconds of speech, i.e. under ~130 words) that stand "
            "alone with their own hook.\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"script": {"title_working": str, "estimated_minutes": number, '
            '"segments": [{"id": "s01"..., "text": str, '
            '"role": "hook"|"build"|"peak"|"resolve"|"outro", "energy": 1-5, '
            '"visual_theme": str, "pd_verbatim": bool, "pause_after_ms": int}], '
            '"pd_attribution": str|null, '
            '"shorts_candidates": [{"segment_ids": [str], "hook_line": str, '
            '"why": str}]}}'
        )

    def run(self, concept: dict, pd_text: str | None = None) -> ScriptOutput:
        task = f"Write the script for this concept:\n{json.dumps(concept, indent=2)}\n"
        if pd_text:
            task += (
                "\nThis is a PUBLIC DOMAIN video. Build the script around excerpts "
                "from the source text below: select and arrange the strongest "
                "passages (mark those segments pd_verbatim: true, keep their "
                "wording exact), and write original framing and bridging narration "
                "around them (pd_verbatim: false). Set pd_attribution to a one-line "
                "credit taken from the source's attribution note.\n\n"
                f"SOURCE TEXT:\n{pd_text}\n"
            )
        else:
            task += ("\nThis is an ORIGINAL video: every segment is your own "
                     "writing, pd_verbatim false everywhere, pd_attribution null.\n")
        return self.run_json(task)
