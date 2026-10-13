"""Feb-2026 · Dashboard Pool + Landscaping customer tiles — tests.

Covers the ``pool_customers_count`` + ``landscaping_customers_count``
aggregation helpers wired into ``GET /api/dashboard``:

  * Union semantics — ``service_category == "both"`` customers are
    counted on BOTH tiles (matches the P2 #6 list filter).
  * ``is_active != False`` + not soft-deleted gate.
  * Case-insensitive match on ``service_category`` so legacy
    ``"Pool"`` / ``"POOL"`` rows land in the same bucket.
  * Tenant isolation — pool customers in tenant B never bleed into
    tenant A's count.

Zero live-DB dependency — the two helpers are pure async
functions over a Mongo-like collection, so a tiny FakeCollection
that honours ``count_documents(query)`` with the minimum operator
set the helpers use (``$and`` / ``$or`` / ``$regex`` /
``$exists``) is enough to lock the contract.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.dashboard_customer_category_counts import (  # noqa: E402
    count_landscaping_customers,
    count_pool_customers,
)


# ═════════════════════════════════════════════════════════════
# FakeCollection — supports the exact Mongo operator subset the
# two helpers emit. No live Mongo required.
# ═════════════════════════════════════════════════════════════
_MISSING = object()


def _get(doc, key):
    return doc.get(key, _MISSING)


def _match_clause(doc, clause):
    """Recursive dict-match honoring $and / $or / $regex /
    $exists / $ne / scalar equality.  Iterates ALL keys in
    the clause so top-level filters that mix a scalar field
    (``tenant_id``) with ``$and`` / ``$or`` groupers all have
    to hold."""
    for key, pred in clause.items():
        if key == "$and":
            if not all(_match_clause(doc, c) for c in pred):
                return False
            continue
        if key == "$or":
            if not any(_match_clause(doc, c) for c in pred):
                return False
            continue
        value = _get(doc, key)
        if isinstance(pred, dict):
            for op, arg in pred.items():
                if op == "$exists":
                    present = value is not _MISSING
                    if bool(arg) != present:
                        return False
                elif op == "$ne":
                    if value is _MISSING:
                        continue
                    if value == arg:
                        return False
                elif op == "$regex":
                    if value is _MISSING or value is None:
                        return False
                    opts = pred.get("$options", "")
                    flags = re.IGNORECASE if "i" in opts else 0
                    if re.search(arg, str(value), flags) is None:
                        return False
                elif op == "$options":
                    # Handled alongside $regex above.
                    pass
                elif op == "$in":
                    if value is _MISSING or value not in arg:
                        return False
                else:
                    raise AssertionError(f"unhandled op {op!r} in test fake")
        else:
            if value is _MISSING:
                if pred is None:
                    continue  # treat missing as null-match-friendly
                return False
            if value != pred:
                return False
    return True


class _FakeCollection:
    def __init__(self, docs):
        self.docs = list(docs or [])

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _match_clause(d, query))


class _FakeDB:
    def __init__(self, customers):
        self.customers = _FakeCollection(customers)


# ═════════════════════════════════════════════════════════════
# Fixture builder
# ═════════════════════════════════════════════════════════════
def _c(**kw):
    """Shorthand — produce a plausible customer doc with the
    defaults the real tenant guard expects."""
    base = {
        "id": kw.pop("id", "c-" + str(id(kw))),
        "tenant_id": kw.pop("tenant_id", "t-a"),
        "is_active": kw.pop("is_active", True),
        "service_category": kw.pop("service_category", None),
    }
    base.update(kw)
    return base


# ═════════════════════════════════════════════════════════════
# Test 1 — User-spec fixture: pool=7, landscaping=5
# ═════════════════════════════════════════════════════════════
def test_dashboard_customer_counts_spec_fixture():
    """Spec fixture from the ticket:
      * 5 pool + is_active=True       → pool +5
      * 3 landscaping + is_active=True → landscaping +3
      * 2 both + is_active=True        → pool AND landscaping +2 each
      * 1 pool + is_active=False       → NOT counted
      * 1 null service_category + active → NOT counted
      * 1 soft-deleted pool            → NOT counted
    Expected: pool=7, landscaping=5.
    """
    docs = []
    for i in range(5):
        docs.append(_c(id=f"p{i}", service_category="pool"))
    for i in range(3):
        docs.append(_c(id=f"l{i}", service_category="landscaping"))
    for i in range(2):
        docs.append(_c(id=f"b{i}", service_category="both"))
    docs.append(_c(id="pi", service_category="pool", is_active=False))
    docs.append(_c(id="pn", service_category=None, is_active=True))
    docs.append(_c(id="pd", service_category="pool",
                     deleted_at="2026-02-01T00:00:00Z"))
    db = _FakeDB(docs)
    pool = asyncio.run(count_pool_customers(db=db, tenant_id="t-a"))
    land = asyncio.run(count_landscaping_customers(db=db, tenant_id="t-a"))
    assert pool == 7, f"expected 7 pool (5 pool + 2 both), got {pool}"
    assert land == 5, f"expected 5 landscaping (3 landscaping + 2 both), got {land}"


# ═════════════════════════════════════════════════════════════
# Test 2 — Case-insensitive match
# ═════════════════════════════════════════════════════════════
def test_case_insensitive_service_category_match():
    docs = [
        _c(id="p1", service_category="POOL"),
        _c(id="p2", service_category="Pool"),
        _c(id="p3", service_category="pool"),
        _c(id="l1", service_category="LANDSCAPING"),
        _c(id="b1", service_category="BOTH"),
    ]
    db = _FakeDB(docs)
    pool = asyncio.run(count_pool_customers(db=db, tenant_id="t-a"))
    land = asyncio.run(count_landscaping_customers(db=db, tenant_id="t-a"))
    assert pool == 4  # 3 pool variants + 1 both
    assert land == 2  # 1 landscaping + 1 both


# ═════════════════════════════════════════════════════════════
# Test 3 — Tenant isolation
# ═════════════════════════════════════════════════════════════
def test_cross_tenant_isolation():
    docs = [
        _c(id="a1", tenant_id="t-a", service_category="pool"),
        _c(id="a2", tenant_id="t-a", service_category="landscaping"),
        _c(id="b1", tenant_id="t-b", service_category="pool"),
        _c(id="b2", tenant_id="t-b", service_category="pool"),
        _c(id="b3", tenant_id="t-b", service_category="landscaping"),
    ]
    db = _FakeDB(docs)
    pool_a = asyncio.run(count_pool_customers(db=db, tenant_id="t-a"))
    land_a = asyncio.run(count_landscaping_customers(db=db, tenant_id="t-a"))
    pool_b = asyncio.run(count_pool_customers(db=db, tenant_id="t-b"))
    land_b = asyncio.run(count_landscaping_customers(db=db, tenant_id="t-b"))
    assert pool_a == 1
    assert land_a == 1
    assert pool_b == 2
    assert land_b == 1


# ═════════════════════════════════════════════════════════════
# Test 4 — is_active != False matches True, missing, and null
# ═════════════════════════════════════════════════════════════
def test_is_active_matches_true_missing_and_null():
    docs = [
        _c(id="t", service_category="pool", is_active=True),
        _c(id="n", service_category="pool", is_active=None),
        _c(id="m", service_category="pool"),  # is_active missing
    ]
    # Remove is_active key from the "missing" doc.
    docs[2].pop("is_active", None)
    db = _FakeDB(docs)
    pool = asyncio.run(count_pool_customers(db=db, tenant_id="t-a"))
    assert pool == 3


def test_is_active_false_excluded():
    docs = [
        _c(id="f1", service_category="pool", is_active=False),
        _c(id="f2", service_category="both", is_active=False),
    ]
    db = _FakeDB(docs)
    pool = asyncio.run(count_pool_customers(db=db, tenant_id="t-a"))
    land = asyncio.run(count_landscaping_customers(db=db, tenant_id="t-a"))
    assert pool == 0
    assert land == 0


# ═════════════════════════════════════════════════════════════
# Test 5 — Soft-deleted excluded on various deleted_at shapes
# ═════════════════════════════════════════════════════════════
def test_soft_deleted_excluded_on_isoformat_string():
    docs = [
        _c(id="d1", service_category="pool",
            deleted_at="2026-02-01T00:00:00Z"),
    ]
    db = _FakeDB(docs)
    assert asyncio.run(
        count_pool_customers(db=db, tenant_id="t-a"),
    ) == 0


# ═════════════════════════════════════════════════════════════
# Test 6 — "both" customer counted on both buckets but not double
#          on a single bucket.
# ═════════════════════════════════════════════════════════════
def test_both_customer_counted_on_both_tiles():
    docs = [_c(id="b1", service_category="both")]
    db = _FakeDB(docs)
    pool = asyncio.run(count_pool_customers(db=db, tenant_id="t-a"))
    land = asyncio.run(count_landscaping_customers(db=db, tenant_id="t-a"))
    assert pool == 1
    assert land == 1


# ═════════════════════════════════════════════════════════════
# Test 7 — ``unset`` / unknown values excluded from both tiles
# ═════════════════════════════════════════════════════════════
def test_unset_or_unknown_category_excluded_from_both_tiles():
    docs = [
        _c(id="u1", service_category=None),
        _c(id="u2", service_category=""),
        _c(id="u3", service_category="unset"),
        _c(id="u4", service_category="other"),
    ]
    db = _FakeDB(docs)
    assert asyncio.run(
        count_pool_customers(db=db, tenant_id="t-a"),
    ) == 0
    assert asyncio.run(
        count_landscaping_customers(db=db, tenant_id="t-a"),
    ) == 0
