"""Phase I7 · Wave A · Feb-2026 — Communication timeline tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from tests._f7_loop_fixture import run_test


URL = "/api/customers/{cid}/communication-timeline"


def _get_app():
    from server import app
    return app


async def _ensure_tenant(db, tid="aquaterra"):
    from utils import now_iso
    ex = await db.tenants.find_one({"id": tid})
    if ex:
        if not ex.get("active"):
            await db.tenants.update_one({"id": tid}, {"$set": {"active": True}})
        return ex
    await db.tenants.insert_one({"id": tid, "slug": tid, "name": tid,
                                       "active": True, "created_at": now_iso()})
    return {"id": tid}


async def _make_token(db, role, email, tid="aquaterra", customer_id=None):
    from utils import create_token, new_id
    from datetime import datetime, timezone
    ex = await db.users.find_one({"email": email})
    if ex:
        patch = {}
        if ex.get("role") != role:
            patch["role"] = role
        if customer_id and ex.get("customer_id") != customer_id:
            patch["customer_id"] = customer_id
        if patch:
            await db.users.update_one({"email": email}, {"$set": patch})
            ex.update(patch)
        return create_token(ex)
    doc = {"id": new_id(), "email": email, "role": role,
              "tenant_id": tid, "active": True,
              "created_at": datetime.now(timezone.utc).isoformat()}
    if customer_id:
        doc["customer_id"] = customer_id
    await db.users.insert_one(dict(doc))
    return create_token(doc)


async def _seed_customer(db, cid="cust_i7_1", tid="aquaterra"):
    from utils import now_iso
    await db.customers.delete_one({"id": cid})
    await db.customers.insert_one({
        "id": cid, "tenant_id": tid, "name": "Test",
        "email": "test@example.com", "phone": "+15555550100",
        "created_at": now_iso(),
    })


async def _seed_dispatch(db, cid, channel, status, sent_at, subject="",
                              tid="aquaterra", error=None, meta=None,
                              recipient=None):
    from utils import new_id
    await db.notification_dispatch_log.insert_one({
        "id": new_id(), "tenant_id": tid, "recipient_id": cid,
        "channel": channel, "notification_type": "test",
        "resolved_address": recipient or ("test@example.com"
                                              if channel == "email"
                                              else "+15555550100"),
        "subject": subject, "status": status,
        "sent_at": sent_at, "reserved_at": sent_at,
        "error": error, "attempt_count": 1,
        "dedupe_key": f"dk_{new_id()}",
        "metadata": meta or {},
    })


async def _cleanup(db, cid, tid="aquaterra"):
    await db.notification_dispatch_log.delete_many(
        {"tenant_id": tid, "recipient_id": cid})
    await db.audit_events.delete_many({"tenant_id": tid,
                                             "payload.customer_ids": cid})
    await db.customers.delete_one({"id": cid})


# ═══════════════════════════════════════════════════════════════════
def test_i7_merges_and_sorts_desc():
    async def _go(db):
        await _ensure_tenant(db)
        cid = "cust_i7_merge"
        await _seed_customer(db, cid)
        # 3 dispatches at t0, t0+1min, t0+2min
        now = datetime.now(timezone.utc)
        for i, (ch, subj) in enumerate([
            ("sms", ""), ("email", "Invoice #1"), ("sms", ""),
        ]):
            await _seed_dispatch(db, cid, ch, "sent",
                                       (now + timedelta(minutes=i)).isoformat(),
                                       subject=subj)
        token = await _make_token(db, "admin", "i7admin@aquaterra.com")
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_get_app()),
                base_url="http://test",
            ) as ac:
                r = await ac.get(URL.format(cid=cid),
                                       headers={"Authorization": f"Bearer {token}"})
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["customer_id"] == cid
                assert len(body["items"]) == 3
                # Sorted desc by occurred_at.
                ts = [it["occurred_at"] for it in body["items"]]
                assert ts == sorted(ts, reverse=True)
                # Types + subject preserved.
                emails = [it for it in body["items"] if it["type"] == "email"]
                assert len(emails) == 1
                assert emails[0]["subject"] == "Invoice #1"
                assert body["has_more"] is False
        finally:
            await _cleanup(db, cid)

    run_test(_go)


def test_i7_types_filter_sms_only():
    async def _go(db):
        await _ensure_tenant(db)
        cid = "cust_i7_types"
        await _seed_customer(db, cid)
        now = datetime.now(timezone.utc)
        await _seed_dispatch(db, cid, "sms", "sent",
                                 now.isoformat())
        await _seed_dispatch(db, cid, "email", "sent",
                                 (now + timedelta(minutes=1)).isoformat(),
                                 subject="Hi")
        token = await _make_token(db, "admin", "i7admin@aquaterra.com")
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_get_app()),
                base_url="http://test",
            ) as ac:
                r = await ac.get(URL.format(cid=cid) + "?types=sms",
                                       headers={"Authorization": f"Bearer {token}"})
                assert r.status_code == 200, r.text
                types = {it["type"] for it in r.json()["items"]}
                assert types == {"sms"}
        finally:
            await _cleanup(db, cid)

    run_test(_go)


def test_i7_pagination_via_before_cursor():
    async def _go(db):
        await _ensure_tenant(db)
        cid = "cust_i7_page"
        await _seed_customer(db, cid)
        base = datetime.now(timezone.utc)
        # Seed 5 rows spaced 1 min apart.
        for i in range(5):
            await _seed_dispatch(
                db, cid, "sms", "sent",
                (base + timedelta(minutes=i)).isoformat(),
            )
        token = await _make_token(db, "admin", "i7admin@aquaterra.com")
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_get_app()),
                base_url="http://test",
            ) as ac:
                r1 = await ac.get(URL.format(cid=cid) + "?limit=2",
                                        headers={"Authorization": f"Bearer {token}"})
                b1 = r1.json()
                assert len(b1["items"]) == 2
                assert b1["has_more"] is True
                assert b1["next_before"]
                r2 = await ac.get(
                    URL.format(cid=cid)
                        + f"?limit=2&before={b1['next_before']}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                b2 = r2.json()
                assert len(b2["items"]) == 2
                # No overlap with page 1.
                p1_ids = {it["id"] for it in b1["items"]}
                p2_ids = {it["id"] for it in b2["items"]}
                assert p1_ids.isdisjoint(p2_ids)
        finally:
            await _cleanup(db, cid)

    run_test(_go)


def test_i7_rbac_customer_own_record_gets_stripped_fields():
    async def _go(db):
        await _ensure_tenant(db)
        cid = "cust_i7_own"
        await _seed_customer(db, cid)
        now = datetime.now(timezone.utc)
        await _seed_dispatch(
            db, cid, "email", "failed", now.isoformat(),
            subject="Failed", error="bounce",
        )
        token = await _make_token(db, "customer", "i7own@aquaterra.com",
                                        customer_id=cid)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_get_app()),
                base_url="http://test",
            ) as ac:
                r = await ac.get(URL.format(cid=cid),
                                       headers={"Authorization": f"Bearer {token}"})
                assert r.status_code == 200, r.text
                items = r.json()["items"]
                assert len(items) == 1
                # Portal filtering: admin-only fields stripped.
                assert "actor_user_id" not in items[0]
                assert "delivery_error" not in items[0]
                # Common fields still present.
                assert items[0]["type"] == "email"
                assert items[0]["delivery_status"] == "failed"
                assert items[0]["subject"] == "Failed"
        finally:
            await _cleanup(db, cid)

    run_test(_go)


def test_i7_rbac_admin_sees_admin_only_fields():
    async def _go(db):
        await _ensure_tenant(db)
        cid = "cust_i7_admin_view"
        await _seed_customer(db, cid)
        await _seed_dispatch(
            db, cid, "email", "failed",
            datetime.now(timezone.utc).isoformat(),
            error="bounce", meta={"actor_user_id": "u_1"},
        )
        token = await _make_token(db, "admin", "i7admin@aquaterra.com")
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_get_app()),
                base_url="http://test",
            ) as ac:
                r = await ac.get(URL.format(cid=cid),
                                       headers={"Authorization": f"Bearer {token}"})
                items = r.json()["items"]
                assert items[0]["delivery_error"] == "bounce"
                assert items[0]["actor_user_id"] == "u_1"
        finally:
            await _cleanup(db, cid)

    run_test(_go)


def test_i7_rbac_customer_cannot_view_other():
    async def _go(db):
        await _ensure_tenant(db)
        cid_a = "cust_i7_a"
        cid_b = "cust_i7_b"
        await _seed_customer(db, cid_a)
        await _seed_customer(db, cid_b)
        token = await _make_token(db, "customer", "i7cust@aquaterra.com",
                                        customer_id=cid_a)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_get_app()),
                base_url="http://test",
            ) as ac:
                r = await ac.get(URL.format(cid=cid_b),
                                       headers={"Authorization": f"Bearer {token}"})
                assert r.status_code == 403, r.text
        finally:
            await _cleanup(db, cid_a)
            await _cleanup(db, cid_b)

    run_test(_go)


def test_i7_rbac_tech_gets_403():
    async def _go(db):
        await _ensure_tenant(db)
        cid = "cust_i7_tech"
        await _seed_customer(db, cid)
        token = await _make_token(db, "tech", "i7tech@aquaterra.com")
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_get_app()),
                base_url="http://test",
            ) as ac:
                r = await ac.get(URL.format(cid=cid),
                                       headers={"Authorization": f"Bearer {token}"})
                assert r.status_code == 403, r.text
        finally:
            await _cleanup(db, cid)

    run_test(_go)


def test_i7_empty_customer_returns_empty_list():
    async def _go(db):
        await _ensure_tenant(db)
        cid = "cust_i7_empty"
        await _seed_customer(db, cid)
        token = await _make_token(db, "admin", "i7admin@aquaterra.com")
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_get_app()),
                base_url="http://test",
            ) as ac:
                r = await ac.get(URL.format(cid=cid),
                                       headers={"Authorization": f"Bearer {token}"})
                b = r.json()
                assert b["items"] == []
                assert b["has_more"] is False
                assert b["next_before"] is None
        finally:
            await _cleanup(db, cid)

    run_test(_go)


def test_i7_tenant_isolation():
    async def _go(db):
        await _ensure_tenant(db, "aquaterra")
        await _ensure_tenant(db, "other-tenant")
        cid_a = "cust_i7_iso_a"
        cid_b = "cust_i7_iso_b"
        # A owns aquaterra dispatch, B owns other-tenant dispatch.
        # Aquaterra admin querying cid_a MUST NOT see B's row.
        await _seed_customer(db, cid_a, tid="aquaterra")
        await _seed_customer(db, cid_b, tid="other-tenant")
        await _seed_dispatch(
            db, cid_b, "sms", "sent",
            datetime.now(timezone.utc).isoformat(),
            tid="other-tenant",
        )
        token = await _make_token(db, "admin", "i7admin@aquaterra.com",
                                        tid="aquaterra")
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_get_app()),
                base_url="http://test",
            ) as ac:
                r = await ac.get(URL.format(cid=cid_a),
                                       headers={"Authorization": f"Bearer {token}"})
                assert r.status_code == 200, r.text
                b = r.json()
                assert b["items"] == []
        finally:
            await _cleanup(db, cid_a, tid="aquaterra")
            await _cleanup(db, cid_b, tid="other-tenant")

    run_test(_go)


def test_i7_audit_event_portal_invite_bulk_included():
    async def _go(db):
        await _ensure_tenant(db)
        cid = "cust_i7_audit"
        await _seed_customer(db, cid)
        from utils import new_id
        await db.audit_events.insert_one({
            "id": new_id(), "tenant_id": "aquaterra",
            "event_type": "portal_invite_bulk",
            "actor_email": "admin@aquaterra.com",
            "actor_id": "u_admin",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"customer_ids": [cid], "sent": 1,
                             "skipped_already_activated": 0},
        })
        token = await _make_token(db, "admin", "i7admin@aquaterra.com")
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_get_app()),
                base_url="http://test",
            ) as ac:
                r = await ac.get(URL.format(cid=cid),
                                       headers={"Authorization": f"Bearer {token}"})
                items = r.json()["items"]
                assert any(it["subject"] == "Portal invite"
                                for it in items)
                inv = next(it for it in items if it["subject"] == "Portal invite")
                assert inv["actor_label"] == "admin@aquaterra.com"
                assert inv["type"] == "email"
        finally:
            await _cleanup(db, cid)

    run_test(_go)
