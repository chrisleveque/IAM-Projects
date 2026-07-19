"""SQLite store: pipeline runs, rendered videos, media assets, approval queue,
agent run log.

Status lifecycles:
    runs:      running -> complete | failed
    videos:    rendered -> in_review -> approved -> uploaded | rejected | upload_failed
    approvals: pending -> approved -> executed | failed ; pending -> rejected

The approvals table is the human gate on publishing: the pipeline may only
insert pending upload actions; executor.py runs approved rows against the
YouTube integration and records the outcome.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

RUN_STATUSES = ("running", "complete", "failed")
VIDEO_STATUSES = ("rendered", "in_review", "approved", "uploaded", "rejected", "upload_failed")
APPROVAL_STATUSES = ("pending", "approved", "executed", "failed", "rejected")
VIDEO_KINDS = ("long", "short")
SOURCE_TYPES = ("original", "public_domain")

# Every action the pipeline may propose, with the payload keys the executor requires.
ACTION_TYPES: dict[str, list[str]] = {
    "youtube.upload_video": ["video_row_id"],
    "youtube.upload_short": ["video_row_id"],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preset TEXT NOT NULL,
    status TEXT DEFAULT 'running',
    source_type TEXT DEFAULT '',
    concept_json TEXT DEFAULT '',
    script_json TEXT DEFAULT '',
    shot_plan_json TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '',
    timeline_json TEXT DEFAULT '',
    workdir TEXT DEFAULT '',
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    parent_video_id INTEGER,
    title TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    duration_s REAL DEFAULT 0,
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    source_type TEXT DEFAULT 'original',
    status TEXT DEFAULT 'rendered',
    youtube_video_id TEXT DEFAULT '',
    privacy TEXT DEFAULT '',
    published_at TEXT,
    metadata_json TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    video_id INTEGER,
    kind TEXT NOT NULL,
    provider TEXT DEFAULT '',
    provider_id TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    license_note TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    duration_s REAL DEFAULT 0,
    segment_id TEXT DEFAULT '',
    created_at TEXT NOT NULL
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
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ----------------------------------------------------------------- runs

    def create_run(self, preset: str, source_type: str, workdir: str) -> int:
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"invalid source_type {source_type!r}")
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO runs (preset, status, source_type, workdir, created_at, updated_at)"
            " VALUES (?, 'running', ?, ?, ?, ?)",
            (preset, source_type, workdir, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_run(self, run_id: int, **fields) -> None:
        if "status" in fields and fields["status"] not in RUN_STATUSES:
            raise ValueError(f"invalid run status {fields['status']!r}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE runs SET {sets}, updated_at = ? WHERE id = ?",
            (*fields.values(), _now(), run_id),
        )
        self.conn.commit()

    def get_run(self, run_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs_table(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- videos

    def create_video(self, run_id: int, kind: str, source_type: str,
                     parent_video_id: int | None = None, **fields) -> int:
        if kind not in VIDEO_KINDS:
            raise ValueError(f"invalid video kind {kind!r}")
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"invalid source_type {source_type!r}")
        now = _now()
        cols = {"run_id": run_id, "kind": kind, "source_type": source_type,
                "parent_video_id": parent_video_id,
                "created_at": now, "updated_at": now, **fields}
        cur = self.conn.execute(
            f"INSERT INTO videos ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            tuple(cols.values()),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_video(self, video_id: int, **fields) -> None:
        if "status" in fields and fields["status"] not in VIDEO_STATUSES:
            raise ValueError(f"invalid video status {fields['status']!r}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE videos SET {sets}, updated_at = ? WHERE id = ?",
            (*fields.values(), _now(), video_id),
        )
        self.conn.commit()

    def get_video(self, video_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return dict(row) if row else None

    def list_videos(self, status: str | None = None, kind: str | None = None) -> list[dict]:
        query, params = "SELECT * FROM videos", []
        clauses = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        rows = self.conn.execute(query + " ORDER BY id", params).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- assets

    def add_asset(self, run_id: int, kind: str, **fields) -> int:
        cols = {"run_id": run_id, "kind": kind, "created_at": _now(), **fields}
        cur = self.conn.execute(
            f"INSERT INTO assets ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            tuple(cols.values()),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_assets(self, run_id: int | None = None, kind: str | None = None) -> list[dict]:
        query, params = "SELECT * FROM assets", []
        clauses = []
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        rows = self.conn.execute(query + " ORDER BY id", params).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------- editorial history

    def recent_topics(self, limit: int = 12) -> list[dict]:
        """Recent long-form concepts (title + theme) so ideation avoids repeats."""
        rows = self.conn.execute(
            "SELECT concept_json FROM runs WHERE concept_json != ''"
            " ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            concept = json.loads(r["concept_json"]).get("concept", {})
            out.append({"title": concept.get("working_title", ""),
                        "theme": concept.get("theme", ""),
                        "angle": concept.get("angle", "")})
        return out

    def source_type_counts(self, last_n: int = 10) -> dict[str, int]:
        """source_type tally over the last N long-form videos (the 80/20 ledger)."""
        rows = self.conn.execute(
            "SELECT source_type FROM videos WHERE kind = 'long'"
            " ORDER BY id DESC LIMIT ?", (last_n,)
        ).fetchall()
        counts = {t: 0 for t in SOURCE_TYPES}
        for r in rows:
            counts[r["source_type"]] = counts.get(r["source_type"], 0) + 1
        return counts

    def recent_music_tracks(self, limit: int = 3) -> list[str]:
        rows = self.conn.execute(
            "SELECT file_path FROM assets WHERE kind = 'music'"
            " ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r["file_path"] for r in rows]

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

    def find_approval_for_video(self, video_row_id: int,
                                statuses: tuple[str, ...] = ("pending", "approved")) -> Approval | None:
        for approval in self.list_approvals(status=None):
            if (approval.payload.get("video_row_id") == video_row_id
                    and approval.status in statuses):
                return approval
        return None

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

    def list_agent_runs(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM agent_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
