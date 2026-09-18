"""Feb 2026 · Follow-up · Extend ack-bypass to past_due / unpaid / overdue.

Backend gate contract lock-in:
    * :data:`services.quotes.status_gate._ALLOWED_WITH_ACK` for the
      ``invoice`` doc_type now includes ``past_due`` / ``unpaid`` /
      ``overdue`` in ADDITION to the pre-existing ``sent`` /
      ``accepted`` / ``paid`` / ``partial``.
    * The estimate side of the map is intentionally unchanged.

These tests exercise the pure predicate + assert helper (fast, no
Motor loop needed for those) and one full-stack ``PUT /quotes/{id}``
round-trip via ``httpx.ASGITransport`` (aligned with the Feb 2026
baseline) covering the primary acceptance criteria:

    1. Admin PATCH without ack on ``past_due`` → 409 (blocked).
    2. Admin PATCH with ack on ``past_due`` → 200, mutation persists.
    3. Tech PATCH with ack on ``past_due`` → 403 (role gate).
    4. Regression: existing status ``paid`` still behaves identically.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict

import httpx
import pytest
from httpx import ASGITransport
from fastapi import HTTPException


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ═══════════════════════════════════════════════════════════════════
# 1 · Pure predicate — ack list contains the three new statuses
# ═══════════════════════════════════════════════════════════════════

def test_ack_bypass_list_contains_the_three_new_invoice_statuses():
    from services.quotes.status_gate import _ALLOWED_WITH_ACK
    assert "past_due" in _ALLOWED_WITH_ACK["invoice"]
    assert "unpaid" in _ALLOWED_WITH_ACK["invoice"]
    assert "overdue" in _ALLOWED_WITH_ACK["invoice"]


def test_ack_bypass_estimate_list_is_unchanged():
    """The follow-up widened only the invoice list; the estimate
    ack-bypass list must remain byte-identical to pre-follow-up so
    the quote flow isn't accidentally loosened."""
    from services.quotes.status_gate import _ALLOWED_WITH_ACK
    assert _ALLOWED_WITH_ACK["estimate"] == {"accepted", "declined"}


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
def test_invoice_is_mutable_with_ack_for_new_statuses(status):
    from services.quotes.status_gate import is_quote_mutable_for_put
    inv = {"doc_type": "invoice", "status": status}
    assert is_quote_mutable_for_put(inv, bypass_lock=True) is True


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
def test_invoice_is_locked_without_ack_for_new_statuses(status):
    from services.quotes.status_gate import is_quote_mutable_for_put
    inv = {"doc_type": "invoice", "status": status}
    assert is_quote_mutable_for_put(inv, bypass_lock=False) is False


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
def test_assert_quote_mutable_raises_409_without_ack(status):
    from services.quotes.status_gate import assert_quote_mutable_for_put
    inv = {"doc_type": "invoice", "status": status,
            "id": "inv-1", "tenant_id": "t1"}
    with pytest.raises(HTTPException) as ei:
        assert_quote_mutable_for_put(inv, bypass_lock=False)
    assert ei.value.status_code == 409
    assert ei.value.detail["error"] == "status_locked"
    assert ei.value.detail["current_status"] == status


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
def test_assert_quote_mutable_passes_with_ack(status):
    from services.quotes.status_gate import assert_quote_mutable_for_put
    inv = {"doc_type": "invoice", "status": status,
            "id": "inv-1", "tenant_id": "t1"}
    # Should NOT raise.
    assert_quote_mutable_for_put(inv, bypass_lock=True)


def test_regression_paid_status_still_locked_without_ack():
    """Spot-check that pre-existing ``paid`` behaviour is unchanged."""
    from services.quotes.status_gate import is_quote_mutable_for_put
    inv = {"doc_type": "invoice", "status": "paid"}
    assert is_quote_mutable_for_put(inv, bypass_lock=False) is False
    assert is_quote_mutable_for_put(inv, bypass_lock=True) is True


def test_regression_void_status_locked_even_with_ack():
    """``void`` is neither in ``_ALLOWED`` nor in ``_ALLOWED_WITH_ACK``
    so ack must NOT unlock it. Ensures the new widen didn't slip
    ``void`` into the ack list."""
    from services.quotes.status_gate import is_quote_mutable_for_put
    inv = {"doc_type": "invoice", "status": "void"}
    assert is_quote_mutable_for_put(inv, bypass_lock=True) is False


# ═══════════════════════════════════════════════════════════════════
# 2 · End-to-end · PUT /quotes/{id} · admin ack path
# ═══════════════════════════════════════════════════════════════════
# Uses ``httpx.ASGITransport`` with dependency overrides so the test
# runs against the real router without a real Mongo or JWT.

_TENANT = {"id": "t-e2e", "slug": "acme"}


async def _tenant_dep():
    return _TENANT


def _admin_user():
    return {"id": "u-admin", "email": "admin@ex.test",
             "role": "admin", "tenant_id": "t-e2e"}


def _super_user():
    return {"id": "u-super", "email": "super@ex.test",
             "role": "super_admin", "tenant_id": "t-e2e"}


def _tech_user():
    return {"id": "u-tech", "email": "tech@ex.test",
             "role": "technician", "tenant_id": "t-e2e"}


class _StubCursor:
    def __init__(self, rows): self._rows = rows

    def sort(self, *_a, **_k): return self
    async def to_list(self, _n): return self._rows

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        v = self._rows[self._i]; self._i += 1
        return v


class _StubColl:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.updates = []
        self.inserts = []

    async def find_one(self, query, projection=None):
        for r in self.rows:
            if all(r.get(k) == v for k, v in query.items()
                    if not isinstance(v, dict)):
                return dict(r)
        return None

    def find(self, query=None, projection=None):
        return _StubCursor(self.rows)

    async def update_one(self, query, update):
        for r in self.rows:
            if all(r.get(k) == v for k, v in query.items()
                    if not isinstance(v, dict)):
                if "$set" in update:
                    r.update(update["$set"])
                self.updates.append({"query": query, "update": update})
                return {"matched": 1}

    async def insert_one(self, doc):
        self.inserts.append(doc)

    async def count_documents(self, *a, **k):
        return 0


class _StubDB:
    def __init__(self, *, invoice):
        self.quotes = _StubColl([invoice])
        self.customers = _StubColl([{"id": "c1", "tenant_id": "t-e2e",
                                       "name": "Test", "email": "c@x.y"}])
        self.audit_logs = _StubColl([])
        # Empty stubs for anything the update path might touch.
        self.items = _StubColl([])
        self.properties = _StubColl([])
        self.documents = _StubColl([])
        self.document_snapshots = _StubColl([])
        self.document_versions = _StubColl([])
        self.dunning_settings = _StubColl([])


def _seed_invoice(status: str) -> Dict[str, Any]:
    return {
        "id": "inv-e2e", "tenant_id": "t-e2e",
        "doc_type": "invoice",
        "customer_id": "c1", "customer_name": "Test",
        "status": status,
        "payment_status": "unpaid",
        "line_items": [{"id": "li-1", "description": "L", "quantity": 1,
                         "unit_price": 100, "retail_price_snapshot": 100}],
        "tax_rate": 0, "subtotal": 100, "tax": 0, "total": 100,
        "amount_paid": 0, "notes": "", "terms": "",
    }


async def _client_for(*, user_fn, invoice_status: str):
    from server import app
    from utils import get_current_user, require_admin
    from routers.tenants import get_current_tenant
    from routers import quotes as _q

    _stub = _StubDB(invoice=_seed_invoice(invoice_status))

    async def _u():
        return user_fn()

    async def _admin_dep():
        u = user_fn()
        if u.get("role") not in ("admin", "super_admin", "manager"):
            raise HTTPException(403, "admin only")
        return u

    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[require_admin] = _admin_dep
    app.dependency_overrides[get_current_tenant] = _tenant_dep

    # Patch the router's db to the stub. Some deep helpers import
    # ``config.db`` fresh; the tests hit the update path early enough
    # that the router-local ``db`` reference is what matters.
    return app, _stub, _q


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
async def test_admin_put_without_ack_blocked_on_new_statuses(status):
    from unittest.mock import patch as _p
    app, stub, qmod = await _client_for(user_fn=_admin_user,
                                          invoice_status=status)
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put("/api/quotes/inv-e2e",
                              json={"notes": "adminfix"})
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["detail"]["error"] == "status_locked"
    assert body["detail"]["current_status"] == status


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
async def test_admin_put_with_ack_succeeds_on_new_statuses(status):
    from unittest.mock import patch as _p
    app, stub, qmod = await _client_for(user_fn=_admin_user,
                                          invoice_status=status)
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put(
                "/api/quotes/inv-e2e",
                json={"notes": "adminfix",
                       "acknowledged_lock_bypass": True},
            )
    assert r.status_code == 200, r.text
    # Update landed on the stub — verify the notes mutation persisted
    # and that ``acknowledged_lock_bypass`` was stripped from ``$set``.
    assert len(stub.quotes.updates) == 1
    upd_set = stub.quotes.updates[0]["update"]["$set"]
    assert upd_set["notes"] == "adminfix"
    assert "acknowledged_lock_bypass" not in upd_set


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
async def test_tech_put_with_ack_still_blocked_on_new_statuses(status):
    """Regression guard — the role gate lives in ``require_admin``
    (the endpoint's dependency). Even with the ack flag, a
    ``technician`` token must NOT be able to mutate the invoice."""
    from unittest.mock import patch as _p
    app, stub, qmod = await _client_for(user_fn=_tech_user,
                                          invoice_status=status)
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put(
                "/api/quotes/inv-e2e",
                json={"notes": "techfix",
                       "acknowledged_lock_bypass": True},
            )
    assert r.status_code == 403, r.text


async def test_regression_admin_put_with_ack_still_works_on_paid():
    """Spot-check pre-existing status path — a paid invoice still
    unlocks with ack, unchanged by the widen."""
    from unittest.mock import patch as _p
    app, stub, qmod = await _client_for(user_fn=_admin_user,
                                          invoice_status="paid")
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put(
                "/api/quotes/inv-e2e",
                json={"notes": "paidfix",
                       "acknowledged_lock_bypass": True},
            )
    assert r.status_code == 200, r.text
    upd_set = stub.quotes.updates[0]["update"]["$set"]
    assert upd_set["notes"] == "paidfix"
