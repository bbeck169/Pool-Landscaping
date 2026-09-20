"""Feb-2026 · P2 — ``POST /customer-portal/tutorial/complete``.

Four assertions against the new idempotent endpoint that persists the
customer walkthrough completion.  Reuses the pre-existing
``portal_walkthrough_completed_at`` field on ``customers`` so the flag
has one source of truth.

  1. Auth required — unauthenticated call → 401/403.
  2. First call sets the timestamp, returns ``already_completed=false``.
  3. Second call is idempotent — returns SAME timestamp, ``already_completed=true``.
  4. Cross-tenant isolation — a synthetic second-tenant customer marking
     their own tutorial cannot see or overwrite tenant A's timestamp.

Follows the ``test_route_optimization_approval.py`` conventions:
* Live HTTP against ``http://localhost:8001/api``.
* Sync ``pymongo`` for setup + assertions; auto-clean the flag before
  and after each test so parallel-run isolation is preserved.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def customer_h():
    return _hdrs("customer@aquaterra.com")


@pytest.fixture
def customer_ids():
    u = _sync.users.find_one({"email": "customer@aquaterra.com"})
    return {"user_id": u["id"], "customer_id": u["customer_id"], "tenant_id": u["tenant_id"]}


def _reset_flag(customer_id: str, tenant_id: str):
    _sync.customers.update_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"$unset": {"portal_walkthrough_completed_at": "", "tutorial_last_step": ""}},
    )


# ── 1. Auth required ────────────────────────────────────────────────
def test_tutorial_complete_requires_auth():
    r = requests.post(f"{API}/customer-portal/tutorial/complete", timeout=10)
    assert r.status_code in (401, 403), r.text


# ── 2. First call sets timestamp, already_completed=false ──────────
def test_tutorial_complete_first_call_sets_timestamp(customer_h, customer_ids):
    _reset_flag(customer_ids["customer_id"], customer_ids["tenant_id"])
    try:
        r = requests.post(f"{API}/customer-portal/tutorial/complete",
                            headers=customer_h, json={"step": "final"}, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["already_completed"] is False
        assert body["tutorial_completed_at"], body
        # Field landed on the customer doc.
        row = _sync.customers.find_one(
            {"id": customer_ids["customer_id"], "tenant_id": customer_ids["tenant_id"]},
            {"_id": 0, "portal_walkthrough_completed_at": 1, "tutorial_last_step": 1},
        )
        assert row["portal_walkthrough_completed_at"] == body["tutorial_completed_at"]
        # Optional step body is stashed for future granularity.
        assert row.get("tutorial_last_step") == "final"
    finally:
        _reset_flag(customer_ids["customer_id"], customer_ids["tenant_id"])


# ── 3. Idempotent on repeat ─────────────────────────────────────────
def test_tutorial_complete_idempotent(customer_h, customer_ids):
    _reset_flag(customer_ids["customer_id"], customer_ids["tenant_id"])
    try:
        r1 = requests.post(f"{API}/customer-portal/tutorial/complete",
                            headers=customer_h, timeout=10)
        assert r1.status_code == 200
        ts1 = r1.json()["tutorial_completed_at"]
        assert r1.json()["already_completed"] is False

        # Sleep long enough that ``now_iso()`` would produce a different
        # value if the endpoint were incorrectly overwriting.
        time.sleep(1.1)

        r2 = requests.post(f"{API}/customer-portal/tutorial/complete",
                            headers=customer_h, timeout=10)
        assert r2.status_code == 200
        body = r2.json()
        assert body["already_completed"] is True
        assert body["tutorial_completed_at"] == ts1, (
            f"idempotency failed — timestamp shifted: {ts1} → {body['tutorial_completed_at']}"
        )
    finally:
        _reset_flag(customer_ids["customer_id"], customer_ids["tenant_id"])


# ── 4. Cross-tenant isolation ───────────────────────────────────────
def test_tutorial_complete_cross_tenant_isolation(customer_h, customer_ids):
    """Seed a synthetic 2nd-tenant customer + user, mark THEIR tutorial,
    verify aquaterra's customer flag is untouched."""
    from utils import hash_password
    other_tid = f"test_tutorial_tenant_{uuid.uuid4().hex[:8]}"
    other_email = f"test_tutorial_cust_{uuid.uuid4().hex[:6]}@example.com"
    other_cid = f"test_tutorial_cust_id_{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({"id": other_tid, "name": "TEST_tutorial_tenant"})
    _sync.customers.insert_one({
        "id": other_cid, "tenant_id": other_tid,
        "name": "TEST tutorial customer",
    })
    _sync.users.insert_one({
        "id": f"test_tutorial_u_{uuid.uuid4().hex[:8]}",
        "tenant_id": other_tid,
        "customer_id": other_cid,
        "email": other_email,
        "name": "TEST tutorial customer",
        "role": "customer",
        "active": True,
        "password_hash": hash_password("password123"),
    })

    _reset_flag(customer_ids["customer_id"], customer_ids["tenant_id"])
    try:
        # Prime aquaterra so we have a value to protect.
        r0 = requests.post(f"{API}/customer-portal/tutorial/complete",
                            headers=customer_h, timeout=10)
        aqua_ts = r0.json()["tutorial_completed_at"]

        # Other-tenant customer marks their own tutorial.
        other_h = _hdrs(other_email)
        r_other = requests.post(f"{API}/customer-portal/tutorial/complete",
                                  headers=other_h, timeout=10)
        assert r_other.status_code == 200
        other_ts = r_other.json()["tutorial_completed_at"]

        # Aquaterra's customer flag MUST be unchanged.
        aqua_row = _sync.customers.find_one(
            {"id": customer_ids["customer_id"], "tenant_id": customer_ids["tenant_id"]},
            {"_id": 0, "portal_walkthrough_completed_at": 1},
        )
        assert aqua_row["portal_walkthrough_completed_at"] == aqua_ts, (
            "cross-tenant leak — other-tenant call rewrote aquaterra's flag"
        )
        # The other tenant landed on its OWN customer doc.
        other_row = _sync.customers.find_one(
            {"id": other_cid, "tenant_id": other_tid},
            {"_id": 0, "portal_walkthrough_completed_at": 1},
        )
        assert other_row["portal_walkthrough_completed_at"] == other_ts
    finally:
        _reset_flag(customer_ids["customer_id"], customer_ids["tenant_id"])
        _sync.users.delete_many({"email": other_email})
        _sync.customers.delete_one({"id": other_cid})
        _sync.tenants.delete_one({"id": other_tid})
