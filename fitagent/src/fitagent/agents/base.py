"""Agent base: JSON-contract agents driven by the deterministic pipeline.

Unlike shopagent (open-ended tool loops writing to an approval queue), most
fitagent agents are pure functions: one prompt in, one validated pydantic
contract out. On a validation failure the error is fed back once so the
model can correct itself. Every call is logged to agent_runs.

The publish gate stays structural anyway: agents produce artifacts, only
executor.py (behind CLI approval) can touch YouTube.
"""

from __future__ import annotations

import json

import pydantic

from ..config import AppConfig, PresetConfig
from ..store import Store


class AgentOutputError(RuntimeError):
    pass


class JSONAgent:
    name: str = "agent"
    output_model: type[pydantic.BaseModel]

    def __init__(self, ai, store: Store, cfg: AppConfig, preset: PresetConfig):
        self.ai = ai
        self.store = store
        self.cfg = cfg
        self.preset = preset

    def system_prompt(self) -> str:
        raise NotImplementedError

    def run_json(self, task: str, retries: int = 2) -> pydantic.BaseModel:
        system = self.system_prompt()
        prompt = task
        last_error = ""
        for attempt in range(retries + 1):
            try:
                raw = self.ai.complete_json(system, prompt)
                result = self.output_model.model_validate(raw)
            except Exception as exc:
                last_error = str(exc)[:800]
                prompt = (
                    f"{task}\n\nYour previous response was invalid:\n{last_error}\n"
                    "Return ONLY a corrected JSON object matching the required schema."
                )
                continue
            self.store.log_run(self.name, task[:300], "ok",
                               json.dumps(raw, default=str)[:1000])
            return result
        self.store.log_run(self.name, task[:300], "error", last_error)
        raise AgentOutputError(
            f"{self.name} failed to produce valid output after "
            f"{retries + 1} attempts: {last_error}")

    def channel_context(self) -> str:
        return (
            f"Channel: {self.preset.channel_name}\n"
            f"Niche: {self.preset.niche}\n"
            f"Tone: {self.preset.tone}\n"
            f"Audience: {self.preset.audience}"
        )
