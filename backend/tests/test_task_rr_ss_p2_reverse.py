"""Task RR/SS Phase 2 followup · Feb 2026 — reverse endpoint tests.

Covers the ``POST /api/customers/{cid}/credits/{entry_id}/reverse``
flow on the Phase 10 storage backend:
  * Happy path — reversal row appears, balance drops
  * Already-reversed → 409
  * Balance-below-zero without force_negative → 422
  * Balance-below-zero with force_negative + super_admin → 200
  * Reverse a reversal → 422
  * Missing entry → 404
  * Customer role gate → 403
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _sync(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def db():
    from config import db as _db
    return _db


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('manager@aquaterra.com')}"}


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def aq_tenant_id(db):
    t = _sync(db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1}))
    return t["id"]


@pytest.fixture(scope="module")
def aq_customer_id(db, aq_tenant_id):
    async def _find():
        c = await db.customers.find_one(
            {"tenant_id": aq_tenant_id}, {"_id": 0, "id": 1},
        )
        return c["id"] if c else None
    return _sync(_find())


def _issue(headers, cid, delta_cents: int, reason: str = "TEST_reverse_setup"):
    r = requests.post(
        f"{API}/customers/{cid}/credits/adjust",
        headers={**headers, "Content-Type": "application/json"},
        json={"delta_cents": delta_cents, "reason": reason}, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _reverse(headers, cid, entry_id, force_negative=False):
    return requests.post(
        f"{API}/customers/{cid}/credits/{entry_id}/reverse",
        headers={**headers, "Content-Type": "application/json"},
        json={"force_negative": force_negative}, timeout=30,
    )


def test_reverse_happy_path(admin_headers, aq_customer_id):
    orig = _issue(admin_headers, aq_customer_id, 4000)
    entry_id = orig["ledger_entry"]["id"]
    balance_after_issue = orig["balance_cents"]
    r = _reverse(admin_headers, aq_customer_id, entry_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # Balance dropped by 4000.
    assert body["balance_cents"] == balance_after_issue - 4000
    # Reversal entry carries the right link + kind.
    entry = body["ledger_entry"]
    assert entry["kind"] == "reversal"
    assert entry["delta_cents"] == -4000
    assert entry["reverted_from_entry_id"] == entry_id


def test_reverse_already_reversed_returns_409(admin_headers, aq_customer_id):
    orig = _issue(admin_headers, aq_customer_id, 2500,
                     reason="TEST_reverse_double")
    entry_id = orig["ledger_entry"]["id"]
    r1 = _reverse(admin_headers, aq_customer_id, entry_id)
    assert r1.status_code == 200
    r2 = _reverse(admin_headers, aq_customer_id, entry_id)
    assert r2.status_code == 409


def test_reverse_a_reversal_returns_422(admin_headers, aq_customer_id):
    orig = _issue(admin_headers, aq_customer_id, 2000,
                     reason="TEST_reverse_of_reversal")
    r1 = _reverse(admin_headers, aq_customer_id, orig["ledger_entry"]["id"])
    assert r1.status_code == 200
    reversal_entry_id = r1.json()["ledger_entry"]["id"]
    r2 = _reverse(admin_headers, aq_customer_id, reversal_entry_id)
    assert r2.status_code == 422


def test_reverse_nonexistent_entry_returns_404(admin_headers, aq_customer_id):
    r = _reverse(admin_headers, aq_customer_id,
                    "nonexistent-" + uuid.uuid4().hex[:8])
    assert r.status_code == 404


def test_reverse_customer_role_gate(customer_headers, aq_customer_id):
    r = _reverse(customer_headers, aq_customer_id, "does-not-matter")
    assert r.status_code in (401, 403)


def test_reverse_below_zero_without_force_returns_422(
    admin_headers, aq_customer_id, db, aq_tenant_id,
):
    """Reverse a positive-delta entry when the current balance is
    LESS than the entry — would push below zero → 422."""
    orig = _issue(admin_headers, aq_customer_id, 6000,
                     reason="TEST_reverse_below_zero_setup")
    entry_id = orig["ledger_entry"]["id"]
    # Drain the balance to below the entry's delta so reversal will
    # push balance negative.
    _issue(admin_headers, aq_customer_id, -(orig["balance_cents"] - 1000),
              reason="TEST_reverse_below_zero_drain")
    r = _reverse(admin_headers, aq_customer_id, entry_id)
    assert r.status_code == 422
    # Restore balance + cleanup: reverse the drain (regular reverse
    # would require the entry_id which we didn't capture — instead
    # issue a compensating adjust).
    async def _current():
        row = await db.customer_credits_balance.find_one(
            {"tenant_id": aq_tenant_id, "customer_id": aq_customer_id},
            {"_id": 0, "balance_cents": 1},
        ) or {}
        return int(row.get("balance_cents") or 0)
    bal = _sync(_current())
    if bal < orig["balance_cents"]:
        _issue(admin_headers, aq_customer_id,
                  orig["balance_cents"] - bal,
                  reason="TEST_reverse_below_zero_restore")


def test_reverse_below_zero_super_admin_force_returns_200(
    super_headers, admin_headers, aq_customer_id,
):
    """Same setup as above but super_admin + force_negative → 200."""
    orig = _issue(admin_headers, aq_customer_id, 3000,
                     reason="TEST_reverse_force_setup")
    entry_id = orig["ledger_entry"]["id"]
    # Drain balance to zero-ish so reversal pushes below zero.
    _issue(super_headers, aq_customer_id, -(orig["balance_cents"]),
              reason="TEST_reverse_force_drain")
    # Regular admin + force_negative → 403.
    r_a = _reverse(admin_headers, aq_customer_id, entry_id,
                     force_negative=True)
    assert r_a.status_code == 403
    # Super_admin + force_negative → 200 with negative balance.
    r_s = _reverse(super_headers, aq_customer_id, entry_id,
                     force_negative=True)
    assert r_s.status_code == 200
    assert r_s.json()["balance_cents"] < 0
    # Restore balance to zero.
    _issue(super_headers, aq_customer_id, 3000,
              reason="TEST_reverse_force_cleanup")
