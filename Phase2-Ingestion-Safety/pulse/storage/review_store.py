"""SQLite-backed review store — persists ScrubbedReview rows for a
(product, iso_week) run, matching the REVIEW entity in Architecture.md §6.

Deliberate extension: rows are scoped by `iso_week` (not just review_id),
since the 8-12 week rolling window means the same review can legitimately
appear in several consecutive weekly runs, and an edited review should be
reflected in whichever week's run re-ingests it (EdgeCases/
Phase2-Ingestion-Safety.md #5) rather than being globally deduped.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from ..review import ScrubbedReview

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review (
    source            TEXT NOT NULL,
    review_id         TEXT NOT NULL,
    product           TEXT NOT NULL,
    iso_week          TEXT NOT NULL,
    rating            INTEGER NOT NULL,
    title             TEXT NOT NULL,
    body_scrubbed     TEXT NOT NULL,
    locale            TEXT,
    review_date       TEXT NOT NULL,
    pii_redacted      INTEGER NOT NULL DEFAULT 0,
    injection_flagged INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (product, iso_week, source, review_id)
);
"""


class ReviewStore:
    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ReviewStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def save_reviews(self, product: str, iso_week: str, reviews: list[ScrubbedReview]) -> int:
        rows = [
            (
                r.source,
                r.review_id,
                product,
                iso_week,
                r.rating,
                r.title,
                r.body_scrubbed,
                r.locale,
                r.review_date.isoformat(),
                int(r.pii_redacted),
                int(r.injection_flagged),
            )
            for r in reviews
        ]
        self._conn.executemany(
            """INSERT OR REPLACE INTO review
               (source, review_id, product, iso_week, rating, title,
                body_scrubbed, locale, review_date, pii_redacted, injection_flagged)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        return len(rows)

    def get_reviews(self, product: str, iso_week: str) -> list[ScrubbedReview]:
        cur = self._conn.execute(
            "SELECT * FROM review WHERE product = ? AND iso_week = ? ORDER BY review_date",
            (product, iso_week),
        )
        return [_row_to_review(row) for row in cur.fetchall()]

    def count(self, product: str, iso_week: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM review WHERE product = ? AND iso_week = ?",
            (product, iso_week),
        )
        return cur.fetchone()[0]


def _row_to_review(row: sqlite3.Row) -> ScrubbedReview:
    return ScrubbedReview(
        review_id=row["review_id"],
        source=row["source"],
        product=row["product"],
        rating=row["rating"],
        title=row["title"],
        body_scrubbed=row["body_scrubbed"],
        locale=row["locale"],
        review_date=date.fromisoformat(row["review_date"]),
        pii_redacted=bool(row["pii_redacted"]),
        injection_flagged=bool(row["injection_flagged"]),
    )
