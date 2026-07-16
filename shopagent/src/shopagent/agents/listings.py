"""Listings agent: turns shortlisted products into Shopify-ready listings.

Drafts are stored locally; going live is a proposed shopify.create_product
action that awaits human approval.
"""

from __future__ import annotations

import json

from .base import Agent


class ListingsAgent(Agent):
    name = "listings"
    description = "Writes SEO product listings and proposes them for the store."

    def system_prompt(self) -> str:
        return (
            "You are the listings agent for a Shopify dropshipping store. For each "
            "shortlisted product in the pipeline:\n"
            "1. Fetch it with get_candidate.\n"
            "2. Write a listing: a benefit-led SEO title (under 70 characters), "
            "persuasive HTML description (2-3 short paragraphs plus a bullet list "
            "of concrete benefits, honest — no invented specs or fake reviews), "
            "and 5-8 search tags.\n"
            "3. Save it with save_listing_draft.\n"
            "4. Propose it for the live store with propose_action "
            "(shopify.create_product), using the draft values and the product's "
            "proposed_price. Set ref_table='products' and ref_id to the product id.\n"
            "Use the stored proposed_price unless it ends oddly — you may round to "
            "a cleaner .99 price, never below it. Finish with a summary of listings "
            "drafted and proposed."
        )

    def extra_tools(self):
        schemas = [
            {
                "name": "get_candidate",
                "description": "Fetch one pipeline product by id, including supplier details.",
                "input_schema": {
                    "type": "object",
                    "properties": {"product_id": {"type": "integer"}},
                    "required": ["product_id"],
                },
            },
            {
                "name": "save_listing_draft",
                "description": ("Save the drafted listing onto the pipeline product and mark it "
                                "drafted. Do this before proposing the product for the store."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "description_html": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "price": {"type": "number"},
                    },
                    "required": ["product_id", "title", "description_html", "tags", "price"],
                },
            },
        ]
        handlers = {
            "get_candidate":
                lambda inp: self.store.get_product(inp["product_id"]) or {"error": "not found"},
            "save_listing_draft": self._save_listing_draft,
        }
        return schemas, handlers

    def _save_listing_draft(self, inp: dict) -> dict:
        product = self.store.get_product(inp["product_id"])
        if product is None:
            return {"saved": False, "reason": f"no product {inp['product_id']}"}
        listing = {"title": inp["title"], "description_html": inp["description_html"],
                   "tags": inp["tags"], "price": inp["price"]}
        self.store.update_product(inp["product_id"],
                                  listing_json=json.dumps(listing), status="drafted")
        return {"saved": True, "product_id": inp["product_id"], "status": "drafted"}
