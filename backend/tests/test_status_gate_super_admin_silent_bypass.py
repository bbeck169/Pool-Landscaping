"""Feb-2026 · Invoice God Mode · super_admin silent bypass on PUT.

Contract locked by product:
    * ``super_admin`` skips the ack popup entirely when editing an
      invoice whose status is ``past_due`` / ``unpaid`` / ``overdue``.
      Server-side gate accepts the PUT without
      ``acknowledged_lock_bypass=True`` and writes a DISTINCT audit
      line ``put_quote_status_super_admin_silent_bypass`` (separate
      from the standard ``put_quote_status_denied`` denial line)
      so ops dashboards can filter on the silent path.
    * ``admin`` sees no behaviour change — the ack popup is still
      required on those statuses (regression guard on the earlier
      ack-widen; the friction stays where it provides real signal).
    * ``paid`` / ``void`` / ``cancelled`` are INTENTIONALLY excluded
      from the silent-bypass set — those statuses gate accounting
      integrity, not just visual freshness.
    * ``technician`` / ``customer`` roles remain blocked by
      ``require_admin`` regardless of status.

These tests exercise the pure predicate (fast, no Motor loop needed)
and the full-stack ``PUT /quotes/{id}`` round-trip via
``httpx.ASGITransport``, mirroring the shape of
``test_status_gate_ack_bypass_aged_statuses.py``.
"""
from __future__ import annotations

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
# 1 · Pure predicate — silent-bypass list + role gate
# ═══════════════════════════════════════════════════════════════════


def test_silent_bypass_list_contains_the_three_aged_statuses():
    """Locked constant — future readers see intent at module scope."""
    from services.quotes.status_gate import _SUPER_ADMIN_SILENT_BYPASS
    assert _SUPER_ADMIN_SILENT_BYPASS == {"past_due", "unpaid", "overdue"}


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
def test_should_super_admin_silent_bypass_fires_for_super_admin(status):
    from services.quotes.status_gate import should_super_admin_silent_bypass
    inv = {"doc_type": "invoice", "status": status}
    assert should_super_admin_silent_bypass(inv, "super_admin") is True
    # Case-insensitive on the role.
    assert should_super_admin_silent_bypass(inv, "SUPER_ADMIN") is True


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
def test_should_super_admin_silent_bypass_does_not_fire_for_admin(status):
    from services.quotes.status_gate import should_super_admin_silent_bypass
    inv = {"doc_type": "invoice", "status": status}
    assert should_super_admin_silent_bypass(inv, "admin") is False
    assert should_super_admin_silent_bypass(inv, "manager") is False
    assert should_super_admin_silent_bypass(inv, "technician") is False
    assert should_super_admin_silent_bypass(inv, "customer") is False
    assert should_super_admin_silent_bypass(inv, None) is False


@pytest.mark.parametrize("status", ["paid", "sent", "accepted",
                                      "partial", "void", "draft"])
def test_should_super_admin_silent_bypass_does_not_fire_on_out_of_scope_statuses(status):
    """Silent bypass MUST stay scoped to the three aged statuses —
    paid/void/etc. still require the standard gate path."""
    from services.quotes.status_gate import should_super_admin_silent_bypass
    inv = {"doc_type": "invoice", "status": status}
    assert should_super_admin_silent_bypass(inv, "super_admin") is False


def test_should_super_admin_silent_bypass_does_not_fire_on_estimates():
    """Estimates never enter ``past_due``/``unpaid``/``overdue`` state
    — guard against a doc_type mismatch letting super_admin bypass
    the estimate ack list."""
    from services.quotes.status_gate import should_super_admin_silent_bypass
    for st in ("past_due", "unpaid", "overdue"):
        est = {"doc_type": "quote", "status": st}
        assert should_super_admin_silent_bypass(est, "super_admin") is False


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
def test_is_quote_mutable_for_put_accepts_super_admin_without_ack(status):
    from services.quotes.status_gate import is_quote_mutable_for_put
    inv = {"doc_type": "invoice", "status": status}
    # Silent path — no ack flag, but ``role="super_admin"`` unlocks.
    assert is_quote_mutable_for_put(inv, bypass_lock=False,
                                      role="super_admin") is True
    # Admin still blocked without ack (regression on the earlier widen).
    assert is_quote_mutable_for_put(inv, bypass_lock=False,
                                      role="admin") is False


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
def test_assert_quote_mutable_passes_for_super_admin_without_ack(status):
    from services.quotes.status_gate import assert_quote_mutable_for_put
    inv = {"doc_type": "invoice", "status": status,
            "id": "inv-1", "tenant_id": "t1"}
    # Should NOT raise.
    assert_quote_mutable_for_put(inv, bypass_lock=False, role="super_admin")


def test_super_admin_still_blocked_on_paid_without_ack():
    """Silent bypass does NOT leak into ``paid`` — super_admin still
    has to go through the ack popup for terminal states."""
    from services.quotes.status_gate import is_quote_mutable_for_put
    inv = {"doc_type": "invoice", "status": "paid"}
    assert is_quote_mutable_for_put(inv, bypass_lock=False,
                                      role="super_admin") is False
    # But standard ack path still works for super_admin on paid.
    assert is_quote_mutable_for_put(inv, bypass_lock=True,
                                      role="super_admin") is True


def test_super_admin_still_blocked_on_void_even_with_ack():
    """``void`` is neither in ``_ALLOWED`` nor ``_ALLOWED_WITH_ACK``
    nor ``_SUPER_ADMIN_SILENT_BYPASS`` — super_admin cannot mutate
    a void invoice under any path."""
    from services.quotes.status_gate import is_quote_mutable_for_put
    inv = {"doc_type": "invoice", "status": "void"}
    assert is_quote_mutable_for_put(inv, bypass_lock=False,
                                      role="super_admin") is False
    assert is_quote_mutable_for_put(inv, bypass_lock=True,
                                      role="super_admin") is False


# ═══════════════════════════════════════════════════════════════════
# 2 · End-to-end · PUT /quotes/{id} · silent-bypass audit trail
# ═══════════════════════════════════════════════════════════════════
# Reuses the same in-memory stub pattern as
# ``test_status_gate_ack_bypass_aged_statuses.py`` — httpx.ASGITransport
# + dependency overrides so the router runs against the real code path
# without a Motor loop.

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

    return app, _stub, _q


def _find_audit(stub, event: str):
    """Return the first audit-log row matching ``event`` (or None)."""
    for doc in stub.audit_logs.inserts:
        if doc.get("event") == event:
            return doc
    return None


# --- Silent-bypass happy path ---------------------------------------


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
async def test_super_admin_put_without_ack_succeeds_and_writes_silent_audit(status):
    """super_admin PUT on aged status WITHOUT ack:
    * 200 OK
    * mutation persists to the stub
    * ``put_quote_status_super_admin_silent_bypass`` audit line written
      with actor + old_status + new_fields
    * standard ``put_quote_status_denied`` audit line is NOT written
    """
    from unittest.mock import patch as _p
    app, stub, qmod = await _client_for(user_fn=_super_user,
                                          invoice_status=status)
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put("/api/quotes/inv-e2e",
                              json={"notes": "superfix"})
    assert r.status_code == 200, r.text
    # Update landed on the stub.
    assert len(stub.quotes.updates) == 1
    upd_set = stub.quotes.updates[0]["update"]["$set"]
    assert upd_set["notes"] == "superfix"
    # No ack flag ever leaked into the persisted $set.
    assert "acknowledged_lock_bypass" not in upd_set
    # Distinct silent-bypass audit line is present …
    silent = _find_audit(stub, "put_quote_status_super_admin_silent_bypass")
    assert silent is not None, (
        "silent-bypass audit line missing — ops dashboards would "
        "not surface this action separately from ack-path edits"
    )
    assert silent["user_email"] == "super@ex.test"
    assert silent["user_role"] == "super_admin"
    assert silent["old_status"] == status
    assert silent["doc_type"] == "invoice"
    assert silent["new_fields"].get("notes") == "superfix"
    # … and the standard denial line is NOT (silent means silent).
    assert _find_audit(stub, "put_quote_status_denied") is None


# --- Admin regression — ack popup still required --------------------


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
async def test_admin_put_without_ack_still_blocked_on_aged_statuses(status):
    """Regression on the earlier ack-widen — plain admin sees no
    behaviour change from the silent-bypass work."""
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
    # No silent-bypass audit line (admin doesn't get that path).
    assert _find_audit(stub, "put_quote_status_super_admin_silent_bypass") is None


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
async def test_admin_put_with_ack_still_succeeds_on_aged_statuses(status):
    """Regression guard on the earlier ack-widen — the ack path is
    still the standard route for admins."""
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
    upd_set = stub.quotes.updates[0]["update"]["$set"]
    assert upd_set["notes"] == "adminfix"
    # Ack-path admin edit MUST NOT emit the silent-bypass line —
    # otherwise ops dashboards would over-count silent bypasses.
    assert _find_audit(stub, "put_quote_status_super_admin_silent_bypass") is None


# --- super_admin out-of-scope statuses still gated ------------------


async def test_super_admin_put_without_ack_still_blocked_on_paid():
    """Silent bypass does NOT leak into ``paid`` — the accounting-
    integrity guard has to hold even for super_admin."""
    from unittest.mock import patch as _p
    app, stub, qmod = await _client_for(user_fn=_super_user,
                                          invoice_status="paid")
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put("/api/quotes/inv-e2e",
                              json={"notes": "superfix"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["current_status"] == "paid"
    assert _find_audit(stub, "put_quote_status_super_admin_silent_bypass") is None


async def test_super_admin_put_on_void_refused_even_with_ack():
    """``void`` has no ack path AND no silent-bypass path — super_admin
    cannot mutate a voided invoice under any circumstance."""
    from unittest.mock import patch as _p
    app, stub, qmod = await _client_for(user_fn=_super_user,
                                          invoice_status="void")
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put(
                "/api/quotes/inv-e2e",
                json={"notes": "superfix",
                       "acknowledged_lock_bypass": True},
            )
    assert r.status_code == 409, r.text
    assert _find_audit(stub, "put_quote_status_super_admin_silent_bypass") is None


# --- Technician role blocked regardless -----------------------------


@pytest.mark.parametrize("status", ["past_due", "unpaid", "overdue"])
async def test_tech_put_still_blocked_on_silent_bypass_statuses(status):
    """Role gate (``require_admin``) sits in front of the status gate
    — a technician cannot exploit the silent-bypass surface."""
    from unittest.mock import patch as _p
    app, stub, qmod = await _client_for(user_fn=_tech_user,
                                          invoice_status=status)
    with _p.object(qmod, "db", stub):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as ac:
            r = await ac.put(
                "/api/quotes/inv-e2e",
                json={"notes": "techfix"},
            )
    assert r.status_code == 403, r.text
    assert _find_audit(stub, "put_quote_status_super_admin_silent_bypass") is None
