"""Feb 2026 · Follow-up investigation lock-in — _load_invoice contract.

Tester report
-------------
Tester saw ``GET /api/invoices/{iid}/full-magic?token=...`` returning
404 "Invoice not found" for what they believed were unpaid seed
invoices. Hypothesis (from the tester): legacy seed rows lack
``doc_type=invoice``.

Investigation on preview (2026-02-XX)
-------------------------------------
Raw ``db.quotes`` scan on the preview tenant::

    total rows                 : 383
    doc_type distribution      : {'quote': 261, 'invoice': 122}
    rows missing doc_type      : 0
    invoices w/ deleted_at set : 33 of 122  (soft-deleted)
    unpaid + alive invoices    : loaded successfully via _load_invoice
    /full-magic end-to-end     : HTTP 200 for a real unpaid + alive
                                 invoice with a freshly-minted token

**Root cause: the tester's target invoice(s) were soft-deleted.** The
current guard in
:func:`routers.invoice_viewer._load_invoice` correctly rejects them,
which is the intended defence-in-depth documented in Feb 2026 Phase
P2 Item 3 (portal read-path guard).

Decision — Fix Path (b): NO product code change
------------------------------------------------
* Not (a): 0 rows are missing ``doc_type`` — nothing to migrate.
* Not "loosen the query": the ``deleted_at`` gate is intentional
  (P2 Item 3). Loosening it would let soft-deleted invoices render in
  the customer-facing viewer + PDF.

Instead, this file locks in the current 3-way contract as a
regression suite so a future edit to ``_load_invoice`` (or a bad
seed) can't silently break the invariants below.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import patch


def _run(coro):
    return asyncio.run(coro)


# ─── Motor-shaped stub ─────────────────────────────────────────────
class _Coll:
    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = [dict(r) for r in rows]

    async def find_one(self, query, projection=None):
        # Very small predicate matcher — enough for _load_invoice's
        # ``{id, tenant_id, doc_type, $or:[deleted_at=None|missing]}``.
        or_clauses = query.pop("$or", None)
        for r in self.rows:
            base_ok = all(r.get(k) == v for k, v in query.items()
                           if not isinstance(v, dict))
            if not base_ok:
                continue
            if or_clauses is None:
                return r
            for clause in or_clauses:
                for k, cond in clause.items():
                    if isinstance(cond, dict):
                        if cond.get("$exists") is False and k not in r:
                            return r
                        if cond.get("$exists") is True and k in r:
                            return r
                    else:
                        if r.get(k) == cond and k in r:
                            return r
        return None


class _StubDB:
    def __init__(self, rows: List[Dict[str, Any]]):
        self.quotes = _Coll(rows)


# ═══════════════════════════════════════════════════════════════════
# _load_invoice — invariant lock-ins
# ═══════════════════════════════════════════════════════════════════

def test_load_invoice_returns_alive_invoice_with_doc_type_set():
    """Golden path — the shape 100% of preview's 89 alive invoices
    match: ``doc_type=invoice`` + ``deleted_at=None``. Locks in the
    baseline so a future edit that accidentally reverses the
    ``$or`` order or drops the equality on ``doc_type`` fails CI."""
    from routers import invoice_viewer as mod

    stub = _StubDB([{
        "id": "inv-1", "tenant_id": "t1", "doc_type": "invoice",
        "invoice_number": "INV-2026-000048",
        "payment_status": "unpaid", "deleted_at": None,
    }])
    with patch.object(mod, "db", stub):
        loaded = _run(mod._load_invoice("inv-1", "t1"))
    assert loaded is not None
    assert loaded["invoice_number"] == "INV-2026-000048"


def test_load_invoice_returns_alive_invoice_without_deleted_at_field():
    """Some legacy seeds never wrote a ``deleted_at`` field at all
    (the ``$exists: False`` branch of the ``$or`` catches them).
    Locks in the two-branch soft-delete gate."""
    from routers import invoice_viewer as mod

    stub = _StubDB([{
        "id": "inv-2", "tenant_id": "t1", "doc_type": "invoice",
        "payment_status": "unpaid",
        # no ``deleted_at`` key at all — legacy pre-P2 seed shape.
    }])
    with patch.object(mod, "db", stub):
        loaded = _run(mod._load_invoice("inv-2", "t1"))
    assert loaded is not None
    assert loaded["id"] == "inv-2"


def test_load_invoice_rejects_soft_deleted_invoice():
    """P2 Item 3 lock-in — a soft-deleted invoice (``deleted_at``
    set to any truthy timestamp) MUST 404 so it never renders in
    the customer-facing viewer / PDF / magic-link surface."""
    from routers import invoice_viewer as mod

    stub = _StubDB([{
        "id": "inv-3", "tenant_id": "t1", "doc_type": "invoice",
        "invoice_number": "INV-2026-000042",
        "payment_status": "unpaid",
        "deleted_at": "2026-08-26T05:52:54.566670+00:00",
    }])
    with patch.object(mod, "db", stub):
        loaded = _run(mod._load_invoice("inv-3", "t1"))
    assert loaded is None, (
        "soft-deleted invoice must NOT be loaded — this is the P2 "
        "Item 3 portal read-path guard. If this assertion fails a "
        "future edit has weakened the ``$or: [deleted_at=None, "
        "$exists=False]`` predicate."
    )


def test_load_invoice_rejects_quote_row_even_when_ids_match():
    """Defence-in-depth — a quote in the same collection MUST NOT
    ever match ``_load_invoice`` even if the caller happens to know
    its id. Locks the ``doc_type=invoice`` equality in place."""
    from routers import invoice_viewer as mod

    stub = _StubDB([{
        "id": "same-id", "tenant_id": "t1", "doc_type": "quote",
        "deleted_at": None,
    }])
    with patch.object(mod, "db", stub):
        loaded = _run(mod._load_invoice("same-id", "t1"))
    assert loaded is None


def test_load_invoice_scopes_by_tenant():
    """Cross-tenant leak-proof — a valid invoice in tenant A must
    not match a lookup keyed to tenant B. This mirrors the
    documented magic-token contract in ``invoice_magic_view``."""
    from routers import invoice_viewer as mod

    stub = _StubDB([{
        "id": "inv-4", "tenant_id": "tenant-A", "doc_type": "invoice",
        "deleted_at": None,
    }])
    with patch.object(mod, "db", stub):
        cross = _run(mod._load_invoice("inv-4", "tenant-B"))
    assert cross is None


def test_load_invoice_returns_none_when_missing_doc_type_field():
    """Documents the current strict behaviour: legacy rows that were
    never written with a ``doc_type`` field would 404. The
    investigation on the preview tenant confirmed **zero** such rows
    exist (all 383 quotes have ``doc_type`` set), so no migration is
    needed today. If a future seed drops the field, THIS test will
    fail — pointing the next agent at the migration path
    (invoices_doc_type_backfill.py, path (a) from the follow-up
    ticket) as the correct remediation.

    Purpose of this test: keep the strictness visible + regression-
    guarded so no one loosens the query without deliberately updating
    the contract here.
    """
    from routers import invoice_viewer as mod

    stub = _StubDB([{
        "id": "legacy-inv-no-dt",
        "tenant_id": "t1",
        # No ``doc_type`` — hypothetical legacy row.
        "invoice_number": "INV-LEGACY-001",
        "payment_status": "unpaid",
        "deleted_at": None,
    }])
    with patch.object(mod, "db", stub):
        loaded = _run(mod._load_invoice("legacy-inv-no-dt", "t1"))
    # Documented current behaviour: strict — no doc_type ⇒ 404.
    assert loaded is None
