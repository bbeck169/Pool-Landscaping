"""LZ2/LZ3/Phase 11 · Feb-2026 — Shared invoice lookup.

Historically invoices lived in two collections:
  • ``db.quotes`` with ``doc_type == "invoice"`` — main creation path
    (``POST /api/quotes``, source of truth).
  • ``db.invoices`` — an ancillary collection used by the reconciler,
    promo codes, referrals, lumino_return, etc.

**Phase 11 (Feb-2026)** unified onto ``db.quotes``. ``db.invoices`` is
retained as a rollback safety net but should NOT be read or written by
production code. ``find_invoice_dual`` is kept as a compatibility symbol
for existing callers but now hits ``db.quotes`` only.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional, Tuple

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _emit_deprecation_warning() -> None:
    log.warning(
        "[phase11] `find_invoice_dual` is deprecated. Read directly from "
        "`db.quotes` with `doc_type=\"invoice\"`. The shim now returns "
        "`(doc, 'quotes')` for every found row; the `db.invoices` branch "
        "was retired in the Feb-2026 dual-collection refactor."
    )


async def find_invoice_dual(db, invoice_id: str) -> Tuple[Optional[dict], Optional[str]]:
    """Look up an invoice in ``db.quotes`` (source of truth).

    Returns ``(doc, "quotes")`` when found, ``(None, None)`` otherwise.
    The tuple shape is preserved for back-compat — existing callers use
    ``collection_name`` to route their own write, and they'll now always
    write to ``db.quotes``.

    .. deprecated:: phase11
        Read from ``db.quotes`` directly:
        ``await db.quotes.find_one({"id": invoice_id, "doc_type": "invoice"})``.
    """
    _emit_deprecation_warning()
    doc = await db.quotes.find_one(
        {"id": invoice_id, "doc_type": "invoice"}, {"_id": 0}
    )
    if doc:
        return doc, "quotes"
    return None, None
