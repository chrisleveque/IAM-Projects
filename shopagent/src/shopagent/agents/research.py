"""Research agent: finds supplier products worth selling and saves candidates.

Externally read-only — its output is local products rows (candidate /
shortlisted), so nothing here needs approval.
"""

from __future__ import annotations

import json

from .base import Agent


def proposed_retail(supplier_cost: float, markup: float) -> float:
    """Retail price from landed cost: multiply, then round up to x.99."""
    raw = supplier_cost * markup
    return max(round(int(raw) + 0.99, 2), 4.99)


class ResearchAgent(Agent):
    name = "research"
    description = "Finds and evaluates supplier products worth selling."

    def system_prompt(self) -> str:
        pricing = self.cfg.business.pricing
        return (
            "You are the product research agent for a Shopify dropshipping store. "
            "Given a niche, search the supplier catalog, evaluate candidates on "
            "price, shipping cost, and how compelling they are for impulse online "
            "purchase, and save the promising ones with save_candidate.\n"
            f"- Target retail is supplier cost x {pricing.markup_multiplier} "
            "(save_candidate computes this for you).\n"
            f"- Skip products whose margin (retail - cost - shipping) would fall "
            f"below ${pricing.min_margin_usd:.2f}.\n"
            "- Prefer lightweight products with reasonable shipping quotes.\n"
            "- Catalog prices can be a range across variants (sell_price is the "
            "low end, sell_price_max the high end). Confirm the real cost with "
            "get_supplier_product, and when in doubt evaluate margin against the "
            "higher figure so you never overstate profitability.\n"
            "- Mark only the strongest finds as shortlist=true; save decent "
            "runners-up as plain candidates.\n"
            "Finish with a short summary of what you saved and why."
        )

    def extra_tools(self):
        schemas = [
            {
                "name": "search_supplier_products",
                "description": ("Search the supplier catalog by keyword. Use the niche and "
                                "close variations of it. Returns pid, name, and cost."),
                "input_schema": {
                    "type": "object",
                    "properties": {"keyword": {"type": "string"}},
                    "required": ["keyword"],
                },
            },
            {
                "name": "get_supplier_product",
                "description": "Fetch full details (including variant id) for one supplier product.",
                "input_schema": {
                    "type": "object",
                    "properties": {"pid": {"type": "string"}},
                    "required": ["pid"],
                },
            },
            {
                "name": "estimate_shipping",
                "description": ("Get the cheapest freight quote for one unit of a variant to "
                                "the store's target country. Call before saving a candidate."),
                "input_schema": {
                    "type": "object",
                    "properties": {"vid": {"type": "string"}},
                    "required": ["vid"],
                },
            },
            {
                "name": "save_candidate",
                "description": ("Save an evaluated product into the local pipeline. Computes the "
                                "proposed retail price from the configured markup. Set "
                                "shortlist=true only for products you would list this week."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pid": {"type": "string"},
                        "vid": {"type": "string"},
                        "name": {"type": "string"},
                        "niche": {"type": "string"},
                        "supplier_price": {"type": "number"},
                        "shipping_estimate": {"type": "number"},
                        "shortlist": {"type": "boolean"},
                        "notes": {"type": "string",
                                  "description": "Why this product is (or isn't) strong"},
                    },
                    "required": ["pid", "vid", "name", "niche", "supplier_price",
                                 "shipping_estimate"],
                },
            },
        ]
        handlers = {
            "search_supplier_products":
                lambda inp: self.cj.search_products(inp["keyword"]),
            "get_supplier_product":
                lambda inp: self.cj.get_product(inp["pid"]) or {"error": "not found"},
            "estimate_shipping":
                lambda inp: self.cj.freight_calculate(
                    inp["vid"], 1, self.cfg.supplier.ship_to_country),
            "save_candidate": self._save_candidate,
        }
        return schemas, handlers

    def _save_candidate(self, inp: dict) -> dict:
        pricing = self.cfg.business.pricing
        price = proposed_retail(inp["supplier_price"], pricing.markup_multiplier)
        margin = price - inp["supplier_price"] - inp["shipping_estimate"]
        if margin < pricing.min_margin_usd:
            return {"saved": False,
                    "reason": f"margin ${margin:.2f} below minimum "
                              f"${pricing.min_margin_usd:.2f} at retail ${price:.2f}"}
        # grab supplier photos so listings can carry real product images;
        # non-fatal if the lookup fails
        try:
            details = self.cj.get_product(inp["pid"]) or {}
            images = details.get("images", [])
        except Exception:
            images = []
        product_id = self.store.upsert_product(
            inp["pid"], inp["name"],
            cj_vid=inp["vid"], niche=inp.get("niche", ""),
            supplier_price=inp["supplier_price"],
            shipping_estimate=inp["shipping_estimate"],
            proposed_price=price, notes=inp.get("notes", ""),
            images_json=json.dumps(images),
        )
        if inp.get("shortlist"):
            self.store.update_product(product_id, status="shortlisted")
        return {"saved": True, "product_id": product_id, "proposed_price": price,
                "margin": round(margin, 2),
                "status": "shortlisted" if inp.get("shortlist") else "candidate"}
