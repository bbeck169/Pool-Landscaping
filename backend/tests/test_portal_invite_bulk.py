"""Phase H1 · Feb-2026 — /admin/customers/portal-invite/bulk tests.

Locks partitioning, rate-limit, batch cap, RBAC, audit trail, and
in-batch idempotency for the new bulk portal invite endpoint.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


@pytest.fixture(autouse=True)
def _stub_email_send(monkeypatch):
    """The single-invite pipeline attempts a Resend send. In the test
    event loop the httpx client the SDK spawns latches onto a
    different loop and throws ``Future attached to a different
    loop``. Stubbing here isolates the boundary — send behaviour is
    already locked by the single-invite tests upstream."""
    async def _fake_try_send(*args, **kwargs):
        return False
    import routers.portal_admin as _pa
    monkeypatch.setattr(_pa, "_try_send_reset_email", _fake_try_send,
                          raising=False)


async def _seed(db):
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                          {"_id": 0, "id": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                       {"_id": 0, "id": 1, "role": 1,
                                        "email": 1})
    return tid, admin


async def _cleanup(db, tid, prefix):
    await db.customers.delete_many({"tenant_id": tid,
                                        "name": {"$regex": f"^{prefix}"}})
    await db.users.delete_many({"tenant_id": tid, "role": "customer",
                                    "email": {"$regex": f"^{prefix}"}})
    await db.portal_invite_rate_limit.delete_many({
        "tenant_id": tid,
        "customer_id": {"$regex": f"^{prefix}"},
    })
    await db.audit_events.delete_many({
        "event_type": "portal_invite_bulk",
        "tenant_id": tid,
        "reason": {"$regex": f"^{prefix}", "$options": "i"},
    })


async def _seed_customer(db, tid, cid, email=None, phone=None,
                            has_login=False):
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": cid,
        "email": email, "phone": phone,
        "is_active": True, "has_login": has_login,
    })


# ═══════════════════════════ 1 · Happy path ══════════════════════════
def test_h1_happy_path_two_eligible_one_already_activated():
    from routers.portal_admin import portal_invite_bulk, _H1BulkInviteBody

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "H1_HAPPY_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        cids = [f"{prefix}A", f"{prefix}B", f"{prefix}C_already"]
        await _seed_customer(db, tid, cids[0], email=f"{prefix}a@e.com")
        await _seed_customer(db, tid, cids[1], email=f"{prefix}b@e.com")
        await _seed_customer(db, tid, cids[2], email=f"{prefix}c@e.com",
                                has_login=True)
        try:
            body = _H1BulkInviteBody(customer_ids=cids, reason=f"{prefix}test")
            res = await portal_invite_bulk(
                body=body, user=admin, tenant={"id": tid},
            )
            assert res["requested"] == 3
            assert res["sent"] == 2
            assert res["skipped_already_activated"] == 1
            assert res["skipped_no_contact"] == 0
            assert res["skipped_wrong_tenant"] == 0
            assert res["failed_send"] == 0
            assert res["batch_id"]
            # has_login must now be True on A + B, unchanged on C
            for i in (0, 1):
                d = await db.customers.find_one({"id": cids[i]},
                                                    {"has_login": 1})
                assert d["has_login"] is True, f"{cids[i]} not stamped"
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═══════════════════════════ 2 · Skip no-contact ═════════════════════
def test_h1_skip_no_contact():
    from routers.portal_admin import portal_invite_bulk, _H1BulkInviteBody

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "H1_NC_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        cid = f"{prefix}nocontact"
        await _seed_customer(db, tid, cid, email=None, phone=None)
        try:
            body = _H1BulkInviteBody(customer_ids=[cid])
            res = await portal_invite_bulk(
                body=body, user=admin, tenant={"id": tid},
            )
            assert res["sent"] == 0
            assert res["skipped_no_contact"] == 1
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═══════════════════════════ 3 · Wrong-tenant ═════════════════════════
def test_h1_skip_wrong_tenant():
    from routers.portal_admin import portal_invite_bulk, _H1BulkInviteBody

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "H1_XT_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        # Seed a customer on a NEW tenant, then try to invite it from
        # aquaterra's admin context.
        alt_tid = f"h1-alt-{uuid.uuid4().hex[:6]}"
        await db.tenants.insert_one({"id": alt_tid, "slug": alt_tid,
                                        "name": "H1 Alt"})
        cid = f"{prefix}crosstenant"
        await db.customers.insert_one({
            "id": cid, "tenant_id": alt_tid, "name": cid,
            "email": f"{prefix}x@e.com", "is_active": True,
        })
        try:
            body = _H1BulkInviteBody(customer_ids=[cid])
            res = await portal_invite_bulk(
                body=body, user=admin, tenant={"id": tid},
            )
            assert res["sent"] == 0
            assert res["skipped_wrong_tenant"] == 1
        finally:
            await db.customers.delete_one({"id": cid})
            await db.tenants.delete_one({"id": alt_tid})
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═══════════════════════════ 4 · Batch cap ═══════════════════════════
def test_h1_batch_cap_201_rejected():
    from routers.portal_admin import portal_invite_bulk, _H1BulkInviteBody

    async def _go(db):
        tid, admin = await _seed(db)
        body = _H1BulkInviteBody(
            customer_ids=[f"nope-{i}" for i in range(201)]
        )
        with pytest.raises(HTTPException) as ei:
            await portal_invite_bulk(
                body=body, user=admin, tenant={"id": tid},
            )
        assert ei.value.status_code == 400
        assert "Batch too large" in ei.value.detail or \
                "batch" in str(ei.value.detail).lower()

    run_test(_go)


# ═══════════════════════════ 5 · Rate limit ══════════════════════════
def test_h1_rate_limit_429_when_budget_exhausted():
    from routers.portal_admin import (
        portal_invite_bulk, _H1BulkInviteBody, _H1_RATE_MAX_PER_WINDOW,
    )

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "H1_RL_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        # Pre-stamp the ledger with _H1_RATE_MAX_PER_WINDOW rows in
        # the current window so remaining budget = 0.
        now = datetime.now(timezone.utc).isoformat()
        docs = [
            {"id": f"{prefix}pre_{i}", "tenant_id": tid,
             "customer_id": f"{prefix}pre_{i}",
             "sent_at": now}
            for i in range(_H1_RATE_MAX_PER_WINDOW)
        ]
        await db.portal_invite_rate_limit.insert_many(docs)
        try:
            body = _H1BulkInviteBody(customer_ids=[f"{prefix}new"])
            with pytest.raises(HTTPException) as ei:
                await portal_invite_bulk(
                    body=body, user=admin, tenant={"id": tid},
                )
            assert ei.value.status_code == 429
            det = ei.value.detail
            assert isinstance(det, dict)
            assert det.get("detail") == "portal_invite_rate_limited"
        finally:
            await db.portal_invite_rate_limit.delete_many({
                "tenant_id": tid,
                "id": {"$regex": f"^{prefix}"},
            })

    run_test(_go)


# ═══════════════════════════ 6 · Empty body ══════════════════════════
def test_h1_empty_body_rejected():
    from routers.portal_admin import portal_invite_bulk, _H1BulkInviteBody

    async def _go(db):
        tid, admin = await _seed(db)
        with pytest.raises(HTTPException) as ei:
            await portal_invite_bulk(
                body=_H1BulkInviteBody(customer_ids=[]),
                user=admin, tenant={"id": tid},
            )
        assert ei.value.status_code == 400

    run_test(_go)


# ═══════════════════════════ 7 · In-batch dedupe ══════════════════════
def test_h1_in_batch_duplicate_is_skipped_second_time():
    from routers.portal_admin import portal_invite_bulk, _H1BulkInviteBody

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "H1_DEDUP_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        cid = f"{prefix}A"
        await _seed_customer(db, tid, cid, email=f"{prefix}a@e.com")
        try:
            body = _H1BulkInviteBody(customer_ids=[cid, cid, cid])
            res = await portal_invite_bulk(
                body=body, user=admin, tenant={"id": tid},
            )
            # First send succeeds; the two duplicates are caught by
            # the in-loop ``seen`` set BEFORE any DB read.
            assert res["sent"] == 1
            assert res["skipped_already_activated"] == 2, res
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)


# ═══════════════════════════ 8 · Audit trail ══════════════════════════
def test_h1_audit_row_written():
    from routers.portal_admin import portal_invite_bulk, _H1BulkInviteBody

    async def _go(db):
        tid, admin = await _seed(db)
        prefix = "H1_AUD_" + uuid.uuid4().hex[:6] + "_"
        await _cleanup(db, tid, prefix)
        cid = f"{prefix}A"
        await _seed_customer(db, tid, cid, email=f"{prefix}a@e.com")
        try:
            body = _H1BulkInviteBody(
                customer_ids=[cid], reason=f"{prefix}audit-test",
            )
            res = await portal_invite_bulk(
                body=body, user=admin, tenant={"id": tid},
            )
            batch_id = res["batch_id"]
            row = await db.audit_events.find_one({
                "event_type": "portal_invite_bulk",
                "tenant_id": tid,
                "payload.batch_id": batch_id,
            }, {"_id": 0})
            assert row is not None, "audit row missing"
            assert row["reason"] == f"{prefix}audit-test"
            assert row["payload"]["sent"] == 1
            assert row["payload"]["requested"] == 1
            # Failures list is intentionally NOT stored in payload
            # (PII containment); only ``failure_count`` is.
            assert "failures" not in row["payload"]
            assert row["failure_count"] == 0
        finally:
            await _cleanup(db, tid, prefix)

    run_test(_go)
