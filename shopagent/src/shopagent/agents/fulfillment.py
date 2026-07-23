"""Fulfillment agent: syncs Shopify orders, proposes supplier orders, tracks shipments.

Placing a CJ order costs real money, so it is always a proposed cj.create_order
action awaiting approval. Local order-state bookkeeping needs no approval.
"""

from __future__ import annotations

import json

from .base import Agent


class FulfillmentAgent(Agent):
    name = "fulfillment"
    description = "Monitors orders, proposes supplier fulfillment, tracks shipments."

    def system_prompt(self) -> str:
        return (
            "You are the fulfillment agent for a dropshipping business selling on "
            "two channels — a Shopify store and Amazon (FBM) — both fulfilled "
            "through CJ Dropshipping. Every order row has a 'channel' field "
            "('shopify' or 'amazon').\n"
            "Workflow each run:\n"
            "1. Call sync_shopify_orders and sync_amazon_orders to pull unfulfilled "
            "orders from both channels into the local pipeline.\n"
            "2. For each order with status 'new' (any channel): map its line items "
            "to CJ variants with map_line_items_to_cj. If every item maps, propose "
            "cj.create_order via propose_action with order_ref set to the order "
            "number, cj_items, the order's shipping address, and logistic_name "
            "'CJPacket Ordinary' (ref_table='orders', ref_id=local order id), then "
            "set the order's status to cj_proposed with update_order_status. If any "
            "item cannot be mapped, set status 'attention' with a note explaining "
            "what is unmappable instead.\n"
            "3. For each order with status 'cj_placed': call check_cj_order. When a "
            "tracking number first appears: (a) record it and set status 'shipped' "
            "with update_order_status, and (b) propose the confirmation action "
            "MATCHING THE ORDER'S CHANNEL — never both:\n"
            "   - channel 'shopify': propose shopify.fulfill_order with the order's "
            "shopify_order_id, the tracking number, notify_customer true.\n"
            "   - channel 'amazon': propose amazon.confirm_shipment with "
            "amazon_order_id (the order's external id), the tracking number, "
            "carrier_code 'Other', and order_items built from the order's line "
            "items ([{order_item_id, quantity}] — order_item_id is on each line "
            "item).\n"
            "   Both with ref_table='orders', ref_id=local order id, and only once "
            "per order: skip orders already 'shipped' or 'delivered'.\n"
            "4. For each order with status 'shipped': call check_cj_order and set "
            "status 'delivered' when CJ reports delivery.\n"
            "Never propose a CJ order twice for the same order — skip orders whose "
            "status is not 'new'. Finish with a summary: orders synced per channel, "
            "proposals made, tracking updates, and anything needing attention."
        )

    def extra_tools(self):
        schemas = [
            {
                "name": "sync_shopify_orders",
                "description": ("Pull unfulfilled orders from the Shopify store into the local "
                                "pipeline. Always call this first. Returns the local orders."),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "sync_amazon_orders",
                "description": ("Pull unshipped Amazon (FBM) orders into the local pipeline "
                                "with channel='amazon'. Call once per run alongside "
                                "sync_shopify_orders."),
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "map_line_items_to_cj",
                "description": ("Map a local order's line items to CJ variant ids using the "
                                "product pipeline (matched by SKU/variant). Returns cj_items "
                                "plus any unmapped items."),
                "input_schema": {
                    "type": "object",
                    "properties": {"order_id": {"type": "integer"}},
                    "required": ["order_id"],
                },
            },
            {
                "name": "check_cj_order",
                "description": "Get current CJ status and tracking number for a placed order.",
                "input_schema": {
                    "type": "object",
                    "properties": {"cj_order_id": {"type": "string"}},
                    "required": ["cj_order_id"],
                },
            },
            {
                "name": "update_order_status",
                "description": ("Update a local order's status (new, cj_proposed, cj_placed, "
                                "shipped, delivered, attention), optionally recording a tracking "
                                "number or a note. Local bookkeeping only."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "integer"},
                        "status": {"type": "string"},
                        "tracking_number": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["order_id", "status"],
                },
            },
        ]
        handlers = {
            "sync_shopify_orders": self._sync_orders,
            "sync_amazon_orders": self._sync_amazon_orders,
            "map_line_items_to_cj": self._map_line_items,
            "check_cj_order": lambda inp: self.cj.get_order_status(inp["cj_order_id"]),
            "update_order_status": self._update_status,
        }
        return schemas, handlers

    def _upsert_channel_orders(self, orders: list[dict], channel: str) -> None:
        for order in orders:
            self.store.upsert_order(
                order["id"],
                channel=channel,
                order_number=order.get("name", ""),
                customer_email=order.get("email", ""),
                line_items_json=json.dumps(order.get("lineItems", [])),
                shipping_address_json=json.dumps(order.get("shippingAddress") or {}),
            )

    def _sync_orders(self, inp: dict) -> list[dict]:
        self._upsert_channel_orders(self.shopify.list_open_orders(), "shopify")
        return self.store.list_orders()

    def _sync_amazon_orders(self, inp: dict):
        if self.amazon is None:
            return {"note": "Amazon channel not configured; nothing synced"}
        self._upsert_channel_orders(self.amazon.list_unshipped_orders(), "amazon")
        return self.store.list_orders()

    def _map_line_items(self, inp: dict) -> dict:
        order = self.store.get_order(inp["order_id"])
        if order is None:
            return {"error": f"no order {inp['order_id']}"}
        by_vid = {p["cj_vid"]: p for p in self.store.list_products() if p["cj_vid"]}
        by_name = {p["name"].lower(): p for p in self.store.list_products()}
        cj_items, unmapped = [], []
        for item in json.loads(order["line_items_json"]):
            sku = item.get("sku", "")
            product = by_vid.get(sku) or by_name.get(item.get("title", "").lower())
            vid = sku if sku in by_vid else (product or {}).get("cj_vid", "")
            if vid:
                cj_items.append({"vid": vid, "quantity": item.get("quantity", 1)})
            else:
                unmapped.append(item.get("title", "?"))
        return {"order_id": inp["order_id"],
                "shipping_address": json.loads(order["shipping_address_json"]),
                "cj_items": cj_items, "unmapped": unmapped}

    def _update_status(self, inp: dict) -> dict:
        fields: dict = {"status": inp["status"]}
        if inp.get("tracking_number"):
            fields["tracking_number"] = inp["tracking_number"]
        if inp.get("note"):
            fields["notes"] = inp["note"]
        self.store.update_order(inp["order_id"], **fields)
        return {"order_id": inp["order_id"], "status": inp["status"]}
