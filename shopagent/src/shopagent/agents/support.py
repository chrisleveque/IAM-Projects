"""Support agent: reads the inbox, looks up real order state, drafts replies.

The inbox is a directory of plain-text message files (v1). Replies are
proposed support.send_reply actions; on approval the executor writes a
copy-ready reply file to output/replies/ — nothing is emailed automatically.
"""

from __future__ import annotations

from .base import Agent


class SupportAgent(Agent):
    name = "support"
    description = "Drafts customer support replies grounded in real order status."

    def system_prompt(self) -> str:
        return (
            "You are the customer support agent for a Shopify dropshipping store.\n"
            "Each run: list the inbox, read every message, and draft a reply for "
            "each with propose_action (support.send_reply).\n"
            "- For order questions, look the order up first with lookup_order and "
            "answer with the real status and tracking number. Never invent "
            "shipping dates or tracking info; if you don't have it, say the order "
            "is being processed and support will follow up.\n"
            "- Typical dropshipping delivery is 8-15 business days — set honest "
            "expectations.\n"
            "- Tone: warm, concise, professional. Sign as 'The Store Team'.\n"
            "- For product questions, answer from the product pipeline data if "
            "available; do not fabricate specifications.\n"
            "Finish with a summary of messages handled and replies proposed."
        )

    def extra_tools(self):
        schemas = [
            {
                "name": "list_inbox",
                "description": "List unhandled customer message files in the inbox.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "read_message",
                "description": "Read one customer message by filename.",
                "input_schema": {
                    "type": "object",
                    "properties": {"filename": {"type": "string"}},
                    "required": ["filename"],
                },
            },
            {
                "name": "lookup_order",
                "description": ("Find a customer's order by order number (e.g. '#1001') or "
                                "email. Returns local status and tracking number if any."),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "order_number": {"type": "string"},
                        "customer_email": {"type": "string"},
                    },
                },
            },
        ]
        handlers = {
            "list_inbox": self._list_inbox,
            "read_message": self._read_message,
            "lookup_order": self._lookup_order,
        }
        return schemas, handlers

    def _inbox_files(self) -> list:
        inbox = self.cfg.inbox_dir
        if not inbox.is_dir():
            return []
        return sorted(p for p in inbox.iterdir() if p.suffix == ".txt")

    def _list_inbox(self, inp: dict) -> list[str]:
        return [p.name for p in self._inbox_files()]

    def _read_message(self, inp: dict) -> dict:
        for p in self._inbox_files():
            if p.name == inp["filename"]:
                return {"filename": p.name, "content": p.read_text(encoding="utf-8")}
        return {"error": f"no message {inp['filename']!r}"}

    def _lookup_order(self, inp: dict) -> dict:
        number = inp.get("order_number", "").strip()
        email = inp.get("customer_email", "").strip().lower()
        for order in self.store.list_orders():
            if (number and order["order_number"] == number) or \
               (email and order["customer_email"].lower() == email):
                return {k: order[k] for k in
                        ("id", "order_number", "customer_email", "status",
                         "tracking_number", "cj_order_id")}
        return {"found": False,
                "note": "no matching order in the local pipeline; it may not be synced yet"}
