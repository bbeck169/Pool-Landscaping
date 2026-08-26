"""Feb-2026 · Item 2 — customer_id list filter (backend).

Verifies:
  * ``GET /api/quotes`` accepts ``customer_id`` + filters to that
    customer + preserves tenant scope.
  * ``GET /api/estimates`` accepts ``customer_id``.
  * ``GET /api/payments/list`` accepts ``customer_id``.
  * customer_id filter is ADDITIVE to existing filters (doc_type,
    status, etc.) — not a replacement.

Uses ``asyncio.get_event_loop().run_until_complete`` per the repo
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


# ── minimal fake motor collection ────────────────────────────────────
class _FakeCursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = list(docs)

    def sort(self, *_a, **_kw):
        return self

    async def to_list(self, _limit):
        return list(self._docs)

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _FakeCollection:
    def __init__(self, docs):
        self.docs = list(docs)
        self.last_query: Optional[Dict[str, Any]] = None

    def find(self, q, projection=None):
        self.last_query = dict(q)
        out = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if k == "$or":
                    # ignore for filter purposes (soft-delete guard)
                    continue
                if isinstance(v, dict) and "$in" in v:
                    if d.get(k) not in v["$in"]:
                        ok = False; break
                elif isinstance(v, dict) and "$gt" in v:
                    try:
                        if not (float(d.get(k) or 0) > v["$gt"]):
                            ok = False; break
                    except (TypeError, ValueError):
                        ok = False; break
                elif d.get(k) != v:
                    ok = False; break
            if ok:
                out.append(d)
        return _FakeCursor(out)


class _FakeDB:
    def __init__(self):
        self._c: Dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        return self._c.setdefault(name, _FakeCollection([]))

    def __getattr__(self, name):
        return self.__getitem__(name)


# ── fixtures ─────────────────────────────────────────────────────────
@pytest.fixture
def fake_db(monkeypatch):
    fdb = _FakeDB()
    monkeypatch.setattr("config.db", fdb, raising=False)
    # Modules under test resolve db at import; patch each namespace.
    import routers.quotes as _q; monkeypatch.setattr(_q, "db", fdb, raising=False)
    import routers.estimates as _e; monkeypatch.setattr(_e, "db", fdb, raising=False)
    import routers.reports as _r; monkeypatch.setattr(_r, "db", fdb, raising=False)
    return fdb


@pytest.fixture
def admin_user():
    return {"id": "u-admin", "tenant_id": "t-1", "role": "admin",
            "email": "a@x.com"}


@pytest.fixture
def tenant():
    return {"id": "t-1", "slug": "test-t"}


# ── /quotes list — customer_id filter ────────────────────────────────
class TestQuotesCustomerFilter:
    def test_customer_id_filters_to_that_customer_only(
        self, fake_db, admin_user, tenant,
    ):
        fake_db["quotes"].docs = [
            {"id": "q-1", "tenant_id": "t-1", "doc_type": "invoice",
             "customer_id": "c-A", "title": "A1"},
            {"id": "q-2", "tenant_id": "t-1", "doc_type": "invoice",
             "customer_id": "c-B", "title": "B1"},
            {"id": "q-3", "tenant_id": "t-1", "doc_type": "invoice",
             "customer_id": "c-A", "title": "A2"},
        ]
        from routers.quotes import list_quotes
        rows = _run(list_quotes(
            user=admin_user, tenant=tenant,
            doc_type="invoice", include_deleted=False,
            category=None, card_on_file=None, customer_id="c-A",
        ))
        ids = sorted(r["id"] for r in rows)
        assert ids == ["q-1", "q-3"]
        # Predicate must include tenant + customer scope.
        lq = fake_db["quotes"].last_query
        assert lq["tenant_id"] == "t-1"
        assert lq["customer_id"] == "c-A"
        assert lq["doc_type"] == "invoice"

    def test_no_customer_id_returns_all_tenant_invoices(
        self, fake_db, admin_user, tenant,
    ):
        fake_db["quotes"].docs = [
            {"id": "q-1", "tenant_id": "t-1", "doc_type": "invoice",
             "customer_id": "c-A"},
            {"id": "q-2", "tenant_id": "t-1", "doc_type": "invoice",
             "customer_id": "c-B"},
        ]
        from routers.quotes import list_quotes
        rows = _run(list_quotes(
            user=admin_user, tenant=tenant, doc_type="invoice",
            include_deleted=False, category=None, card_on_file=None,
            customer_id=None,
        ))
        assert len(rows) == 2

    def test_customer_id_never_crosses_tenants(
        self, fake_db, admin_user, tenant,
    ):
        fake_db["quotes"].docs = [
            {"id": "q-1", "tenant_id": "t-1", "doc_type": "invoice",
             "customer_id": "c-X"},
            {"id": "q-2", "tenant_id": "t-OTHER", "doc_type": "invoice",
             "customer_id": "c-X"},
        ]
        from routers.quotes import list_quotes
        rows = _run(list_quotes(
            user=admin_user, tenant=tenant, doc_type="invoice",
            include_deleted=False, category=None, card_on_file=None,
            customer_id="c-X",
        ))
        ids = [r["id"] for r in rows]
        assert ids == ["q-1"]
        assert "q-2" not in ids

    def test_technician_still_forbidden_even_when_customer_id_sent(
        self, fake_db, tenant,
    ):
        from routers.quotes import list_quotes
        from fastapi import HTTPException
        tech = {"id": "u-t", "tenant_id": "t-1", "role": "technician"}
        with pytest.raises(HTTPException) as exc:
            _run(list_quotes(
                user=tech, tenant=tenant, doc_type="invoice",
                include_deleted=False, category=None, card_on_file=None,
                customer_id="c-A",
            ))
        assert exc.value.status_code == 403


# ── /estimates list — customer_id filter ─────────────────────────────
class TestEstimatesCustomerFilter:
    def test_customer_id_filters_to_that_customer_only(
        self, fake_db, admin_user, tenant,
    ):
        fake_db["estimates"].docs = [
            {"id": "e-1", "tenant_id": "t-1", "customer_id": "c-A"},
            {"id": "e-2", "tenant_id": "t-1", "customer_id": "c-B"},
        ]
        from routers.estimates import list_estimates
        rows = _run(list_estimates(
            user=admin_user, tenant=tenant, customer_id="c-A",
        ))
        assert [r["id"] for r in rows] == ["e-1"]
        assert fake_db["estimates"].last_query["customer_id"] == "c-A"


# ── /payments/list — customer_id filter ──────────────────────────────
class TestPaymentsCustomerFilter:
    def test_customer_id_filters_ledger(
        self, fake_db, admin_user, tenant,
    ):
        fake_db["quotes"].docs = [
            {"id": "p-1", "doc_type": "invoice", "customer_id": "c-A",
             "payment_status": "paid", "amount_paid": 100.0,
             "created_at": "2026-02-15T00:00:00Z", "paid_at": "2026-02-15T00:00:00Z"},
            {"id": "p-2", "doc_type": "invoice", "customer_id": "c-B",
             "payment_status": "paid", "amount_paid": 200.0,
             "created_at": "2026-02-15T00:00:00Z", "paid_at": "2026-02-15T00:00:00Z"},
        ]
        from routers.reports import payments_list
        r = _run(payments_list(
            user=admin_user, start=None, end=None, method=None,
            status="paid", customer_id="c-A", page=1, page_size=50,
        ))
        ids = [row["id"] for row in r["rows"]]
        assert ids == ["p-1"]
        assert r["total"] == 1
        assert fake_db["quotes"].last_query["customer_id"] == "c-A"
