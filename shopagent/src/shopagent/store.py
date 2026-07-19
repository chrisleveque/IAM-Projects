"""SQLite store: product pipeline, order pipeline, approval queue, agent run log.

Status lifecycles:
    products:  candidate -> shortlisted -> drafted -> listed | rejected
    orders:    new -> cj_proposed -> cj_placed -> shipped -> delivered | attention
    approvals: pending -> approved -> executed | failed ; pending -> rejected

The approvals table is the human gate: agents may only insert pending rows
(via their propose_action tool); executor.py runs approved rows against the
real integrations and records the outcome.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PRODUCT_STATUSES = ("candidate", "shortlisted", "drafted", "listed", "rejected")
ORDER_STATUSES = ("new", "cj_proposed", "cj_placed", "shipped", "delivered", "attention")
APPROVAL_STATUSES = ("pending", "approved", "executed", "failed", "rejected")

# Every action an agent may propose, with the payload keys the executor requires.
ACTION_TYPES: dict[str, list[str]] = {
    "shopify.create_product": ["title", "description_html", "tags", "price", "vendor"],
    "shopify.update_product": ["shopify_product_id", "fields"],
    "shopify.fulfill_order": ["shopify_order_id", "tracking_number"],
    "cj.create_order": ["order_ref", "cj_items", "shipping_address", "logistic_name"],
    "support.send_reply": ["customer_email", "subject", "body"],
    "marketing.publish": ["channel", "title", "body"],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cj_product_id TEXT NOT NULL,
    cj_vid TEXT DEFAULT '',
    name TEXT NOT NULL,
    niche TEXT DEFAULT '',
    supplier_price REAL,
    shipping_estimate REAL,
    proposed_price REAL,
    images_json TEXT DEFAULT '[]',
    listing_json TEXT DEFAULT '',
    shopify_product_id TEXT DEFAULT '',
    status TEXT DEFAULT 'candidate',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(cj_product_id)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shopify_order_id TEXT NOT NULL,
    order_number TEXT DEFAULT '',
    customer_email TEXT DEFAULT '',
    line_items_json TEXT DEFAULT '[]',
    shipping_address_json TEXT DEFAULT '{}',
    cj_order_id TEXT DEFAULT '',
    tracking_number TEXT DEFAULT '',
    status TEXT DEFAULT 'new',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(shopify_order_id)
);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    agent TEXT NOT NULL,
    title TEXT NOT NULL,
    payload TEXT NOT NULL,
    rationale TEXT DEFAULT '',
    ref_table TEXT DEFAULT '',
    ref_id INTEGER,
    status TEXT DEFAULT 'pending',
    result TEXT DEFAULT '',
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    decided_at TEXT,
    executed_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    task TEXT NOT NULL,
    status TEXT DEFAULT 'ok',
    summary TEXT DEFAULT '',
    tool_calls INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Approval:
    action_type: str
    agent: str
    title: str
    payload: dict
    rationale: str = ""
    ref_table: str = ""
    ref_id: int | None = None
    status: str = "pending"
    result: str = ""
    error: str = ""
    id: int | None = None
    created_at: str = field(default_factory=_now)
    decided_at: str | None = None
    executed_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Approval":
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        return cls(**d)


class Store:
    def __init__(self, db_path: Path | str):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Additive migrations for databases created by earlier versions."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(products)")}
        if "images_json" not in cols:
            self.conn.execute(
                "ALTER TABLE products ADD COLUMN images_json TEXT DEFAULT '[]'")

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------- products

    def upsert_product(self, cj_product_id: str, name: str, **fields) -> int:
        """Insert a candidate product, or refresh metadata on an existing row
        (status is preserved). Returns the row id."""
        row = self.conn.execute(
            "SELECT id FROM products WHERE cj_product_id = ?", (cj_product_id,)
        ).fetchone()
        now = _now()
        if row:
            allowed = {"cj_vid", "name", "niche", "supplier_price", "shipping_estimate",
                       "proposed_price", "images_json", "notes"}
            updates = {k: v for k, v in fields.items() if k in allowed}
            if updates:
                sets = ", ".join(f"{k} = ?" for k in updates)
                self.conn.execute(
                    f"UPDATE products SET {sets}, updated_at = ? WHERE id = ?",
                    (*updates.values(), now, row["id"]),
                )
                self.conn.commit()
            return row["id"]
        cols = {"cj_product_id": cj_product_id, "name": name,
                "created_at": now, "updated_at": now, **fields}
        cur = self.conn.execute(
            f"INSERT INTO products ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            tuple(cols.values()),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_product(self, product_id: int, **fields) -> None:
        if "status" in fields and fields["status"] not in PRODUCT_STATUSES:
            raise ValueError(f"invalid product status {fields['status']!r}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE products SET {sets}, updated_at = ? WHERE id = ?",
            (*fields.values(), _now(), product_id),
        )
        self.conn.commit()

    def get_product(self, product_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return dict(row) if row else None

    def list_products(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM products WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM products ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- orders

    def upsert_order(self, shopify_order_id: str, **fields) -> int:
        """Insert a synced Shopify order; existing rows keep their status and
        CJ linkage, only customer metadata is refreshed. Returns the row id."""
        row = self.conn.execute(
            "SELECT id FROM orders WHERE shopify_order_id = ?", (shopify_order_id,)
        ).fetchone()
        now = _now()
        if row:
            allowed = {"order_number", "customer_email", "line_items_json",
                       "shipping_address_json"}
            updates = {k: v for k, v in fields.items() if k in allowed}
            if updates:
                sets = ", ".join(f"{k} = ?" for k in updates)
                self.conn.execute(
                    f"UPDATE orders SET {sets}, updated_at = ? WHERE id = ?",
                    (*updates.values(), now, row["id"]),
                )
                self.conn.commit()
            return row["id"]
        cols = {"shopify_order_id": shopify_order_id,
                "created_at": now, "updated_at": now, **fields}
        cur = self.conn.execute(
            f"INSERT INTO orders ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            tuple(cols.values()),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_order(self, order_id: int, **fields) -> None:
        if "status" in fields and fields["status"] not in ORDER_STATUSES:
            raise ValueError(f"invalid order status {fields['status']!r}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE orders SET {sets}, updated_at = ? WHERE id = ?",
            (*fields.values(), _now(), order_id),
        )
        self.conn.commit()

    def get_order(self, order_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return dict(row) if row else None

    def get_order_by_shopify_id(self, shopify_order_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM orders WHERE shopify_order_id = ?", (shopify_order_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_orders(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM orders WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM orders ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ approvals

    def propose(self, approval: Approval) -> int:
        """Insert a pending approval. Validates the action type and required
        payload keys so the executor never sees a malformed action."""
        required = ACTION_TYPES.get(approval.action_type)
        if required is None:
            raise ValueError(
                f"unknown action_type {approval.action_type!r}; "
                f"must be one of {sorted(ACTION_TYPES)}"
            )
        missing = [k for k in required if k not in approval.payload]
        if missing:
            raise ValueError(
                f"payload for {approval.action_type} missing keys: {missing}"
            )
        cur = self.conn.execute(
            "INSERT INTO approvals (action_type, agent, title, payload, rationale,"
            " ref_table, ref_id, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (approval.action_type, approval.agent, approval.title,
             json.dumps(approval.payload), approval.rationale,
             approval.ref_table, approval.ref_id, _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_approval(self, approval_id: int) -> Approval | None:
        row = self.conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        return Approval.from_row(row) if row else None

    def list_approvals(self, status: str | None = "pending") -> list[Approval]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM approvals WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM approvals ORDER BY id").fetchall()
        return [Approval.from_row(r) for r in rows]

    def decide_approval(self, approval_id: int, status: str, note: str = "") -> Approval:
        """Move a pending approval to approved/rejected. A failed approval may
        be moved back to approved for retry."""
        approval = self.get_approval(approval_id)
        if approval is None:
            raise ValueError(f"no approval with id {approval_id}")
        if status not in ("approved", "rejected"):
            raise ValueError(f"decision must be approved/rejected, got {status!r}")
        legal_from = ("pending",) if status == "rejected" else ("pending", "failed")
        if approval.status not in legal_from:
            raise ValueError(
                f"approval #{approval_id} is {approval.status}, cannot mark {status}"
            )
        self.conn.execute(
            "UPDATE approvals SET status = ?, decided_at = ?, error = '',"
            " rationale = CASE WHEN ? = '' THEN rationale ELSE rationale || ' | note: ' || ? END"
            " WHERE id = ?",
            (status, _now(), note, note, approval_id),
        )
        self.conn.commit()
        return self.get_approval(approval_id)

    def mark_executed(self, approval_id: int, result: str) -> None:
        self.conn.execute(
            "UPDATE approvals SET status = 'executed', result = ?, executed_at = ? WHERE id = ?",
            (result, _now(), approval_id),
        )
        self.conn.commit()

    def mark_failed(self, approval_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE approvals SET status = 'failed', error = ? WHERE id = ?",
            (error, approval_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------ agent log

    def log_run(self, agent: str, task: str, status: str, summary: str,
                tool_calls: int = 0, input_tokens: int = 0, output_tokens: int = 0) -> int:
        cur = self.conn.execute(
            "INSERT INTO agent_runs (agent, task, status, summary, tool_calls,"
            " input_tokens, output_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (agent, task, status, summary, tool_calls, input_tokens, output_tokens, _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_runs(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM agent_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
