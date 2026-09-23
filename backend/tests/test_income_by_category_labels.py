"""Feb-2026 · Income-by-Category label resolver — regression tests.

Root-cause: mobile "Income by Category" was rendering raw UUIDs when
invoice line items carried a category *id* (via ``income_category_id``
or an inline UUID string in ``category``) instead of the display name.
``compute_income_by_category`` now runs a resolution ladder:

  1. ``income_category_id`` → name via ``db.income_categories``.
  2. inline ``category`` — UUID-shape guarded → id lookup or
     ``Uncategorized (…last-8)`` orphan fallback.
  3. pricebook fallback via ``item_id`` → ``db.items.category``.
  4. legacy ``"Pool"`` default (unchanged for older seed data).

These tests lock the new response contract (``label``,
``category_id``, plus the legacy ``category`` alias) and cover:
  1. Every row carries a ``label`` field.
  2. Unresolvable UUID → ``Uncategorized (…last-8)`` fallback.
  3. Well-known enum (``"Pool"``) passes through verbatim.
  4. Tenant scoping — tenant A never sees tenant B rows.

Uses ``asyncio.get_event_loop().run_until_complete`` per repo
convention (no ``pytest-asyncio`` in the dev image).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

os.environ.setdefault(
    "FERNET_KEY",
    "f2DlHrLPFFiF2HxLFglFEegS2pvke90APrHBSU_YGus=",
)

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Minimal in-memory fake with $and / $or / $exists / $gt / $ne ──
_SENTINEL = object()


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_a, **_kw):
        return self

    async def to_list(self, _limit=None):
        return list(self._docs)


class _FakeCollection:
    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])

    def _cmp_op(self, doc_val, op, needle):
        if op == "$exists":
            has = doc_val is not _SENTINEL
            return has if needle else not has
        if op == "$ne":
            return doc_val != needle
        if op == "$gt":
            try:
                return float(doc_val or 0) > float(needle)
            except (TypeError, ValueError):
                return False
        if op == "$gte":
            return (doc_val or "") >= needle
        if op == "$lte":
            return (doc_val or "") <= needle
        return False

    def _matches(self, doc, q):
        for k, v in q.items():
            if k == "$or":
                if not any(self._matches(doc, cond) for cond in v):
                    return False
                continue
            if k == "$and":
                if not all(self._matches(doc, cond) for cond in v):
                    return False
                continue
            if isinstance(v, dict):
                doc_val = doc.get(k, _SENTINEL)
                for op, needle in v.items():
                    if op == "$exists":
                        has = k in doc
                        if needle and not has:
                            return False
                        if not needle and has:
                            return False
                    elif not self._cmp_op(
                        doc_val if doc_val is not _SENTINEL else None,
                        op, needle,
                    ):
                        return False
                continue
            if doc.get(k) != v:
                return False
        return True

    def find(self, q, projection=None):
        return _FakeCursor([
            {k: v for k, v in d.items() if k != "_id"}
            for d in self.docs if self._matches(d, q)
        ])


class _FakeDB:
    def __init__(self):
        self._c: Dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        return self._c.setdefault(name, _FakeCollection())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self.__getitem__(name)


# ─────────────────────────────────────────────────────────────────────
# Fixtures — one fake DB seeded with both tenants' data. Every test
# picks a tenant_id via the compute_income_by_category call, and the
# fake DB filters by ``tenant_id`` in its ``_matches`` engine.
# ─────────────────────────────────────────────────────────────────────
POOL_CAT_A = "eb08680a-b3db-455b-b4dc-47b2a3fe6645"
LANDSCAPE_CAT_A = "0c9431cb-595c-488e-ae04-d3d0e29fcc39"
ORPHAN_UUID = "48cd653e-afc6-4864-a59b-47b7a0953b5c"
TENANT_B_CAT = "ffffffff-ffff-4fff-8fff-ffffffffffff"


@pytest.fixture
def fake_db(monkeypatch):
    fdb = _FakeDB()

    # income_categories — tenant-scoped id ↔ name mappings.
    fdb["income_categories"].docs = [
        {"id": POOL_CAT_A, "name": "Pool", "tenant_id": "t-A"},
        {"id": LANDSCAPE_CAT_A, "name": "Landscaping", "tenant_id": "t-A"},
        {"id": TENANT_B_CAT, "name": "Tenant B Pool", "tenant_id": "t-B"},
    ]

    # Invoices covering the four cases we assert on.
    fdb["quotes"].docs = [
        # Case 3 — inline well-known enum "Pool" (non-UUID passthrough).
        {"id": "inv-pool", "tenant_id": "t-A", "doc_type": "invoice",
         "payment_status": "paid", "amount_paid": 100.0, "total": 100.0,
         "line_items": [
             {"category": "Pool", "quantity": 1, "unit_price": 100.0},
         ],
         "created_at": "2026-02-15T00:00:00Z"},
        # Case 2 — inline category holds an unresolvable UUID (orphan).
        {"id": "inv-orphan", "tenant_id": "t-A", "doc_type": "invoice",
         "payment_status": "paid", "amount_paid": 200.0, "total": 200.0,
         "line_items": [
             {"category": ORPHAN_UUID, "quantity": 1, "unit_price": 200.0},
         ],
         "created_at": "2026-02-15T00:00:00Z"},
        # Case 1 — income_category_id lookup path (resolved to name).
        {"id": "inv-id", "tenant_id": "t-A", "doc_type": "invoice",
         "payment_status": "paid", "amount_paid": 50.0, "total": 50.0,
         "line_items": [
             {"income_category_id": LANDSCAPE_CAT_A,
              "quantity": 1, "unit_price": 50.0},
         ],
         "created_at": "2026-02-15T00:00:00Z"},
        # Case 4 — tenant B invoice must NEVER leak into tenant A.
        {"id": "inv-tenant-b", "tenant_id": "t-B", "doc_type": "invoice",
         "payment_status": "paid", "amount_paid": 999.0, "total": 999.0,
         "line_items": [
             {"category": "Tenant B Pool", "quantity": 1,
              "unit_price": 999.0},
         ],
         "created_at": "2026-02-15T00:00:00Z"},
    ]

    # Patch the finances router's module-level ``db`` to the fake.
    import routers.finances as _f
    monkeypatch.setattr(_f, "db", fdb, raising=False)
    return fdb


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────
def test_every_row_has_label_field(fake_db):
    """Contract: every row carries a ``label`` field (never absent)."""
    from routers.finances import compute_income_by_category
    r = _run(compute_income_by_category("t-A"))
    assert r["rows"], "expected non-empty rows for tenant t-A"
    for row in r["rows"]:
        assert "label" in row, f"row missing label: {row}"
        assert isinstance(row["label"], str) and row["label"], (
            f"label must be a non-empty string, got: {row['label']!r}"
        )
        # Backward-compat alias must still match the label.
        assert row["category"] == row["label"]


def test_unresolvable_uuid_gets_orphan_fallback_label(fake_db):
    """A UUID category with no matching income_categories row is
    surfaced as ``Uncategorized (…last-8)`` so ops can trace it."""
    from routers.finances import compute_income_by_category
    r = _run(compute_income_by_category("t-A"))
    labels = {row["label"] for row in r["rows"]}
    expected_suffix = ORPHAN_UUID[-8:]
    expected_label = f"Uncategorized ({expected_suffix})"
    assert expected_label in labels, (
        f"expected orphan label '{expected_label}' in labels: {labels}"
    )
    # And the orphan row must carry the raw UUID as its category_id
    # so a future drill-down can point at the specific broken ref.
    orphan_row = next(
        row for row in r["rows"] if row["label"] == expected_label
    )
    assert orphan_row["category_id"] == ORPHAN_UUID


def test_wellknown_enum_passes_through_verbatim(fake_db):
    """Non-UUID strings (``"Pool"``, ``"Landscape"``, ...) render
    as-is with the label matching the input string."""
    from routers.finances import compute_income_by_category
    r = _run(compute_income_by_category("t-A"))
    pool_rows = [row for row in r["rows"] if row["label"] == "Pool"]
    assert pool_rows, f"expected 'Pool' row, got: {r['rows']}"
    pool_row = pool_rows[0]
    # Well-known name-→-id lookup fills category_id when the display
    # name maps to a live income_categories row.
    assert pool_row["category_id"] == POOL_CAT_A
    assert pool_row["amount"] == 100.0


def test_tenant_scoping_isolates_tenant_a_from_tenant_b(fake_db):
    """Tenant A must never see tenant B's invoices in the response."""
    from routers.finances import compute_income_by_category
    r_a = _run(compute_income_by_category("t-A"))
    labels_a = {row["label"] for row in r_a["rows"]}
    assert "Tenant B Pool" not in labels_a
    # And the totals must not sum tenant B's $999.
    # Tenant A totals: 100 (Pool) + 200 (orphan) + 50 (Landscaping) = 350.
    assert r_a["total"] == 350.0

    # Sanity: querying as tenant B does show B's row (proves the
    # scoping works both ways, not that tenant A is broken).
    r_b = _run(compute_income_by_category("t-B"))
    labels_b = {row["label"] for row in r_b["rows"]}
    assert "Tenant B Pool" in labels_b
    assert r_b["total"] == 999.0
