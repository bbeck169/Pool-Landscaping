"""Resolve-duplicate · Phase 1 · Feb-2026 — pytest coverage for the
new ``POST /api/customers/{cid}/unbind-portal-email`` endpoint and
the enriched ``_upsert_customer_user`` 409 response shape.

Covers:
  1. Invite collision raises 409 with enriched payload (``error_code``
     + ``conflict`` object alongside legacy ``code`` / prefixes).
  2. Unbind with matching ``confirmation_name`` → 200, email cleared,
     portal user soft-deleted, audit row written.
  3. Unbind with mismatched ``confirmation_name`` → 400
     ``confirmation_name_mismatch``.
  4. Unbind for cross-tenant customer → 404 (tenant-scope guard).
  5. ``_portal_email_history`` array captures the previous binding.
  6. After unbind, the second ``_upsert_customer_user`` succeeds —
     end-to-end resolution verified.
  7. Session invalidation path — soft-delete sets ``deleted_at`` so
     the stateless-JWT ``get_current_user`` 401s on next request.
     (Verified via ``users.deleted_at`` + ``active=False`` state.)

Synthetic data only; no real PII.
"""
from __future__ import annotations

import uuid

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")

_FIXED_PW = "TempPass123!"


def _ids(prefix: str = "test-unbind") -> tuple[str, str]:
    tid = f"{prefix}-{uuid.uuid4()}"
    cid = str(uuid.uuid4())
    return tid, cid


async def _seed_customer(db, tid: str, cid: str, name: str, email: str):
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": name, "email": email,
    })


async def _cleanup(db, *tids: str):
    for tid in tids:
        await db.customers.delete_many({"tenant_id": tid})
        await db.users.delete_many({"tenant_id": tid})
        await db.audit_logs.delete_many({"tenant_id": tid})


# ─── 1 · 409 collision carries enriched conflict payload ─────────
def test_collision_raises_409_with_enriched_conflict_payload():
    tid, cid_a = _ids()
    cid_b = str(uuid.uuid4())
    email = f"e-{uuid.uuid4().hex[:8]}@synthetic.test"
    name_a = f"Alpha Conflict {uuid.uuid4().hex[:6]}"

    async def _run(db):
        try:
            await _seed_customer(db, tid, cid_a, name_a, email)
            await _seed_customer(
                db, tid, cid_b, "Beta Caller", email,
            )
            from routers.portal_admin import _upsert_customer_user
            # First invite — succeeds, binds email to A.
            await _upsert_customer_user(cid_a, tid, email, _FIXED_PW)
            # Second invite from B triggers the collision guard.
            with pytest.raises(HTTPException) as exc:
                await _upsert_customer_user(cid_b, tid, email, _FIXED_PW)
            assert exc.value.status_code == 409
            d = exc.value.detail
            # New fields.
            assert d["error_code"] == "email_bound_to_other_customer"
            assert "conflict" in d
            cf = d["conflict"]
            assert cf["customer_id"] == cid_a
            assert cf["customer_name"] == name_a
            assert cf["has_portal_password_set"] is True
            assert cf["has_active_portal_session"] is True
            # Legacy fields preserved — no breaking change for pre-FE
            # consumers (see /app/frontend/src/pages/customers/
            # __tests__/PortalInvite.collision.test.jsx).
            assert d["code"] == "portal_user_email_collision"
            assert d["existing_customer_id_prefix"] == cid_a[:8]
            assert d.get("message", "").startswith(
                "This email is already linked"
            )
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 2 · unbind success · email cleared + user soft-deleted + audit ─
def test_unbind_success_clears_email_softdeletes_user_writes_audit():
    tid, cid_a = _ids()
    cid_b = str(uuid.uuid4())
    email = f"u-{uuid.uuid4().hex[:8]}@synthetic.test"
    name_a = f"Alpha {uuid.uuid4().hex[:6]}"
    admin_id = f"admin-{uuid.uuid4().hex[:6]}"

    async def _run(db):
        try:
            await _seed_customer(db, tid, cid_a, name_a, email)
            await _seed_customer(db, tid, cid_b, "Beta", email)
            from routers.portal_admin import (
                _upsert_customer_user, unbind_portal_email,
                _UnbindPortalEmailBody,
            )
            await _upsert_customer_user(cid_a, tid, email, _FIXED_PW)

            # Direct call to the endpoint function with injected
            # auth deps — mirrors how other admin-endpoint tests in
            # this suite exercise ``portal_admin`` without a live
            # HTTP client.
            resp = await unbind_portal_email(
                cid=cid_a,
                body=_UnbindPortalEmailBody(confirmation_name=name_a),
                user={"id": admin_id, "email": "admin@example.test"},
                tenant={"id": tid},
            )
            assert resp["status"] == "ok"
            assert resp["released_email"] == email.lower()
            assert resp["users_soft_deleted"] == 1
            assert resp["portal_sessions_invalidated"] == 1

            # Email cleared on customers doc.
            cust = await db.customers.find_one(
                {"id": cid_a, "tenant_id": tid}, {"_id": 0},
            )
            assert cust.get("email") in (None, "")
            assert cust.get("has_login") is False

            # Users row soft-deleted — ``get_current_user`` will 401
            # on the next request for any live JWT bound to this row.
            row = await db.users.find_one(
                {"customer_id": cid_a, "tenant_id": tid}, {"_id": 0},
            )
            assert row is not None
            assert row.get("deleted_at")
            assert row.get("deleted_reason") == (
                "admin_unbind_portal_email_resolve_duplicate"
            )
            assert row.get("active") is False

            # Audit log row written.
            audit = await db.audit_logs.find_one({
                "tenant_id": tid,
                "event": "portal_email.unbound_by_admin",
                "target_customer_id": cid_a,
            }, {"_id": 0})
            assert audit is not None
            assert audit.get("actor_id") == admin_id
            assert audit.get("released_email") == email.lower()
            assert audit.get("session_invalidated") is True
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 3 · mismatched confirmation name → 400 ──────────────────────
def test_unbind_rejects_mismatched_confirmation_name():
    tid, cid = _ids()
    email = f"m-{uuid.uuid4().hex[:8]}@synthetic.test"
    name = f"Correct Name {uuid.uuid4().hex[:6]}"

    async def _run(db):
        try:
            await _seed_customer(db, tid, cid, name, email)
            from routers.portal_admin import (
                unbind_portal_email, _UnbindPortalEmailBody,
            )
            with pytest.raises(HTTPException) as exc:
                await unbind_portal_email(
                    cid=cid,
                    body=_UnbindPortalEmailBody(
                        confirmation_name="Totally Wrong",
                    ),
                    user={"id": "admin-1", "email": "a@x.test"},
                    tenant={"id": tid},
                )
            assert exc.value.status_code == 400
            assert exc.value.detail["error_code"] == (
                "confirmation_name_mismatch"
            )
            # Email NOT cleared — guard fired pre-mutation.
            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": tid}, {"_id": 0},
            )
            assert cust.get("email") == email
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 3b · case-insensitive, whitespace-collapsed name match ─────
def test_unbind_matches_name_case_insensitive_and_whitespace_collapsed():
    tid, cid = _ids()
    email = f"ci-{uuid.uuid4().hex[:8]}@synthetic.test"
    name = "Jane  Doe-Smith"   # double-space + mixed case input

    async def _run(db):
        try:
            await _seed_customer(db, tid, cid, name, email)
            from routers.portal_admin import (
                unbind_portal_email, _UnbindPortalEmailBody,
            )
            # Admin types with lowercase + single space — must match.
            resp = await unbind_portal_email(
                cid=cid,
                body=_UnbindPortalEmailBody(
                    confirmation_name="  jane doe-smith  ",
                ),
                user={"id": "admin-2", "email": "a@x.test"},
                tenant={"id": tid},
            )
            assert resp["status"] == "ok"
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 4 · cross-tenant customer → 404 ─────────────────────────────
def test_unbind_cross_tenant_returns_404():
    tid_a, cid = _ids()
    tid_b, _ = _ids()
    name = f"Cross {uuid.uuid4().hex[:6]}"

    async def _run(db):
        try:
            await _seed_customer(
                db, tid_a, cid, name, "x@synthetic.test",
            )
            from routers.portal_admin import (
                unbind_portal_email, _UnbindPortalEmailBody,
            )
            # Caller is in tid_b trying to unbind a cid in tid_a.
            with pytest.raises(HTTPException) as exc:
                await unbind_portal_email(
                    cid=cid,
                    body=_UnbindPortalEmailBody(confirmation_name=name),
                    user={"id": "admin-x", "email": "a@x.test"},
                    tenant={"id": tid_b},
                )
            assert exc.value.status_code == 404
        finally:
            await _cleanup(db, tid_a, tid_b)

    run_test(_run)


# ─── 5 · _portal_email_history archive ────────────────────────────
def test_unbind_appends_portal_email_history():
    tid, cid = _ids()
    email = f"h-{uuid.uuid4().hex[:8]}@synthetic.test"
    name = f"History {uuid.uuid4().hex[:6]}"
    admin_id = f"admin-{uuid.uuid4().hex[:6]}"

    async def _run(db):
        try:
            await _seed_customer(db, tid, cid, name, email)
            from routers.portal_admin import (
                _upsert_customer_user, unbind_portal_email,
                _UnbindPortalEmailBody,
            )
            await _upsert_customer_user(cid, tid, email, _FIXED_PW)
            await unbind_portal_email(
                cid=cid,
                body=_UnbindPortalEmailBody(confirmation_name=name),
                user={"id": admin_id, "email": "admin@example.test"},
                tenant={"id": tid},
            )
            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": tid}, {"_id": 0},
            )
            hist = cust.get("_portal_email_history") or []
            assert len(hist) == 1
            entry = hist[0]
            assert entry["email"] == email.lower()
            assert entry["reason"] == "resolve_duplicate_portal_invite"
            assert entry["unbound_by"] == admin_id
            assert entry.get("unbound_at")
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 6 · end-to-end · after unbind, original invite succeeds ─────
def test_after_unbind_original_invite_succeeds_end_to_end():
    tid, cid_conflict = _ids()
    cid_target = str(uuid.uuid4())
    email = f"e2e-{uuid.uuid4().hex[:8]}@synthetic.test"
    name_conflict = f"Conflict {uuid.uuid4().hex[:6]}"
    admin_id = f"admin-{uuid.uuid4().hex[:6]}"

    async def _run(db):
        try:
            await _seed_customer(
                db, tid, cid_conflict, name_conflict, email,
            )
            await _seed_customer(
                db, tid, cid_target, "Target Caller", email,
            )
            from routers.portal_admin import (
                _upsert_customer_user, unbind_portal_email,
                _UnbindPortalEmailBody,
            )
            # Original invite target hits the collision.
            await _upsert_customer_user(cid_conflict, tid, email, _FIXED_PW)
            with pytest.raises(HTTPException):
                await _upsert_customer_user(cid_target, tid, email, _FIXED_PW)
            # Admin unbinds the conflicting record.
            await unbind_portal_email(
                cid=cid_conflict,
                body=_UnbindPortalEmailBody(
                    confirmation_name=name_conflict,
                ),
                user={"id": admin_id, "email": "admin@example.test"},
                tenant={"id": tid},
            )
            # Retry the original invite — must succeed now.
            # First set the email on the TARGET customer (the UI
            # already has it on this record; test setup already
            # seeded it).  The invite call reads
            # ``customers.email``.
            await _upsert_customer_user(cid_target, tid, email, _FIXED_PW)
            rows = await db.users.find({
                "tenant_id": tid,
                "role": "customer",
                "customer_id": cid_target,
                "$or": [
                    {"deleted_at": None},
                    {"deleted_at": {"$exists": False}},
                    {"deleted_at": False},
                ],
            }, {"_id": 0}).to_list(5)
            assert len(rows) == 1
            assert rows[0]["email"] == email.lower()
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 7 · session invalidation signal present on soft-deleted row ─
def test_unbind_soft_deletes_row_so_jwt_401s_on_next_request():
    """Validates the stateless-JWT invalidation path: because
    ``backend/utils.get_current_user`` raises 401 ``account_deleted``
    on any user with ``deleted_at`` set, our soft-delete IS the
    session kill.  This test asserts the deleted_at flag + active=False
    are both persisted so the auth guard trips."""
    tid, cid = _ids()
    email = f"s-{uuid.uuid4().hex[:8]}@synthetic.test"
    name = f"Session {uuid.uuid4().hex[:6]}"

    async def _run(db):
        try:
            await _seed_customer(db, tid, cid, name, email)
            from routers.portal_admin import (
                _upsert_customer_user, unbind_portal_email,
                _UnbindPortalEmailBody,
            )
            await _upsert_customer_user(cid, tid, email, _FIXED_PW)
            # Simulate a prior portal login stamp so we're confident
            # ``has_active_portal_session`` would read as True.
            await db.users.update_one(
                {"customer_id": cid, "tenant_id": tid,
                  "role": "customer"},
                {"$set": {"last_portal_login_at": "2026-02-01T00:00:00Z"}},
            )
            resp = await unbind_portal_email(
                cid=cid,
                body=_UnbindPortalEmailBody(confirmation_name=name),
                user={"id": "admin-s", "email": "a@x.test"},
                tenant={"id": tid},
            )
            assert resp["portal_sessions_invalidated"] >= 1
            row = await db.users.find_one(
                {"customer_id": cid, "tenant_id": tid},
                {"_id": 0, "deleted_at": 1, "active": 1},
            )
            # Both signals present → ``get_current_user`` guards fire.
            assert row.get("deleted_at")
            assert row.get("active") is False
        finally:
            await _cleanup(db, tid)

    run_test(_run)
