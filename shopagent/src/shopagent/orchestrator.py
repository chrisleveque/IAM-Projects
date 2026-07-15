"""Deterministic pipeline coordinator for the agent team.

The orchestrator is plain Python — which agent runs, in what order, and with
what task is decided here, not by an LLM. Each agent invocation is an LLM
tool-use loop; a failure in one step is recorded and the pipeline continues.
"""

from __future__ import annotations

from .agents.fulfillment import FulfillmentAgent
from .agents.listings import ListingsAgent
from .agents.marketing import MarketingAgent
from .agents.research import ResearchAgent
from .agents.support import SupportAgent
from .config import AppConfig
from .store import Store

AGENTS = {
    "research": ResearchAgent,
    "listings": ListingsAgent,
    "fulfillment": FulfillmentAgent,
    "support": SupportAgent,
    "marketing": MarketingAgent,
}


class Orchestrator:
    def __init__(self, ai, store: Store, cfg: AppConfig, shopify, cj):
        self.ai = ai
        self.store = store
        self.cfg = cfg
        self.shopify = shopify
        self.cj = cj

    def agent(self, name: str):
        cls = AGENTS[name]
        return cls(self.ai, self.store, self.cfg, shopify=self.shopify, cj=self.cj)

    def run_task(self, agent_name: str, task: str):
        return self.agent(agent_name).run(task)

    def _next_niche(self) -> str:
        """Rotate niches: pick the one with the fewest pipeline products."""
        niches = self.cfg.business.niches or ["general"]
        counts = {n: 0 for n in niches}
        for p in self.store.list_products():
            if p["niche"] in counts:
                counts[p["niche"]] += 1
        return min(niches, key=lambda n: counts[n])

    def run_daily(self) -> dict:
        """Fulfillment -> support -> research (if pool is low) -> listings ->
        marketing (if anything is newly listed). Returns a step-by-step summary."""
        summary: dict = {"steps": [], "pending_approvals": 0}

        def step(name: str, task: str, skip_reason: str | None = None):
            if skip_reason:
                summary["steps"].append({"agent": name, "skipped": skip_reason})
                return
            try:
                result = self.run_task(name, task)
                summary["steps"].append({"agent": name, "ok": True,
                                         "tool_calls": result.tool_calls,
                                         "summary": result.text[:300]})
            except Exception as exc:
                summary["steps"].append({"agent": name, "ok": False, "error": str(exc)[:300]})

        step("fulfillment",
             "Run your standard workflow: sync store orders, propose CJ orders for "
             "new ones, and update tracking for placed ones.")

        step("support", "Handle every message currently in the inbox.")

        shortlisted = self.store.list_products("shortlisted")
        pool = len(shortlisted) + len(self.store.list_products("candidate"))
        if pool < self.cfg.business.min_candidate_pool:
            niche = self._next_niche()
            step("research",
                 f"Research the '{niche}' niche and save up to "
                 f"{self.cfg.business.max_new_products_per_run} strong candidates.")
            shortlisted = self.store.list_products("shortlisted")
        else:
            step("research", "", skip_reason=f"candidate pool is {pool}, above threshold")

        if shortlisted:
            ids = ", ".join(str(p["id"]) for p in shortlisted)
            step("listings",
                 f"Draft listings for shortlisted product ids: {ids}, and propose "
                 "each for the store.")
        else:
            step("listings", "", skip_reason="nothing shortlisted")

        listed = self.store.list_products("listed")
        if listed:
            step("marketing",
                 "Draft social, email, and ad content for the currently listed products.")
        else:
            step("marketing", "", skip_reason="nothing listed yet")

        summary["pending_approvals"] = len(self.store.list_approvals("pending"))
        return summary
