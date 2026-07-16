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
    def __init__(self, store: Store, cfg: AppConfig, shopify, cj):
        self.store = store
        self.cfg = cfg
        self.shopify = shopify
        self.cj = cj
        self._dispatch = {
            "shopify.create_product": self._shopify_create_product,
            "shopify.update_product": self._shopify_update_product,
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
        result = self.shopify.create_product(
            title=p["title"], description_html=p["description_html"],
            tags=p["tags"], price=str(p["price"]), vendor=p.get("vendor", ""),
        )
        if approval.ref_table == "products" and approval.ref_id:
            self.store.update_product(approval.ref_id,
                                      shopify_product_id=result["id"], status="listed")
        return result

    def _shopify_update_product(self, approval: Approval) -> dict:
        p = approval.payload
        return self.shopify.update_product(p["shopify_product_id"], p["fields"])

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
        path.write_text(content)
        return path
