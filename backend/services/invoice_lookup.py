"""LZ2/LZ3 · Feb-2026 — Shared dual-collection invoice lookup.

Invoices live in two collections in this codebase:
  • ``db.quotes`` with ``doc_type == "invoice"`` — main creation path
    (``POST /api/quotes``)
  • ``db.invoices`` — used by reconciler, promo codes, referrals,
    lumino_return, etc.

Callers need to work regardless of provenance. This helper checks
``db.invoices`` first (cheaper — no ``doc_type`` filter), then falls
back to ``db.quotes``.

Returns ``(doc, collection_name)`` so the caller knows which
collection to write updates against — never dual-write.
"""
from __future__ import annotations

from typing import Optional, Tuple


async def find_invoice_dual(db, invoice_id: str) -> Tuple[Optional[dict], Optional[str]]:
    """Look up an invoice in db.invoices first, then db.quotes.
    Returns (doc, collection_name) or (None, None) if not found.
    ``collection_name`` is "invoices" or "quotes"."""
    doc = await db.invoices.find_one({"id": invoice_id}, {"_id": 0})
    if doc:
        return doc, "invoices"
    doc = await db.quotes.find_one(
        {"id": invoice_id, "doc_type": "invoice"}, {"_id": 0}
    )
    if doc:
        return doc, "quotes"
    return None, None
