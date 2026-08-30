"""Idempotent Doc delivery — Architecture.md §5.1, revised.

Checks whether this week's heading text already appears in the document's
content before appending — `google_workspace_mcp` has no dedicated
named-range read tool, so content-search is the idempotency check (see
`docs_client.py`'s module docstring). A named range is not yet created on
append (see `docs_client.py`'s docstring for why) — duplicate-detection
doesn't depend on it anyway, only on the content-text search.

`force_replace` (`--replace-doc-section`) is not implemented in this
revision: safely replacing a section requires deleting its exact text
range, which requires knowing precise indices we have no confirmed way to
read back from this server. Rather than implement something that might
silently corrupt the document, this raises `NotImplementedError` — a
known, documented gap, not a silent no-op.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..idempotency import named_range_name
from .docs_client import DocsMCPClient


@dataclass(frozen=True)
class DocDeliveryResult:
    status: str  # "SUCCEEDED" | "SKIPPED"
    named_range: str
    deep_link: str


def deliver_doc_section(
    client: DocsMCPClient,
    *,
    doc_id: str,
    product: str,
    iso_week: str,
    heading_text: str,
    build_section_text: Callable[[], str],
    force_replace: bool = False,
) -> DocDeliveryResult:
    if force_replace:
        raise NotImplementedError(
            "force_replace (--replace-doc-section) requires precise text-range "
            "deletion, which depends on capabilities not confirmed available in "
            "google_workspace_mcp — see this module's docstring. Not implemented."
        )

    name = named_range_name(product, iso_week)
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

    content = client.get_doc_content(doc_id)
    if heading_text in content.text:
        return DocDeliveryResult(status="SKIPPED", named_range=name, deep_link=doc_url)

    section_text = build_section_text()
    client.append_section(doc_id, section_text)

    return DocDeliveryResult(status="SUCCEEDED", named_range=name, deep_link=doc_url)
