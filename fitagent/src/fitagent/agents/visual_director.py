"""Visual director agent: maps script segments to a stock-footage shot plan.

The one tool-loop agent — it probes real (or mock) stock searches so every
planned shot is backed by actual results, then submits the plan through a
validating tool. The plan is consumed deterministically by media/footage.py."""

from __future__ import annotations

import json

from .base import AgentOutputError, JSONAgent
from .contracts import ShotPlanOutput


class VisualDirectorAgent(JSONAgent):
    name = "visual_director"
    output_model = ShotPlanOutput

    def __init__(self, ai, store, cfg, preset, stock_clients: list):
        super().__init__(ai, store, cfg, preset)
        self.stock_clients = stock_clients
        self._plan: ShotPlanOutput | None = None

    def system_prompt(self) -> str:
        providers = ", ".join(c.provider for c in self.stock_clients)
        return (
            "You are the visual director for a men's fitness motivation YouTube "
            "channel: dark cinematic b-roll matched to a voiceover script.\n\n"
            f"{self.channel_context()}\n\n"
            f"Available stock footage providers: {providers}.\n\n"
            "For EVERY script segment, plan 1-3 shots. Craft search queries the "
            "way stock libraries index footage: subject + setting + look, e.g. "
            "'man training alone dark gym', 'boxer wrapping hands slow motion', "
            "'rain city street night'. Verify queries with the search_stock tool "
            "and pick a specific clip_id from the results for each shot. Give "
            "every shot 2 fallback_queries in case the clip fails to download. "
            "Don't reuse a clip_id across shots. Assign each segment a mood: "
            "gritty, dark, epic, or calm.\n\n"
            "When the plan covers every segment, submit it ONCE with "
            "submit_shot_plan, then stop."
        )

    # ------------------------------------------------------------------ tools

    def _tools(self) -> tuple[list[dict], dict]:
        schemas = [
            {
                "name": "search_stock",
                "description": ("Search the stock footage providers. Returns up to "
                                "8 clips with id, provider, duration, and size. "
                                "Metadata only — nothing is downloaded."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "orientation": {"type": "string",
                                        "enum": ["landscape", "portrait"]},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "submit_shot_plan",
                "description": ("Submit the final shot plan for the whole script. "
                                "Call exactly once, after verifying queries."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "shot_plan": {"type": "array", "items": {
                            "type": "object",
                            "properties": {
                                "segment_id": {"type": "string"},
                                "mood": {"type": "string",
                                         "enum": ["gritty", "dark", "epic", "calm"]},
                                "shots": {"type": "array", "items": {
                                    "type": "object",
                                    "properties": {
                                        "query": {"type": "string"},
                                        "provider": {"type": "string"},
                                        "clip_id": {"type": "string"},
                                        "fallback_queries": {"type": "array",
                                                             "items": {"type": "string"}},
                                        "target_seconds": {"type": "number"},
                                    },
                                    "required": ["query"],
                                }},
                            },
                            "required": ["segment_id", "shots"],
                        }},
                        "reuse_notes": {"type": "string"},
                    },
                    "required": ["shot_plan"],
                },
            },
        ]
        handlers = {"search_stock": self._search_stock,
                    "submit_shot_plan": self._submit_plan}
        return schemas, handlers

    def _search_stock(self, inp: dict) -> list[dict]:
        results = []
        for client in self.stock_clients:
            try:
                for clip in client.search(inp["query"],
                                          orientation=inp.get("orientation", "landscape"),
                                          per_page=8):
                    results.append({"provider": clip.provider, "clip_id": clip.clip_id,
                                    "duration_s": clip.duration_s,
                                    "width": clip.width, "height": clip.height})
            except Exception as exc:
                results.append({"provider": client.provider, "error": str(exc)[:200]})
        return results[:16]

    def _submit_plan(self, inp: dict) -> dict:
        self._plan = ShotPlanOutput.model_validate(inp)
        return {"accepted": True, "segments_planned": len(self._plan.shot_plan)}

    # -------------------------------------------------------------------- run

    def run(self, segments: list[dict]) -> ShotPlanOutput:
        self._plan = None
        brief = [{"id": s["id"], "visual_theme": s.get("visual_theme", ""),
                  "energy": s.get("energy", 3), "text": s["text"][:120]}
                 for s in segments]
        task = ("Plan shots for these script segments:\n"
                + json.dumps(brief, indent=2))
        schemas, handlers = self._tools()
        result = self.ai.run_tools(self.system_prompt(), task, schemas, handlers,
                                   max_iterations=self.cfg.ai.max_tool_iterations)
        status = "ok" if self._plan is not None else "error"
        self.store.log_run(self.name, f"plan {len(segments)} segments", status,
                           result.text[:800], tool_calls=result.tool_calls,
                           input_tokens=result.input_tokens,
                           output_tokens=result.output_tokens)
        if self._plan is None:
            raise AgentOutputError(
                "visual director finished without submitting a shot plan "
                f"(stopped on {result.stopped_on})")
        return self._plan
