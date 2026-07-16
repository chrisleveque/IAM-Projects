"""Marketing agent: drafts promotional content for listed products.

Every artifact is a proposed marketing.publish action; on approval the
executor writes it to output/marketing/ for the owner to post.
"""

from __future__ import annotations

import json

from .base import Agent


class MarketingAgent(Agent):
    name = "marketing"
    description = "Drafts social, email, and ad copy for listed products."

    def system_prompt(self) -> str:
        return (
            "You are the marketing agent for a Shopify dropshipping store.\n"
            "For the listed products you're asked about (or all listed products if "
            "not specified), draft promotional content and submit each piece with "
            "propose_action (marketing.publish):\n"
            "- channel 'social': a short scroll-stopping caption with 3-5 hashtags.\n"
            "- channel 'email': a promo email (subject in the title field, body in "
            "the body field).\n"
            "- channel 'ad': primary ad text plus a headline, clearly labeled.\n"
            "Ground every claim in the product's actual listing copy — no invented "
            "discounts, reviews, or scarcity. One propose_action per artifact, with "
            "ref_table='products' and ref_id set. Finish with a summary of what you "
            "drafted."
        )

    def extra_tools(self):
        schemas = [
            {
                "name": "get_listed_products",
                "description": ("Fetch products live on the store (status 'listed'), including "
                                "their listing copy to ground the marketing content in."),
                "input_schema": {
                    "type": "object",
                    "properties": {"product_id": {"type": "integer",
                                                  "description": "Optional: one product only"}},
                },
            },
        ]
        return schemas, {"get_listed_products": self._get_listed}

    def _get_listed(self, inp: dict) -> list[dict]:
        products = self.store.list_products("listed")
        if inp.get("product_id"):
            products = [p for p in products if p["id"] == inp["product_id"]]
        out = []
        for p in products:
            listing = json.loads(p["listing_json"]) if p["listing_json"] else {}
            out.append({"id": p["id"], "name": p["name"], "niche": p["niche"],
                        "price": p["proposed_price"], "listing": listing})
        return out
