"""Agent base class: system prompt + tool registry + logged tool-use runs.

Agents have NO tools that mutate the store, the supplier, or customer-facing
channels. Their single write path is ``propose_action``, which inserts a
pending row into the approvals table; executor.py performs approved actions.
That makes the human gate structural — no prompt can bypass it.
"""

from __future__ import annotations

import json

from ..config import AppConfig
from ..store import ACTION_TYPES, Approval, Store

APPROVAL_RULE = (
    "You cannot change the store, the supplier, or contact customers directly — "
    "every state-changing action must be submitted with the propose_action tool "
    "for human review. Propose one action per logical change, with a clear title "
    "and rationale the owner can evaluate at a glance."
)


class Agent:
    name: str = "agent"
    description: str = ""

    def __init__(self, ai, store: Store, cfg: AppConfig, shopify=None, cj=None):
        self.ai = ai
        self.store = store
        self.cfg = cfg
        self.shopify = shopify
        self.cj = cj

    # ---- subclass surface -------------------------------------------------

    def system_prompt(self) -> str:
        raise NotImplementedError

    def extra_tools(self) -> tuple[list[dict], dict]:
        """Per-agent (schemas, handlers) beyond the shared set."""
        return [], {}

    # ---- shared tools -----------------------------------------------------

    def shared_tools(self) -> tuple[list[dict], dict]:
        schemas = [
            {
                "name": "propose_action",
                "description": (
                    "Submit a state-changing action for human approval. This is the ONLY "
                    "way to change the store, order from the supplier, reply to a customer, "
                    "or publish marketing. Use it once per logical action, after you have "
                    "gathered everything needed to fill the payload exactly."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action_type": {"type": "string", "enum": sorted(ACTION_TYPES)},
                        "title": {"type": "string",
                                  "description": "One-line human summary of the action"},
                        "payload": {"type": "object",
                                    "description": "Exact arguments the executor will use"},
                        "rationale": {"type": "string",
                                      "description": "Why this action is worth approving"},
                        "ref_table": {"type": "string", "enum": ["", "products", "orders"]},
                        "ref_id": {"type": "integer",
                                   "description": "Local products/orders row id this refers to"},
                    },
                    "required": ["action_type", "title", "payload", "rationale"],
                },
            },
            {
                "name": "query_products",
                "description": ("List products in the local pipeline, optionally filtered by "
                                "status (candidate, shortlisted, drafted, listed, rejected). "
                                "Use to check what already exists before researching or drafting."),
                "input_schema": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                },
            },
            {
                "name": "query_orders",
                "description": ("List orders in the local pipeline, optionally filtered by "
                                "status (new, cj_proposed, cj_placed, shipped, delivered, "
                                "attention). Use to check order state before acting."),
                "input_schema": {
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                },
            },
        ]
        handlers = {
            "propose_action": self._propose_action,
            "query_products": lambda inp: self.store.list_products(inp.get("status") or None),
            "query_orders": lambda inp: self.store.list_orders(inp.get("status") or None),
        }
        return schemas, handlers

    def _propose_action(self, inp: dict) -> dict:
        approval_id = self.store.propose(Approval(
            action_type=inp["action_type"],
            agent=self.name,
            title=inp["title"],
            payload=inp["payload"],
            rationale=inp.get("rationale", ""),
            ref_table=inp.get("ref_table", ""),
            ref_id=inp.get("ref_id"),
        ))
        return {"approval_id": approval_id, "status": "pending",
                "note": "queued for human review; it will not execute until approved"}

    # ---- run --------------------------------------------------------------

    def tools(self) -> tuple[list[dict], dict]:
        schemas, handlers = self.shared_tools()
        extra_schemas, extra_handlers = self.extra_tools()
        return schemas + extra_schemas, {**handlers, **extra_handlers}

    def run(self, task: str):
        schemas, handlers = self.tools()
        system = f"{self.system_prompt()}\n\n{APPROVAL_RULE}"
        try:
            result = self.ai.run_tools(system, task, schemas, handlers,
                                       max_iterations=self.cfg.ai.max_tool_iterations)
        except Exception as exc:
            self.store.log_run(self.name, task, "error", str(exc)[:500])
            raise
        status = "ok" if not result.errors else "ok_with_tool_errors"
        summary = result.text[:1000]
        if result.errors:
            summary += "\n[tool errors] " + json.dumps(result.errors[:5])
        self.store.log_run(self.name, task, status, summary,
                           tool_calls=result.tool_calls,
                           input_tokens=result.input_tokens,
                           output_tokens=result.output_tokens)
        return result
