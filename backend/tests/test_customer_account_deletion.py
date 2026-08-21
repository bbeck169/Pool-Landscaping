"""Feb-2026 · P11b — Customer self-service account deletion.

Six assertions against ``DELETE /api/customer-portal/account``:

  1. Auth required (401/403 unauthenticated).
  2. Role restricted — super_admin JWT → 403 ``role_not_permitted``.
  3. Happy path — first call: 200, response shape matches,
     ``deleted_at`` + ``anonymized_at`` stamped, PII scrubbed.
  4. Idempotent — second call returns 200 with the SAME
     ``anonymized_at``.
  5. Authored data preservation — customer's assigned jobs still
     exist post-deletion with the same ``customer_id``.
  6. Session invalidation — a follow-up authenticated request with
     the same JWT is rejected 401 (utils.get_current_user hard-401
     branch on ``deleted_at``).

Uses a synthetic tenant + customer/user pair per test so
``customer@aquaterra.com`` is never touched — the shared demo
account stays usable by other suites.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


# ── Synthetic fixture helpers ─────────────────────────────────────
def _mk_customer_account(*, tenant_id: str) -> dict:
    """Insert a synthetic ``customers`` + ``users`` pair scoped to a
    throwaway tenant.  Password is the shared demo secret."""
    from passlib.context import CryptContext
    pw = CryptContext(schemes=["bcrypt"], deprecated="auto").hash("password123")
    suffix = uuid.uuid4().hex[:10]
    cid = f"p11b-cust-{suffix}"
    uid = f"p11b-user-{suffix}"
    email = f"p11b-{suffix}@example.com"
    now = datetime.now(timezone.utc).isoformat()
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "email": email, "name": "P11b Test Customer",
        "first_name": "P11b", "last_name": "Customer",
        "phone": "+15555550101", "address": "1 Test Way",
        "avatar_url": "https://example.com/a.png",
        "notes": "seeded by test_customer_account_deletion",
        "created_at": now, "updated_at": now,
    })
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "customer_id": cid,
        "role": "customer", "email": email,
        "name": "P11b Test Customer", "password_hash": pw,
        "active": True, "created_at": now,
    })
    return {"user_id": uid, "customer_id": cid, "tenant_id": tenant_id,
            "email": email}


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _cleanup(ids: dict):
    _sync.customers.delete_many({"id": ids["customer_id"]})
    _sync.users.delete_many({"id": ids["user_id"]})
    _sync.account_deletion_events.delete_many(
        {"customer_id": ids["customer_id"]})
    _sync.jobs.delete_many({"customer_id": ids["customer_id"]})


@pytest.fixture
def synthetic_customer():
    tid = f"p11b-tenant-{uuid.uuid4().hex[:8]}"
    ids = _mk_customer_account(tenant_id=tid)
    yield ids
    _cleanup(ids)


# ── 1. Auth required ────────────────────────────────────────────
def test_delete_account_requires_auth():
    r = requests.delete(f"{API}/customer-portal/account", timeout=10)
    assert r.status_code in (401, 403), r.text


# ── 2. Role restricted — super_admin gets 403 ───────────────────
def test_delete_account_rejects_non_customer_role():
    # Reuse the seeded super-admin from the shared aquaterra fixture —
    # do NOT call delete against a real admin's user_id since a 403
    # short-circuits before any mutation happens.
    tok = _login("super@aquaterra.com")
    r = requests.delete(
        f"{API}/customer-portal/account",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 403, r.text
    assert "role_not_permitted" in r.text


# ── 3. Happy path — stamps + scrubs PII ─────────────────────────
def test_delete_account_happy_path_scrubs_pii(synthetic_customer):
    ids = synthetic_customer
    tok = _login(ids["email"])
    r = requests.delete(
        f"{API}/customer-portal/account",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] is True
    assert body["anonymized_at"], body

    cust = _sync.customers.find_one({"id": ids["customer_id"]})
    usr = _sync.users.find_one({"id": ids["user_id"]})
    for row_name, row in (("customers", cust), ("users", usr)):
        assert row["deleted_at"], f"{row_name}.deleted_at not set"
        assert row["anonymized_at"], f"{row_name}.anonymized_at not set"
        assert row["email"] == f"deleted-user-{ids['customer_id']}@example.invalid", \
            f"{row_name}.email not scrubbed → {row['email']!r}"
        assert row["name"] == "Deleted User"
        assert row["first_name"] == "Deleted"
        assert row["last_name"] == "User"
        assert row["phone"] is None
        assert row["address"] is None
        assert row["avatar_url"] is None
    # Audit trail row landed.
    ev = _sync.account_deletion_events.find_one(
        {"customer_id": ids["customer_id"]})
    assert ev is not None, "audit trail row not written"
    assert ev["tenant_id"] == ids["tenant_id"]
    assert ev["anonymized_at"] == body["anonymized_at"]


# ── 4. Idempotent — same anonymized_at on second call ───────────
def test_delete_account_is_idempotent(synthetic_customer):
    ids = synthetic_customer
    tok = _login(ids["email"])
    hdrs = {"Authorization": f"Bearer {tok}"}
    r1 = requests.delete(f"{API}/customer-portal/account", headers=hdrs,
                            timeout=10)
    assert r1.status_code == 200, r1.text
    ts1 = r1.json()["anonymized_at"]
    # Direct-DB unset ``deleted_at`` on the users row so the JWT
    # revives and we can simulate a legitimate re-call. This proves
    # the idempotency short-circuit fires on ``anonymized_at`` alone
    # (defensive-in-depth, per the endpoint docstring).
    _sync.users.update_one({"id": ids["user_id"]},
                            {"$set": {"deleted_at": None}})
    time.sleep(0.05)
    r2 = requests.delete(f"{API}/customer-portal/account", headers=hdrs,
                            timeout=10)
    assert r2.status_code == 200, r2.text
    assert r2.json()["anonymized_at"] == ts1, (
        "idempotent re-call must return the ORIGINAL anonymized_at"
    )


# ── 5. Authored data preservation — jobs stay owned ─────────────
def test_delete_account_preserves_authored_data(synthetic_customer):
    ids = synthetic_customer
    # Seed one job assigned to this customer.
    jid = f"p11b-job-{uuid.uuid4().hex[:8]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": ids["tenant_id"],
        "customer_id": ids["customer_id"],
        "title": "Weekly service",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    tok = _login(ids["email"])
    r = requests.delete(
        f"{API}/customer-portal/account",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    # Job still exists, still owned by the same customer_id.
    job = _sync.jobs.find_one({"id": jid})
    assert job is not None, "authored job was cascade-deleted"
    assert job["customer_id"] == ids["customer_id"], (
        "customer_id ownership must be preserved"
    )
    assert job["title"] == "Weekly service", (
        "authored job body must NOT be scrubbed"
    )


# ── 6. Session invalidation — JWT rejected on next request ──────
def test_delete_account_invalidates_active_session(synthetic_customer):
    ids = synthetic_customer
    tok = _login(ids["email"])
    hdrs = {"Authorization": f"Bearer {tok}"}
    # First call succeeds.
    r1 = requests.delete(f"{API}/customer-portal/account", headers=hdrs,
                            timeout=10)
    assert r1.status_code == 200, r1.text
    # Any subsequent authenticated request with the SAME JWT must be
    # rejected. ``/auth/me`` is the cheapest guarded probe.
    r2 = requests.get(f"{API}/auth/me", headers=hdrs, timeout=10)
    assert r2.status_code == 401, (
        f"active JWT must be rejected after account deletion → got "
        f"{r2.status_code} {r2.text}"
    )
    assert "account_deleted" in r2.text or "deleted" in r2.text.lower()
