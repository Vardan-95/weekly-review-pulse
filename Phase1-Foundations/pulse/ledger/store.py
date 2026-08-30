"""SQLite-backed run ledger — the audit log described in Architecture.md §6.

Keyed by (product, iso_week): a run for a given product/week is tracked by
one row that's *updated* across its lifecycle (upsert on start), matching
the "Orch->>Ledger: upsert run(status=STARTED)" step in Architecture.md §4's
sequence diagram — so the idempotency check is a single lookup, not a scan.

Deliberate extension of the §6 ERD: `doc_status` and `email_status` columns
are added so the independent per-leg partial-failure semantics from §9
("Doc delivery and Gmail delivery are independent ledger fields") are
directly queryable, not just inferred from the overall `status` + `error`.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

RUN_STATUSES = ("STARTED", "SUCCEEDED", "FAILED", "SKIPPED")
LEG_STATUSES = ("PENDING", "SKIPPED", "SUCCEEDED", "FAILED")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
    run_id           TEXT PRIMARY KEY,
    product          TEXT NOT NULL,
    iso_week         TEXT NOT NULL,
    status           TEXT NOT NULL,
    doc_id           TEXT,
    doc_named_range  TEXT,
    doc_heading_id   TEXT,
    doc_deep_link    TEXT,
    doc_status       TEXT NOT NULL DEFAULT 'PENDING',
    email_mode       TEXT,
    email_message_id TEXT,
    email_run_key    TEXT,
    email_status     TEXT NOT NULL DEFAULT 'PENDING',
    tokens_used      INTEGER NOT NULL DEFAULT 0,
    cost_usd         REAL NOT NULL DEFAULT 0.0,
    started_at       TEXT NOT NULL,
    completed_at     TEXT,
    error            TEXT,
    UNIQUE(product, iso_week)
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunRecord:
    run_id: str
    product: str
    iso_week: str
    status: str
    doc_id: Optional[str]
    doc_named_range: Optional[str]
    doc_heading_id: Optional[str]
    doc_deep_link: Optional[str]
    doc_status: str
    email_mode: Optional[str]
    email_message_id: Optional[str]
    email_run_key: Optional[str]
    email_status: str
    tokens_used: int
    cost_usd: float
    started_at: str
    completed_at: Optional[str]
    error: Optional[str]

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> "RunRecord":
        return cls(**{key: row[key] for key in row.keys()})


class RunLedger:
    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "RunLedger":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def get_run(self, product: str, iso_week: str) -> Optional[RunRecord]:
        cur = self._conn.execute(
            "SELECT * FROM run WHERE product = ? AND iso_week = ?",
            (product, iso_week),
        )
        row = cur.fetchone()
        return RunRecord._from_row(row) if row else None

    def upsert_start(
        self,
        product: str,
        iso_week: str,
        doc_id: str | None = None,
        email_mode: str | None = None,
    ) -> RunRecord:
        """Idempotent run start.

        Reuses the existing row for (product, iso_week) if present (reset to
        STARTED), otherwise inserts a new one. Wrapped in an IMMEDIATE
        transaction so two concurrent callers can't both observe "no
        existing row" and insert a duplicate (EdgeCases/Phase1-Foundations.md
        #6).
        """
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self.get_run(product, iso_week)
            now = _now_iso()
            if existing:
                self._conn.execute(
                    """UPDATE run SET status = 'STARTED', started_at = ?,
                       completed_at = NULL, error = NULL,
                       doc_status = 'PENDING', email_status = 'PENDING'
                       WHERE run_id = ?""",
                    (now, existing.run_id),
                )
            else:
                run_id = str(uuid.uuid4())
                self._conn.execute(
                    """INSERT INTO run (run_id, product, iso_week, status,
                       doc_id, email_mode, started_at)
                       VALUES (?, ?, ?, 'STARTED', ?, ?, ?)""",
                    (run_id, product, iso_week, doc_id, email_mode, now),
                )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        record = self.get_run(product, iso_week)
        assert record is not None
        return record

    def update_doc(
        self,
        run_id: str,
        *,
        status: str,
        named_range: str | None = None,
        heading_id: str | None = None,
        deep_link: str | None = None,
    ) -> None:
        if status not in LEG_STATUSES:
            raise ValueError(f"invalid doc_status {status!r}")
        self._conn.execute(
            """UPDATE run SET doc_status = ?,
               doc_named_range = COALESCE(?, doc_named_range),
               doc_heading_id = COALESCE(?, doc_heading_id),
               doc_deep_link = COALESCE(?, doc_deep_link)
               WHERE run_id = ?""",
            (status, named_range, heading_id, deep_link, run_id),
        )

    def update_email(
        self,
        run_id: str,
        *,
        status: str,
        message_id: str | None = None,
        run_key: str | None = None,
    ) -> None:
        if status not in LEG_STATUSES:
            raise ValueError(f"invalid email_status {status!r}")
        self._conn.execute(
            """UPDATE run SET email_status = ?,
               email_message_id = COALESCE(?, email_message_id),
               email_run_key = COALESCE(?, email_run_key)
               WHERE run_id = ?""",
            (status, message_id, run_key, run_id),
        )

    def update_usage(
        self,
        run_id: str,
        *,
        tokens_used: int | None = None,
        cost_usd: float | None = None,
    ) -> None:
        self._conn.execute(
            """UPDATE run SET tokens_used = COALESCE(?, tokens_used),
               cost_usd = COALESCE(?, cost_usd) WHERE run_id = ?""",
            (tokens_used, cost_usd, run_id),
        )

    def complete(self, run_id: str, *, status: str, error: str | None = None) -> None:
        if status not in RUN_STATUSES:
            raise ValueError(f"invalid status {status!r}")
        self._conn.execute(
            "UPDATE run SET status = ?, completed_at = ?, error = ? WHERE run_id = ?",
            (status, _now_iso(), error, run_id),
        )

    def list_runs(self, product: str | None = None) -> list[RunRecord]:
        if product:
            cur = self._conn.execute(
                "SELECT * FROM run WHERE product = ? ORDER BY started_at DESC",
                (product,),
            )
        else:
            cur = self._conn.execute("SELECT * FROM run ORDER BY started_at DESC")
        return [RunRecord._from_row(row) for row in cur.fetchall()]
