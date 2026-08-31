"""Persists each run's QuantSnapshot so next week's run can do a real
week-over-week comparison without re-clustering old reviews (clustering
isn't deterministic enough across separate runs to compare cluster-to-
cluster directly — see quant_analysis.py's WoW comparison docstring).

Separate from Phase 1's run ledger deliberately: the ledger's job is
delivery-identifier audit trail (Architecture.md §6), not analytical
history. This is a Phase 6-only concern, additive to it.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .quant_analysis import QuantSnapshot, SentimentCounts, StarCount, ThemeMetrics

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quant_snapshot (
    product      TEXT NOT NULL,
    iso_week     TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (product, iso_week)
);
"""


def _snapshot_to_dict(snapshot: QuantSnapshot) -> dict:
    return {
        "total_reviews": snapshot.total_reviews,
        "average_rating": snapshot.average_rating,
        "sentiment": {
            "positive": snapshot.sentiment.positive,
            "neutral": snapshot.sentiment.neutral,
            "negative": snapshot.sentiment.negative,
        },
        "star_distribution": [
            {"stars": s.stars, "count": s.count, "pct": s.pct} for s in snapshot.star_distribution
        ],
        "theme_metrics": [
            {
                "theme_id": t.theme_id,
                "theme_name": t.theme_name,
                "review_count": t.review_count,
                "pct_of_total": t.pct_of_total,
                "sentiment": {
                    "positive": t.sentiment.positive,
                    "neutral": t.sentiment.neutral,
                    "negative": t.sentiment.negative,
                },
            }
            for t in snapshot.theme_metrics
        ],
        "issue_count": snapshot.issue_count,
        "issue_pct": snapshot.issue_pct,
    }


def _dict_to_snapshot(data: dict) -> QuantSnapshot:
    return QuantSnapshot(
        total_reviews=data["total_reviews"],
        average_rating=data["average_rating"],
        sentiment=SentimentCounts(**data["sentiment"]),
        star_distribution=tuple(StarCount(**s) for s in data["star_distribution"]),
        theme_metrics=tuple(
            ThemeMetrics(
                theme_id=t["theme_id"],
                theme_name=t["theme_name"],
                review_count=t["review_count"],
                pct_of_total=t["pct_of_total"],
                sentiment=SentimentCounts(**t["sentiment"]),
            )
            for t in data["theme_metrics"]
        ),
        issue_count=data["issue_count"],
        issue_pct=data["issue_pct"],
    )


@dataclass(frozen=True)
class StoredSnapshot:
    iso_week: str
    snapshot: QuantSnapshot


class QuantSnapshotStore:
    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "QuantSnapshotStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def save(self, product: str, iso_week: str, snapshot: QuantSnapshot, *, created_at: str) -> None:
        self._conn.execute(
            """INSERT INTO quant_snapshot (product, iso_week, snapshot_json, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(product, iso_week) DO UPDATE SET
                 snapshot_json = excluded.snapshot_json, created_at = excluded.created_at""",
            (product, iso_week, json.dumps(_snapshot_to_dict(snapshot)), created_at),
        )

    def get(self, product: str, iso_week: str) -> StoredSnapshot | None:
        cur = self._conn.execute(
            "SELECT iso_week, snapshot_json FROM quant_snapshot WHERE product = ? AND iso_week = ?",
            (product, iso_week),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return StoredSnapshot(iso_week=row["iso_week"], snapshot=_dict_to_snapshot(json.loads(row["snapshot_json"])))
