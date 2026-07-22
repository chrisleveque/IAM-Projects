"""Amazon listing agent: cross-lists pipeline products onto the Amazon channel.

Takes products already listed (or drafted) for the Shopify store that have no
Amazon presence yet, writes Amazon-optimized copy, pre-validates the payload
with Amazon's non-persisting validation mode, and proposes amazon.create_listing
for human approval. Going live is always an approved action.
"""

from __future__ import annotations

import json

from .base import Agent


class AmazonListingAgent(Agent):
    name = "amazon"
    description = "Cross-lists pipeline products onto Amazon (FBM)."

    def system_prompt(self) -> str:
        amz = self.cfg.amazon
        return (
            "You are the Amazon listing agent for a dropshipping business that "
            "also runs a Shopify store. Your job: cross-list pipeline products "
            "(status listed or drafted, empty amazon_status) onto Amazon as "
            "merchant-fulfilled (FBM) listings.\n"
            "For each product:\n"
            "1. Fetch it with get_candidate.\n"
            "2. Find the right productType with search_product_types (use words "
            "from the product name/category; never guess type names).\n"
            "3. Build the attributes object. Amazon copy rules: title under 200 "
            "characters, no promotional phrases or ALL CAPS; exactly 5 concise "
            "benefit-led bullet_point entries; plain-text product_description; "
            "honest content only — never invent specs. Structure (every value is "
            "a list of objects, marketplace-scoped fields include marketplace_id "
            f"'{amz.marketplace_id}'):\n"
            "   item_name [{value}], brand [{value: 'Generic'}], "
            "bullet_point x5 [{value}], product_description [{value}], "
            "condition_type [{value: 'new_new'}], "
            "purchasable_offer [{marketplace_id, currency: 'USD', our_price: "
            "[{schedule: [{value_with_tax: <price>}]}]}], "
            "fulfillment_availability [{fulfillment_channel_code: 'DEFAULT', "
            f"quantity: {amz.default_quantity}, lead_time_to_ship_max_days: "
            f"{amz.lead_time_days}}}], "
            "supplier_declared_has_product_identifier_exemption [{value: true}], "
            "main_product_image_locator [{marketplace_id, media_location: <url>}] "
            "plus other_product_image_locator_1.. for extra images from the "
            "product's images_json.\n"
            "4. Use the product's proposed_price (you may round up to a cleaner "
            ".99, never below). The SKU MUST be exactly the product's cj_vid — "
            "that is what links Amazon orders back to the supplier.\n"
            "5. Pre-check with validate_listing. If it returns issues, fix the "
            "attributes and validate again (up to 2 retries); report issues you "
            "cannot fix instead of guessing.\n"
            "6. Set the product's amazon status with mark_amazon_status "
            "('proposed'), then submit via propose_action (amazon.create_listing, "
            "ref_table='products', ref_id=product id) with payload {sku, "
            "product_type, attributes}.\n"
            "Finish with a summary of listings proposed and any blockers."
        )

    def extra_tools(self):
        schemas = [
            {
                "name": "get_candidate",
                "description": ("Fetch one pipeline product by id, including listing copy, "
                                "price, images_json, and cj_vid (the required Amazon SKU)."),
                "input_schema": {
                    "type": "object",
                    "properties": {"product_id": {"type": "integer"}},
                    "required": ["product_id"],
                },
            },
            {
                "name": "search_product_types",
                "description": ("Search Amazon's product type registry by keywords. Always "
                                "use a returned name; guessed productType values are rejected."),
                "input_schema": {
                    "type": "object",
                    "properties": {"keywords": {"type": "string"}},
                    "required": ["keywords"],
                },
            },
            {
                "name": "validate_listing",
                "description": ("Validate a listing payload against Amazon's rules WITHOUT "
                                "creating anything (VALIDATION_PREVIEW). Always run this "
                                "before proposing; returns issues to fix."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "sku": {"type": "string"},
                        "product_type": {"type": "string"},
                        "attributes": {"type": "object"},
                    },
                    "required": ["sku", "product_type", "attributes"],
                },
            },
            {
                "name": "mark_amazon_status",
                "description": ("Record the product's Amazon channel status locally "
                                "(proposed, blocked). Local bookkeeping only."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "product_id": {"type": "integer"},
                        "status": {"type": "string", "enum": ["proposed", "blocked"]},
                        "note": {"type": "string"},
                    },
                    "required": ["product_id", "status"],
                },
            },
        ]
        handlers = {
            "get_candidate":
                lambda inp: self.store.get_product(inp["product_id"]) or {"error": "not found"},
            "search_product_types":
                lambda inp: self.amazon.search_product_types(inp["keywords"]),
            "validate_listing":
                lambda inp: self.amazon.validate_listing(
                    inp["sku"], inp["product_type"], inp["attributes"]),
            "mark_amazon_status": self._mark_status,
        }
        return schemas, handlers

    def _mark_status(self, inp: dict) -> dict:
        product = self.store.get_product(inp["product_id"])
        if product is None:
            return {"error": f"no product {inp['product_id']}"}
        fields = {"amazon_status": inp["status"]}
        if inp.get("note"):
            fields["notes"] = (product.get("notes") or "") + f" | amazon: {inp['note']}"
        self.store.update_product(inp["product_id"], **fields)
        return {"product_id": inp["product_id"], "amazon_status": inp["status"]}
