"""PORTAL-INVITE-EMAIL-COLLISION-FIX · Feb-2026 (P0 #1 + P0 #2).

Shared-root-cause pytest for the ``_upsert_customer_user`` collision
guard that closes BOTH P0 tickets:
  • P0 #1 — "Customer portal temp-password login is broken."
  • P0 #2 — "Portal shows empty data after login."

Four cases:
  (a) Happy path · brand-new customer with unique email → INSERT
      succeeds; one ``users`` row persisted.
  (b) Re-invite SAME customer · UPDATE branch — no 409, hash
      rotated in-place; row count stays at one.
  (c) Collision · SECOND customer with the SAME email in the SAME
      tenant → raises ``HTTPException(409)`` with
      ``detail["code"] == "portal_user_email_collision"``.  Guard
      fails loudly BEFORE any INSERT so the DB stays at one row.
  (d) Cross-tenant · SECOND customer with the SAME email in a
      DIFFERENT tenant → NOT blocked.  Multi-tenant isolation
      preserved.

Synthetic data only.  No real customer PII; passwords are literal
fixtures (``"TempPass123!"``).
"""
from __future__ import annotations

import uuid

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")

_FIXED_PASSWORD = "TempPass123!"


def _ids() -> tuple:
    tid = f"test-portal-collision-{uuid.uuid4()}"
    cid = str(uuid.uuid4())
    return tid, cid


async def _seed_customer(db, tid: str, cid: str, email: str):
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "Synthetic Cust", "email": email,
    })


async def _cleanup(db, *tids: str):
    for tid in tids:
        await db.customers.delete_many({"tenant_id": tid})
        await db.users.delete_many({"tenant_id": tid})


# ─── (a) Happy path · unique email → INSERT ───────────────────────
def test_portal_upsert_happy_path_unique_email_inserts_one_row():
    tid, cid = _ids()
    email = f"a-{uuid.uuid4().hex[:8]}@synthetic.test"

    async def _run(db):
        try:
            await _seed_customer(db, tid, cid, email)
            from routers.portal_admin import _upsert_customer_user
            await _upsert_customer_user(cid, tid, email, _FIXED_PASSWORD)
            rows = await db.users.find(
                {"tenant_id": tid, "role": "customer"}, {"_id": 0}
            ).to_list(5)
            assert len(rows) == 1, rows
            assert rows[0]["customer_id"] == cid
            assert rows[0]["email"] == email.lower()
            assert rows[0]["must_change_password_on_next_login"] is True
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── (b) Re-invite same customer · UPDATE ─────────────────────────
def test_portal_upsert_reinvite_same_customer_rotates_hash_in_place():
    tid, cid = _ids()
    email = f"b-{uuid.uuid4().hex[:8]}@synthetic.test"

    async def _run(db):
        try:
            await _seed_customer(db, tid, cid, email)
            from routers.portal_admin import _upsert_customer_user
            await _upsert_customer_user(cid, tid, email, _FIXED_PASSWORD)
            row_1 = await db.users.find_one(
                {"tenant_id": tid, "customer_id": cid}, {"_id": 0},
            )
            hash_1 = row_1["password_hash"]
            # Second invite on the SAME customer — UPDATE path.
            await _upsert_customer_user(cid, tid, email, "DifferentPw456!")
            rows = await db.users.find(
                {"tenant_id": tid, "role": "customer"}, {"_id": 0},
            ).to_list(5)
            assert len(rows) == 1, (
                "re-invite must NOT create a second row; got "
                f"{len(rows)} rows"
            )
            assert rows[0]["id"] == row_1["id"]
            assert rows[0]["password_hash"] != hash_1
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── (c) Collision · same email, different customer_id → 409 ─────
def test_portal_upsert_email_collision_same_tenant_raises_409():
    tid, cid_a = _ids()
    cid_b = str(uuid.uuid4())
    email = f"c-{uuid.uuid4().hex[:8]}@synthetic.test"

    async def _run(db):
        try:
            await _seed_customer(db, tid, cid_a, email)
            await _seed_customer(db, tid, cid_b, email)
            from routers.portal_admin import _upsert_customer_user
            # First invite — succeeds, creates user U_A.
            await _upsert_customer_user(cid_a, tid, email, _FIXED_PASSWORD)
            # Second invite — SAME email, SAME tenant, DIFFERENT
            # customer_id.  Guard must fail with 409.
            with pytest.raises(HTTPException) as exc:
                await _upsert_customer_user(
                    cid_b, tid, email, "DifferentPw456!",
                )
            assert exc.value.status_code == 409
            assert exc.value.detail["code"] == (
                "portal_user_email_collision"
            )
            assert exc.value.detail["existing_customer_id_prefix"] == (
                cid_a[:8]
            )
            # Row count must still be 1 — the guard fires BEFORE
            # the INSERT branch.
            rows = await db.users.find(
                {"tenant_id": tid, "role": "customer"}, {"_id": 0},
            ).to_list(5)
            assert len(rows) == 1, (
                "collision guard must prevent the duplicate INSERT; "
                f"got {len(rows)} rows"
            )
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── (d) Cross-tenant collision allowed ───────────────────────────
def test_portal_upsert_same_email_different_tenant_not_blocked():
    tid_a, cid_a = _ids()
    tid_b, cid_b = _ids()
    email = f"d-{uuid.uuid4().hex[:8]}@synthetic.test"

    async def _run(db):
        try:
            await _seed_customer(db, tid_a, cid_a, email)
            await _seed_customer(db, tid_b, cid_b, email)
            from routers.portal_admin import _upsert_customer_user
            await _upsert_customer_user(cid_a, tid_a, email, _FIXED_PASSWORD)
            # Cross-tenant invite with the same email — multi-tenant
            # isolation means this is a legitimate separate customer.
            # Must NOT 409.
            await _upsert_customer_user(cid_b, tid_b, email, _FIXED_PASSWORD)
            rows_a = await db.users.find(
                {"tenant_id": tid_a, "role": "customer"}, {"_id": 0},
            ).to_list(5)
            rows_b = await db.users.find(
                {"tenant_id": tid_b, "role": "customer"}, {"_id": 0},
            ).to_list(5)
            assert len(rows_a) == 1
            assert len(rows_b) == 1
            assert rows_a[0]["customer_id"] == cid_a
            assert rows_b[0]["customer_id"] == cid_b
        finally:
            await _cleanup(db, tid_a, tid_b)

    run_test(_run)
