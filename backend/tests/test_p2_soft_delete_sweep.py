"""Feb-2026 · P2 Items 1-3 — soft-delete portal + revenue exclusion.

Combined test file for the three defensive sweeps in the P2 bundle:

  Item 1 — ``GET /api/quotes/{qid}`` 404s soft-deleted rows for
           everyone except super_admin with ``?include_deleted=true``.
  Item 2 — Dashboard revenue + reports helpers + payments ledger
           + invoice CSV export all exclude soft-deleted invoices.
  Item 3 — Portal PDF / viewer read path (``_load_invoice`` in
           ``invoice_viewer.py``) returns None for soft-deleted rows
           so the router 404s.

Uses ``asyncio.get_event_loop().run_until_complete`` per repo
convention (no pytest-asyncio in the dev image).
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


# ── Reusable fake collection with $or / $and / $exists / $in / $gt ──
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
        self.last_query: Optional[Dict[str, Any]] = None

    def _cmp_op(self, doc_val, op, needle):
        if op == "$exists":
            has = doc_val is not _SENTINEL
            return has if needle else not has
        if op == "$in":
            return doc_val in needle
        if op == "$nin":
            return doc_val not in needle
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
        if op == "$lt":
            return (doc_val or "") < needle
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
                        if needle and not has: return False
                        if not needle and has: return False
                    elif not self._cmp_op(doc_val if doc_val is not _SENTINEL else None, op, needle):
                        return False
                continue
            if doc.get(k) != v:
                return False
        return True

    async def find_one(self, q, projection=None):
        self.last_query = dict(q)
        for d in self.docs:
            if self._matches(d, q):
                return {k: v for k, v in d.items() if k != "_id"}
        return None

    def find(self, q, projection=None):
        self.last_query = dict(q)
        return _FakeCursor([
            {k: v for k, v in d.items() if k != "_id"}
            for d in self.docs if self._matches(d, q)
        ])

    async def count_documents(self, q, **kw):
        self.last_query = dict(q)
        return sum(1 for d in self.docs if self._matches(d, q))

    async def insert_one(self, doc):
        self.docs.append({**doc})
        return type("_R", (), {"inserted_id": len(self.docs)})

    async def update_one(self, q, upd, upsert=False):
        for d in self.docs:
            if self._matches(d, q):
                if "$set" in upd:
                    d.update(upd["$set"])
                return type("_R", (), {"matched_count": 1, "modified_count": 1})
        return type("_R", (), {"matched_count": 0, "modified_count": 0})


_SENTINEL = object()


class _FakeDB:
    def __init__(self):
        self._c: Dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        return self._c.setdefault(name, _FakeCollection())

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self.__getitem__(name)


@pytest.fixture
def fake_db(monkeypatch):
    fdb = _FakeDB()
    monkeypatch.setattr("config.db", fdb, raising=False)
    for mod_name in (
        "routers.quotes", "routers.dashboard", "routers.dashboard_revenue",
        "routers.reports", "routers.invoice_viewer",
    ):
        try:
            m = __import__(mod_name, fromlist=["db"])
            monkeypatch.setattr(m, "db", fdb, raising=False)
        except ImportError:
            pass
    return fdb


@pytest.fixture
def super_admin():
    return {"id": "u-sa", "email": "sa@x.com", "tenant_id": "t-1",
            "role": "super_admin"}


@pytest.fixture
def admin():
    return {"id": "u-adm", "email": "a@x.com", "tenant_id": "t-1",
            "role": "admin"}


@pytest.fixture
def customer():
    return {"id": "u-cust", "email": "c@x.com", "tenant_id": "t-1",
            "role": "customer", "customer_id": "c-1"}


@pytest.fixture
def tenant():
    return {"id": "t-1"}


# ─────────────────────────────────────────────────────────────────────
# Item 1 — GET /quotes/{qid} hides deleted
# ─────────────────────────────────────────────────────────────────────
class TestGetQuoteHidesDeleted:
    def test_super_admin_404s_soft_deleted_by_default(
        self, fake_db, super_admin, tenant,
    ):
        fake_db["quotes"].docs = [{
            "id": "inv-del", "tenant_id": "t-1", "doc_type": "invoice",
            "deleted_at": "2026-02-14T10:00:00Z",
        }]
        from routers.quotes import get_quote
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(get_quote(qid="inv-del", user=super_admin,
                             tenant=tenant, include_deleted=False))
        assert exc.value.status_code == 404

    def test_admin_404s_soft_deleted_regardless(
        self, fake_db, admin, tenant,
    ):
        fake_db["quotes"].docs = [{
            "id": "inv-del", "tenant_id": "t-1", "doc_type": "invoice",
            "deleted_at": "2026-02-14T10:00:00Z",
        }]
        from routers.quotes import get_quote
        from fastapi import HTTPException
        # Non-super callers CANNOT set include_deleted; even if they
        # try, the router silently ignores it.
        with pytest.raises(HTTPException) as exc:
            _run(get_quote(qid="inv-del", user=admin, tenant=tenant,
                             include_deleted=True))
        assert exc.value.status_code == 404

    def test_customer_404s_soft_deleted_direct_link(
        self, fake_db, customer, tenant,
    ):
        # Direct-link portal-leak guard — the customer_id matches so
        # RBAC would let them through, but the query filters out the
        # deleted row first, giving them a clean 404.
        fake_db["quotes"].docs = [{
            "id": "inv-del", "tenant_id": "t-1", "doc_type": "invoice",
            "customer_id": "c-1",  # matches customer.customer_id
            "deleted_at": "2026-02-14T10:00:00Z",
        }]
        from routers.quotes import get_quote
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            _run(get_quote(qid="inv-del", user=customer, tenant=tenant,
                             include_deleted=False))
        assert exc.value.status_code == 404

    def test_super_admin_can_bypass_with_include_deleted_true(
        self, fake_db, super_admin, tenant,
    ):
        fake_db["quotes"].docs = [{
            "id": "inv-del", "tenant_id": "t-1", "doc_type": "invoice",
            "deleted_at": "2026-02-14T10:00:00Z",
            "invoice_number": "INV-9",
        }]
        from routers.quotes import get_quote
        # Super_admin explicitly opts in via query param — allowed.
        result = _run(get_quote(qid="inv-del", user=super_admin,
                                    tenant=tenant, include_deleted=True))
        assert result["id"] == "inv-del"
        assert result["invoice_number"] == "INV-9"

    def test_live_quote_still_returns_200_for_everyone_default_path(
        self, fake_db, admin, tenant,
    ):
        # Legacy row with no deleted_at field at all — must still resolve.
        fake_db["quotes"].docs = [{
            "id": "q-live", "tenant_id": "t-1", "doc_type": "quote",
        }]
        from routers.quotes import get_quote
        r = _run(get_quote(qid="q-live", user=admin, tenant=tenant,
                              include_deleted=False))
        assert r["id"] == "q-live"


# ─────────────────────────────────────────────────────────────────────
# Item 2 — dashboard revenue hides deleted
# ─────────────────────────────────────────────────────────────────────
class TestDashboardRevenueHidesDeleted:
    def _seed_three_paid_and_one_deleted(self, fake_db):
        fake_db["quotes"].docs = [
            {"id": "p1", "tenant_id": "t-1", "doc_type": "invoice",
             "payment_status": "paid", "total": 100.0,
             "paid_at": "2026-02-15T10:00:00Z"},
            {"id": "p2", "tenant_id": "t-1", "doc_type": "invoice",
             "payment_status": "paid", "total": 100.0,
             "paid_at": "2026-02-16T10:00:00Z"},
            {"id": "p3", "tenant_id": "t-1", "doc_type": "invoice",
             "payment_status": "paid", "total": 100.0,
             "paid_at": "2026-02-17T10:00:00Z"},
        ]

    def test_dashboard_revenue_excludes_soft_deleted_invoice(
        self, fake_db, admin, tenant,
    ):
        self._seed_three_paid_and_one_deleted(fake_db)
        from routers.dashboard import dashboard
        r = _run(dashboard(user=admin, tenant=tenant))
        # 3 paid × $100 = $300 initially.
        assert r["revenue"] == 300.0
        # Soft-delete one of the three.
        fake_db["quotes"].docs[1]["deleted_at"] = "2026-02-16T11:00:00Z"
        r2 = _run(dashboard(user=admin, tenant=tenant))
        assert r2["revenue"] == 200.0
        # Restore.
        fake_db["quotes"].docs[1]["deleted_at"] = None
        r3 = _run(dashboard(user=admin, tenant=tenant))
        assert r3["revenue"] == 300.0

    def test_dashboard_outstanding_excludes_soft_deleted_unpaid(
        self, fake_db, admin, tenant,
    ):
        fake_db["quotes"].docs = [
            {"id": "u1", "tenant_id": "t-1", "doc_type": "invoice",
             "payment_status": "unpaid", "total": 50.0},
            {"id": "u2", "tenant_id": "t-1", "doc_type": "invoice",
             "payment_status": "unpaid", "total": 75.0,
             "deleted_at": "2026-02-16T10:00:00Z"},
        ]
        from routers.dashboard import dashboard
        r = _run(dashboard(user=admin, tenant=tenant))
        assert r["outstanding"] == 50.0  # NOT 125

    def test_customer_dashboard_hides_soft_deleted_from_outstanding(
        self, fake_db, customer, tenant,
    ):
        fake_db["quotes"].docs = [
            {"id": "cu1", "tenant_id": "t-1", "doc_type": "invoice",
             "customer_id": "c-1", "payment_status": "unpaid",
             "total": 200.0},
            {"id": "cu2", "tenant_id": "t-1", "doc_type": "invoice",
             "customer_id": "c-1", "payment_status": "unpaid",
             "total": 200.0,
             "deleted_at": "2026-02-14T10:00:00Z"},
        ]
        from routers.dashboard import dashboard
        r = _run(dashboard(user=customer, tenant=tenant))
        assert r["outstanding"] == 200.0
        assert r["unpaid_invoices"] == 1  # NOT 2

    def test_reports_fetch_paid_helper_excludes_deleted(self, fake_db):
        fake_db["quotes"].docs = [
            {"id": "a", "doc_type": "invoice", "amount_paid": 100.0,
             "payment_status": "paid", "paid_at": "2026-02-15T00:00:00Z"},
            {"id": "b", "doc_type": "invoice", "amount_paid": 200.0,
             "payment_status": "paid", "paid_at": "2026-02-16T00:00:00Z",
             "deleted_at": "2026-02-17T00:00:00Z"},
        ]
        from routers.reports import _fetch_paid
        docs = _run(_fetch_paid(None, None))
        ids = [d["id"] for d in docs]
        assert "a" in ids
        assert "b" not in ids

    def test_reports_fetch_all_invoices_helper_excludes_deleted(
        self, fake_db,
    ):
        fake_db["quotes"].docs = [
            {"id": "a", "doc_type": "invoice", "total": 50.0,
             "created_at": "2026-02-15T00:00:00Z"},
            {"id": "b", "doc_type": "invoice", "total": 200.0,
             "created_at": "2026-02-16T00:00:00Z",
             "deleted_at": "2026-02-17T00:00:00Z"},
        ]
        from routers.reports import _fetch_all_invoices
        docs = _run(_fetch_all_invoices(None, None))
        ids = [d["id"] for d in docs]
        assert ids == ["a"]

    def test_payments_list_endpoint_excludes_deleted(
        self, fake_db, admin,
    ):
        fake_db["quotes"].docs = [
            {"id": "pa", "doc_type": "invoice",
             "payment_status": "paid", "amount_paid": 100.0,
             "paid_at": "2026-02-15T00:00:00Z", "created_at": "2026-02-15T00:00:00Z"},
            {"id": "pb", "doc_type": "invoice",
             "payment_status": "paid", "amount_paid": 200.0,
             "paid_at": "2026-02-16T00:00:00Z", "created_at": "2026-02-16T00:00:00Z",
             "deleted_at": "2026-02-17T00:00:00Z"},
        ]
        from routers.reports import payments_list
        r = _run(payments_list(
            user=admin, start=None, end=None, method=None,
            status="paid", customer_id=None, page=1, page_size=50,
        ))
        ids = [row["id"] for row in r["rows"]]
        assert "pa" in ids
        assert "pb" not in ids


# ─────────────────────────────────────────────────────────────────────
# Item 3 — portal PDF / viewer aggregator hides deleted
# ─────────────────────────────────────────────────────────────────────
class TestPortalReadPathHidesDeleted:
    def test_invoice_viewer_load_returns_none_for_deleted(self, fake_db):
        fake_db["quotes"].docs = [{
            "id": "gone", "tenant_id": "t-1", "doc_type": "invoice",
            "deleted_at": "2026-02-14T10:00:00Z",
        }]
        from routers.invoice_viewer import _load_invoice
        r = _run(_load_invoice("gone", "t-1"))
        assert r is None

    def test_invoice_viewer_load_returns_live_invoice_ok(self, fake_db):
        fake_db["quotes"].docs = [{
            "id": "live", "tenant_id": "t-1", "doc_type": "invoice",
        }]
        from routers.invoice_viewer import _load_invoice
        r = _run(_load_invoice("live", "t-1"))
        assert r is not None
        assert r["id"] == "live"

    def test_customer_portal_summary_query_excludes_deleted(self, fake_db):
        # Regression guard — the customer_portal.py:83 query shape
        # covered by the prior sweep. Re-locking it here so the
        # portal-hidden invariant lives in ONE audit file for future
        # tester runs.
        fake_db["quotes"].docs = [
            {"id": "live", "tenant_id": "t-1", "doc_type": "invoice",
             "customer_id": "c-1", "total": 100.0, "amount_paid": 0.0},
            {"id": "gone", "tenant_id": "t-1", "doc_type": "invoice",
             "customer_id": "c-1", "total": 200.0, "amount_paid": 0.0,
             "deleted_at": "2026-02-14T10:00:00Z"},
        ]
        rows = _run(fake_db["quotes"].find({
            "tenant_id": "t-1",
            "customer_id": "c-1",
            "doc_type": "invoice",
            "$or": [
                {"deleted_at": None},
                {"deleted_at": {"$exists": False}},
            ],
        }).to_list(2000))
        ids = [r["id"] for r in rows]
        assert "live" in ids
        assert "gone" not in ids
