"""Metadata agent: titles, descriptions, tags, and thumbnail text for the
long-form video and each short — grounded in the real rendered durations."""

from __future__ import annotations

import json

from .base import JSONAgent
from .contracts import MetadataOutput


def _fmt_ts(seconds: float) -> str:
    m, s = int(seconds // 60), int(seconds % 60)
    return f"{m}:{s:02d}"


class MetadataAgent(JSONAgent):
    name = "metadata"
    output_model = MetadataOutput

    def system_prompt(self) -> str:
        hints = ", ".join(self.preset.seo_hints)
        return (
            "You write YouTube metadata for a men's fitness motivation channel.\n\n"
            f"{self.channel_context()}\n\n"
            "Rules:\n"
            "- Long-form title: under 100 characters, hook-forward, no clickbait "
            "lies, no ALL CAPS words except one for emphasis at most.\n"
            "- Description: an opening hook paragraph, then a 'Chapters' block "
            "using the exact chapter timestamps you are given (format 'M:SS "
            "Title'), then the attribution line if one is provided, then 3-5 "
            "hashtags.\n"
            f"- Tags: 10-20, drawing on: {hints}.\n"
            "- Shorts titles must include #shorts.\n"
            "- thumbnail_text: 3-5 punchy words, e.g. 'DISCIPLINE IS FREEDOM'.\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"long_form": {"title": str, "description": str, "tags": [str], '
            '"category_id": "22", "thumbnail_text": str}, '
            '"shorts": [{"for_segments": [str], "title": str, "description": str, '
            '"tags": [str]}]}'
        )

    def run(self, concept: dict, script: dict, chapters: list[dict],
            shorts: list[dict], pd_attribution: str | None) -> MetadataOutput:
        task = (
            f"Concept:\n{json.dumps(concept, indent=2)}\n\n"
            f"Script segments (id, role, first words):\n"
            + json.dumps([{"id": s["id"], "role": s["role"],
                           "text": s["text"][:80]} for s in script["segments"]],
                         indent=2)
            + "\n\nChapter timestamps (use exactly):\n"
            + json.dumps([{"time": _fmt_ts(c["start_s"]), "hint": c["hint"]}
                          for c in chapters], indent=2)
            + "\n\nShorts to title (windows of the script):\n"
            + json.dumps(shorts, indent=2)
            + f"\n\nAttribution line to include: {pd_attribution or '(none)'}\n"
        )
        return self.run_json(task)
