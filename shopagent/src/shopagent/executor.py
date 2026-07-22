"""Executes approved actions against the real integrations.

This is the only code path that mutates the store, the supplier, or produces
customer-facing output — and it only runs on approvals whose status is
'approved' (set by a human via `shopagent approvals approve`). On success it
writes results back onto the linked pipeline rows; on failure the approval is
marked failed and can be retried.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .config import AppConfig
from .store import Approval, Store


class Executor:
    def __init__(self, store: Store, cfg: AppConfig, shopify, cj, amazon=None):
        self.store = store
        self.cfg = cfg
        self.shopify = shopify
        self.cj = cj
        self.amazon = amazon
        self._dispatch = {
            "shopify.create_product": self._shopify_create_product,
            "shopify.update_product": self._shopify_update_product,
            "shopify.fulfill_order": self._shopify_fulfill_order,
            "amazon.create_listing": self._amazon_create_listing,
            "amazon.update_price": self._amazon_update_price,
            "amazon.confirm_shipment": self._amazon_confirm_shipment,
            "cj.create_order": self._cj_create_order,
            "support.send_reply": self._support_send_reply,
            "marketing.publish": self._marketing_publish,
        }

    def execute(self, approval_id: int) -> Approval:
        approval = self.store.get_approval(approval_id)
        if approval is None:
            raise ValueError(f"no approval with id {approval_id}")
        if approval.status != "approved":
            raise ValueError(
                f"approval #{approval_id} is {approval.status}; only approved "
                "actions can be executed"
            )
        handler = self._dispatch[approval.action_type]
        try:
            result = handler(approval)
        except Exception as exc:
            self.store.mark_failed(approval_id, str(exc)[:1000])
            return self.store.get_approval(approval_id)
        self.store.mark_executed(approval_id, json.dumps(result, default=str))
        return self.store.get_approval(approval_id)

    # ------------------------------------------------------------- handlers

    def _shopify_create_product(self, approval: Approval) -> dict:
        p = approval.payload
        # attach supplier photos saved on the linked pipeline product, so the
        # store listing never goes up imageless (payload may override)
        image_urls = p.get("image_urls")
        if not image_urls and approval.ref_table == "products" and approval.ref_id:
            product = self.store.get_product(approval.ref_id)
            if product and product.get("images_json"):
                image_urls = json.loads(product["images_json"])
        result = self.shopify.create_product(
            title=p["title"], description_html=p["description_html"],
            tags=p["tags"], price=str(p["price"]), vendor=p.get("vendor", ""),
            image_urls=image_urls or [],
        )
        result["images_attached"] = len(image_urls or [])
        if approval.ref_table == "products" and approval.ref_id:
            self.store.update_product(approval.ref_id,
                                      shopify_product_id=result["id"], status="listed")
        return result

    def _shopify_update_product(self, approval: Approval) -> dict:
        p = approval.payload
        return self.shopify.update_product(p["shopify_product_id"], p["fields"])

    def _shopify_fulfill_order(self, approval: Approval) -> dict:
        p = approval.payload
        result = self.shopify.fulfill_order(
            p["shopify_order_id"], p["tracking_number"],
            tracking_company=p.get("tracking_company", "CJPacket"),
            notify_customer=p.get("notify_customer", True),
        )
        if approval.ref_table == "orders" and approval.ref_id:
            self.store.update_order(approval.ref_id, status="shipped",
                                    tracking_number=p["tracking_number"])
        return result

    def _require_amazon(self):
        if self.amazon is None:
            raise RuntimeError("Amazon client not configured for this executor")
        return self.amazon

    def _amazon_create_listing(self, approval: Approval) -> dict:
        p = approval.payload
        result = self._require_amazon().put_listing(
            p["sku"], p["product_type"], p["attributes"])
        if approval.ref_table == "products" and approval.ref_id:
            self.store.update_product(
                approval.ref_id, amazon_sku=p["sku"],
                amazon_submission_id=result.get("submission_id", ""),
                amazon_status="submitted")
        return result

    def _amazon_update_price(self, approval: Approval) -> dict:
        p = approval.payload
        return self._require_amazon().update_price(
            p["sku"], p["product_type"], float(p["price"]))

    def _amazon_confirm_shipment(self, approval: Approval) -> dict:
        p = approval.payload
        result = self._require_amazon().confirm_shipment(
            p["amazon_order_id"], p["tracking_number"],
            carrier_code=p.get("carrier_code", self.cfg.amazon.carrier_default),
            carrier_name=p.get("carrier_name", self.cfg.amazon.carrier_name_default),
            order_items=p["order_items"],
        )
        if approval.ref_table == "orders" and approval.ref_id:
            self.store.update_order(approval.ref_id, status="shipped",
                                    tracking_number=p["tracking_number"])
        return result

    def _cj_create_order(self, approval: Approval) -> dict:
        p = approval.payload
        result = self.cj.create_order(
            order_ref=p["order_ref"], cj_items=p["cj_items"],
            shipping_address=p["shipping_address"], logistic_name=p["logistic_name"],
        )
        if approval.ref_table == "orders" and approval.ref_id:
            self.store.update_order(approval.ref_id,
                                    cj_order_id=result["cj_order_id"], status="cj_placed")
        return result

    def _support_send_reply(self, approval: Approval) -> dict:
        p = approval.payload
        path = self._write_output("replies", p["subject"],
                                  f"To: {p['customer_email']}\n"
                                  f"Subject: {p['subject']}\n\n{p['body']}\n")
        return {"written_to": str(path),
                "note": "copy-ready reply file; sending email is manual in v1"}

    def _marketing_publish(self, approval: Approval) -> dict:
        p = approval.payload
        path = self._write_output(f"marketing/{p['channel']}", p["title"],
                                  f"# {p['title']}\n\n{p['body']}\n")
        return {"written_to": str(path),
                "note": "copy-ready content file; posting is manual in v1"}

    def _write_output(self, subdir: str, name: str, content: str):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "untitled"
        out_dir = self.cfg.output_dir / subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{stamp}_{slug}.md"
        # explicit utf-8: Windows defaults to cp1252, which chokes on emoji
        path.write_text(content, encoding="utf-8")
        return path
