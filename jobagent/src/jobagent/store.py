"""SQLite-backed job tracker.

Status lifecycle:
    discovered -> scored -> (queued) -> tailored -> applied
Any status can move to skipped. Jobs whose apply flow needs an external ATS
stay at tailored/queued with the docs generated for a manual apply.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ("discovered", "scored", "queued", "tailored", "applied", "skipped")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    url TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT DEFAULT '',
    company TEXT DEFAULT '',
    location TEXT DEFAULT '',
    description TEXT DEFAULT '',
    easy_apply INTEGER DEFAULT 0,
    saved INTEGER DEFAULT 0,
    status TEXT DEFAULT 'discovered',
    score INTEGER,
    score_reasons TEXT DEFAULT '',
    resume_path TEXT DEFAULT '',
    cover_letter_path TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    applied_at TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    url: str
    source: str
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    easy_apply: bool = False
    saved: bool = False  # imported from the user's saved-jobs list
    status: str = "discovered"
    score: int | None = None
    score_reasons: str = ""
    resume_path: str = ""
    cover_letter_path: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    applied_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        d = dict(row)
        d["easy_apply"] = bool(d.get("easy_apply"))
        d["saved"] = bool(d.get("saved"))
        return cls(**d)


class Store:
    def __init__(self, db_path: Path | str):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        # Migrate databases created before the `saved` column existed.
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(jobs)")}
        if "saved" not in cols:
            self.conn.execute("ALTER TABLE jobs ADD COLUMN saved INTEGER DEFAULT 0")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def upsert_job(self, job: Job) -> bool:
        """Insert a discovered job. Returns True if new; existing jobs only get
        their description/metadata refreshed (status and score are preserved)."""
        existing = self.get_job(job.url)
        if existing is None:
            self.conn.execute(
                """INSERT INTO jobs (url, source, title, company, location, description,
                       easy_apply, saved, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job.url, job.source, job.title, job.company, job.location,
                 job.description, int(job.easy_apply), int(job.saved), job.status,
                 _now(), _now()),
            )
            self.conn.commit()
            return True
        # Refresh metadata if we scraped more detail this time.
        self.conn.execute(
            """UPDATE jobs SET title = CASE WHEN ? != '' THEN ? ELSE title END,
                   company = CASE WHEN ? != '' THEN ? ELSE company END,
                   location = CASE WHEN ? != '' THEN ? ELSE location END,
                   description = CASE WHEN length(?) > length(description) THEN ? ELSE description END,
                   easy_apply = MAX(easy_apply, ?),
                   saved = MAX(saved, ?),
                   updated_at = ?
               WHERE url = ?""",
            (job.title, job.title, job.company, job.company, job.location, job.location,
             job.description, job.description, int(job.easy_apply), int(job.saved),
             _now(), job.url),
        )
        self.conn.commit()
        return False

    def get_job(self, url: str) -> Job | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
        return Job.from_row(row) if row else None

    def list_jobs(
        self,
        status: str | tuple[str, ...] | None = None,
        source: str | None = None,
        min_score: int | None = None,
        saved: bool | None = None,
    ) -> list[Job]:
        clauses, params = [], []
        if saved is not None:
            clauses.append("saved = ?")
            params.append(int(saved))
        if status is not None:
            statuses = (status,) if isinstance(status, str) else tuple(status)
            clauses.append(f"status IN ({','.join('?' * len(statuses))})")
            params.extend(statuses)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if min_score is not None:
            clauses.append("score >= ?")
            params.append(min_score)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM jobs {where} ORDER BY COALESCE(score, -1) DESC, created_at DESC",
            params,
        ).fetchall()
        return [Job.from_row(r) for r in rows]

    def update(self, url: str, **fields) -> None:
        if not fields:
            return
        if "status" in fields and fields["status"] not in STATUSES:
            raise ValueError(f"unknown status: {fields['status']}")
        if "easy_apply" in fields:
            fields["easy_apply"] = int(bool(fields["easy_apply"]))
        fields["updated_at"] = _now()
        if fields.get("status") == "applied" and "applied_at" not in fields:
            fields["applied_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE jobs SET {cols} WHERE url = ?", (*fields.values(), url))
        self.conn.commit()

    def count_applied_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE status = 'applied' AND applied_at >= ?",
            (today,),
        ).fetchone()
        return int(row["n"])

    def status_counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}
