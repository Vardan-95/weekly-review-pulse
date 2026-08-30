"""Idempotency conventions — Architecture.md §5.1 (Doc named-range naming)
and §5.2 (Gmail run-key computation). Shared by delivery/doc_delivery.py
and delivery/email_delivery.py.
"""
from __future__ import annotations

import hashlib


def named_range_name(product: str, iso_week: str) -> str:
    """`pulse-section-<product-slug>-<iso_week>`, per Architecture.md §5.1's
    exact example (`pulse-section-groww-2026-W35`) — matches Phase 4's
    `render/doc_blocks.py::_named_range_name` convention."""
    slug = product.strip().lower().replace(" ", "-")
    return f"pulse-section-{slug}-{iso_week}"


def compute_report_content_hash(*parts: str) -> str:
    """Deterministic content hash over report parts (e.g. rendered email
    subject/html/text), used as the `report_content_hash` input to
    compute_run_key(). Parts are joined with a unit-separator character so
    that ('ab', 'c') and ('a', 'bc') don't collide.
    """
    joined = "\x1f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def compute_run_key(product: str, iso_week: str, report_content_hash: str) -> str:
    """`run_key = hash(product, iso_week, report_content_hash)` per
    Architecture.md §5.2."""
    raw = f"{product}\x1f{iso_week}\x1f{report_content_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
