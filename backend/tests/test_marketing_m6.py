"""Feb-2026 · Marketing Slice M6 — Automated review-request lifecycle."""
from __future__ import annotations

import asyncio, os, uuid, jwt
from datetime import datetime, timedelta, timezone

import pytest, requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(): return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}
@pytest.fixture(scope="module")
def tech_headers(): return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}
@pytest.fixture(scope="module")
def customer_headers(): return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro): return _LOOP.run_until_complete(coro)


def _rebind_db_to_loop():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.marketing_sequences as _seq
    _seq.db = fresh_db
    import services.marketing.segments as _seg
    _seg.db = fresh_db
    import services.marketing.drip_events as _de
    _de.db = fresh_db
    import routers.marketing_review_requests as _mrr
    _mrr.db = fresh_db
    try:
        import routers.marketing_preferences as _mp
        _mp.db = fresh_db
    except Exception:
        pass
    return fresh_db


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    _rebind_db_to_loop()
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"],
                               io_loop=_LOOP)[os.environ["DB_NAME"]]


def _pick_templates(admin_headers):
    r = requests.get(f"{API}/marketing/templates?active=true",
                      headers=admin_headers, timeout=15).json()
    email = next(t for t in r["templates"] if t["channel"] == "email")
    sms   = next(t for t in r["templates"] if t["channel"] == "sms")
    return email, sms


async def _tenant_of_admin():
    u = await _db().users.find_one({"email": "admin@aquaterra.com"},
                                    {"_id": 0, "tenant_id": 1})
    return u["tenant_id"]


async def _pick_customer():
    tid = await _tenant_of_admin()
    c = await _db().customers.find_one(
        {"tenant_id": tid}, {"_id": 0, "id": 1, "name": 1},
    )
    return tid, c


# ═══════════════════════════════════════════════════════════════════════
# Config CRUD + RBAC
# ═══════════════════════════════════════════════════════════════════════
def test_config_get_admin_only(admin_headers, tech_headers, customer_headers):
    r = requests.get(f"{API}/marketing/review-requests/config",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    for k in ("enabled", "channel", "delay_hours", "expire_days"):
        assert k in r.json()
    for h in (tech_headers, customer_headers):
        assert requests.get(f"{API}/marketing/review-requests/config",
                             headers=h, timeout=15).status_code in (401, 403)


def test_config_patch_channel_validation(admin_headers):
    email_tpl, sms_tpl = _pick_templates(admin_headers)
    # Enabling with email channel but no email_template_id → 422
    r = requests.patch(f"{API}/marketing/review-requests/config",
                        headers=admin_headers,
                        json={"enabled": True, "channel": "email",
                              "email_template_id": None},
                        timeout=15)
    assert r.status_code == 422

    # Enabling with sms channel but supplied email template → 422
    r = requests.patch(f"{API}/marketing/review-requests/config",
                        headers=admin_headers,
                        json={"enabled": True, "channel": "sms",
                              "sms_template_id": email_tpl["id"]},
                        timeout=15)
    assert r.status_code == 422

    # Happy path — email channel with a real email template.
    r = requests.patch(f"{API}/marketing/review-requests/config",
                        headers=admin_headers,
                        json={"enabled": True, "channel": "email",
                              "email_template_id": email_tpl["id"],
                              "delay_hours": 0,   # immediate for test speed
                              "expire_days": 14},
                        timeout=15)
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["enabled"] is True
    assert cfg["email_template_id"] == email_tpl["id"]
    assert cfg["delay_hours"] == 0


# ═══════════════════════════════════════════════════════════════════════
# Manual enqueue + duplicate guard + cancel
# ═══════════════════════════════════════════════════════════════════════
def test_manual_enqueue_and_duplicate_and_cancel(admin_headers):
    _tid, cust = _run(_pick_customer())
    r = requests.post(
        f"{API}/marketing/review-requests/manual/{cust['id']}",
        headers=admin_headers, json={}, timeout=15,
    )
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["status"] == "queued"
    assert row["channel"] == "email"
    assert "r/review?token=" in row["magic_link"]

    # Duplicate active row for the same customer + no service_report →
    # returns 409.
    r_dup = requests.post(
        f"{API}/marketing/review-requests/manual/{cust['id']}",
        headers=admin_headers, json={}, timeout=15,
    )
    assert r_dup.status_code == 409

    # Cancel → status flips to failed with halt_reason=cancelled.
    r_cancel = requests.post(
        f"{API}/marketing/review-requests/{row['id']}/cancel",
        headers=admin_headers, timeout=15,
    )
    assert r_cancel.status_code == 200
    assert r_cancel.json()["status"] == "failed"
    assert r_cancel.json()["halt_reason"] == "cancelled"

    # Re-cancel already-failed → 409.
    r_recancel = requests.post(
        f"{API}/marketing/review-requests/{row['id']}/cancel",
        headers=admin_headers, timeout=15,
    )
    assert r_recancel.status_code == 409

    # Now we can enqueue again (previous was failed).
    r2 = requests.post(
        f"{API}/marketing/review-requests/manual/{cust['id']}",
        headers=admin_headers, json={}, timeout=15,
    )
    assert r2.status_code == 201

    async def _clean():
        await _db().marketing_review_requests.delete_many(
            {"id": {"$in": [row["id"], r2.json()["id"]]}},
        )
    _run(_clean())


# ═══════════════════════════════════════════════════════════════════════
# End-to-end: enqueue → tick → sent → verify → submit-via-token → reviewed
# ═══════════════════════════════════════════════════════════════════════
def test_full_lifecycle_via_token(admin_headers):
    """Config already enabled + delay_hours=0 from the previous test.
    Enqueue manually, run tick, verify token, submit via token, assert
    the review-request row flips through queued → sent → opened →
    reviewed and the ``review_id`` + ``review_rating`` are set."""
    _tid, cust = _run(_pick_customer())

    # Fresh customer to avoid any lingering rows.
    async def _fresh_cust():
        db = _db()
        tid = await _tenant_of_admin()
        cid = f"m6-{uuid.uuid4().hex[:6]}"
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "M6 Tester",
            "email": "m6@test.local", "phone": "+15550100",
        })
        return tid, cid
    tid, cid = _run(_fresh_cust())

    try:
        r = requests.post(
            f"{API}/marketing/review-requests/manual/{cid}",
            headers=admin_headers, json={}, timeout=15,
        )
        assert r.status_code == 201, r.text
        row = r.json()
        assert row["status"] == "queued"

        # Tick — delay_hours=0 means next_send_at is <= now.
        async def _run_tick():
            from routers.marketing_review_requests import m6_tick_all_tenants
            return await m6_tick_all_tenants()
        tick_r = _run(_run_tick())
        assert tick_r["sent"] >= 1

        async def _fetch():
            return await _db().marketing_review_requests.find_one(
                {"id": row["id"]}, {"_id": 0},
            )
        after_tick = _run(_fetch())
        assert after_tick["status"] == "sent"
        assert after_tick["delivery_id"]
        assert after_tick["sent_at"]

        # A mock delivery landed in marketing_deliveries.
        async def _delivery():
            return await _db().marketing_deliveries.find_one(
                {"review_request_id": row["id"]}, {"_id": 0},
            )
        d = _run(_delivery())
        assert d is not None
        assert d["mock"] is True
        assert d["channel"] == "email"

        # Extract the magic-link token and verify.
        tok = row["magic_link"].split("token=", 1)[1].split("&")[0]
        r_v = requests.get(
            f"{API}/portal/review-token/verify?token={tok}",
            timeout=15,
        )
        assert r_v.status_code == 200, r_v.text
        verify = r_v.json()
        assert verify["review_request_id"] == row["id"]
        assert verify["customer_id"] == cid
        assert verify["customer_name"] == "M6 Tester"

        # First verify flipped status to opened.
        after_open = _run(_fetch())
        assert after_open["status"] == "opened"
        assert after_open["opened_at"]

        # Submit review via token — rating=5 → is_public=True.
        r_s = requests.post(
            f"{API}/portal/reviews/via-token",
            json={"token": tok, "rating": 5,
                  "comment": "M6 end-to-end trace"},
            timeout=15,
        )
        assert r_s.status_code == 201, r_s.text
        review = r_s.json()
        assert review["ok"] is True
        assert review["is_public"] is True

        final = _run(_fetch())
        assert final["status"] == "reviewed"
        assert final["review_id"] == review["review_id"]
        assert final["review_rating"] == 5
        assert final["reviewed_at"]

        # Second submit with same token → 409.
        r_s2 = requests.post(
            f"{API}/portal/reviews/via-token",
            json={"token": tok, "rating": 4, "comment": "dup"},
            timeout=15,
        )
        assert r_s2.status_code == 409

        # Review row got the review_request_id back-link.
        async def _review_doc():
            return await _db().customer_portal_reviews.find_one(
                {"id": review["review_id"]}, {"_id": 0},
            )
        doc = _run(_review_doc())
        assert doc["review_request_id"] == row["id"]
    finally:
        async def _clean():
            db = _db()
            await db.customers.delete_one({"id": cid})
            await db.marketing_review_requests.delete_many({"customer_id": cid})
            await db.customer_portal_reviews.delete_many({"customer_id": cid})
            await db.marketing_deliveries.delete_many({"customer_id": cid})
        _run(_clean())


# ═══════════════════════════════════════════════════════════════════════
# Token verification — expired + tampered
# ═══════════════════════════════════════════════════════════════════════
def test_token_expired_and_tampered():
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    secret = os.environ["JWT_SECRET"]
    # Expired token
    expired = jwt.encode({
        "sub": "rr", "cid": "x", "rid": "y", "srid": None,
        "iat": int((datetime.now(timezone.utc) - timedelta(days=60)).timestamp()),
        "exp": datetime.now(timezone.utc) - timedelta(days=1),
    }, secret, algorithm="HS256")
    r = requests.get(f"{API}/portal/review-token/verify?token={expired}",
                      timeout=15)
    assert r.status_code == 401

    # Wrong signature (right shape, different secret)
    tampered = jwt.encode({
        "sub": "rr", "cid": "x", "rid": "y", "srid": None,
        "exp": datetime.now(timezone.utc) + timedelta(days=1),
    }, "not-the-real-secret" + "x" * 40, algorithm="HS256")
    r2 = requests.get(f"{API}/portal/review-token/verify?token={tampered}",
                       timeout=15)
    assert r2.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# Expiry sweep
# ═══════════════════════════════════════════════════════════════════════
def test_expiry_sweep_flips_old_rows(admin_headers):
    async def _go():
        from routers.marketing_review_requests import m6_expiry_sweep
        db = _db()
        tid = await _tenant_of_admin()
        # Insert a queued row already past its expire_at.
        rid = f"m6-old-{uuid.uuid4().hex[:6]}"
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        await db.marketing_review_requests.insert_one({
            "id": rid, "tenant_id": tid, "customer_id": "ghost",
            "service_report_id": None, "drip_enrolment_id": None,
            "channel": "email", "template_id": None, "delivery_id": None,
            "magic_link": "/r/review?token=x",
            "status": "queued", "requested_at": past,
            "next_send_at": past, "expire_at": past,
            "sent_at": None, "opened_at": None, "reviewed_at": None,
            "review_id": None, "review_rating": None,
            "source": "manual",
            "created_at": past, "updated_at": past,
        })
        try:
            r = await m6_expiry_sweep()
            assert r["expired"] >= 1
            row = await db.marketing_review_requests.find_one({"id": rid}, {"_id": 0})
            assert row["status"] == "expired"
        finally:
            await db.marketing_review_requests.delete_one({"id": rid})

    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# service_completed hook enqueues automatically when tenant enabled
# ═══════════════════════════════════════════════════════════════════════
def test_hook_from_service_completed_helper(admin_headers):
    async def _go():
        from routers.marketing_review_requests import (
            enqueue_from_service_completed, _config_for,
        )
        tid = await _tenant_of_admin()
        cfg = await _config_for(tid)
        assert cfg["enabled"] is True   # left on by earlier config test

        cid = f"m6-sc-{uuid.uuid4().hex[:6]}"
        srid = f"m6-sr-{uuid.uuid4().hex[:6]}"
        await _db().customers.insert_one(
            {"id": cid, "tenant_id": tid, "name": "M6 ServCompl"},
        )
        try:
            row = await enqueue_from_service_completed(tid, cid, srid)
            assert row is not None
            assert row["service_report_id"] == srid
            # Duplicate: same (customer, service_report) → None.
            dup = await enqueue_from_service_completed(tid, cid, srid)
            assert dup is None
        finally:
            await _db().customers.delete_one({"id": cid})
            await _db().marketing_review_requests.delete_many({"customer_id": cid})

    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Cross-tenant isolation on GET/cancel
# ═══════════════════════════════════════════════════════════════════════
def test_cross_tenant_isolation(admin_headers):
    async def _seed():
        db = _db()
        mine = await _tenant_of_admin()
        others = await db.tenants.find(
            {"id": {"$ne": mine}}, {"_id": 0, "id": 1},
        ).to_list(1)
        assert others
        rid = f"m6-cross-{uuid.uuid4().hex[:6]}"
        await db.marketing_review_requests.insert_one({
            "id": rid, "tenant_id": others[0]["id"],
            "customer_id": "ghost", "service_report_id": None,
            "drip_enrolment_id": None, "channel": "email",
            "template_id": None, "delivery_id": None,
            "magic_link": "/r/review?token=x",
            "status": "queued", "requested_at": "2026-01-01T00:00:00+00:00",
            "next_send_at": "2026-01-01T00:00:00+00:00",
            "expire_at": "2027-01-01T00:00:00+00:00",
            "sent_at": None, "opened_at": None, "reviewed_at": None,
            "review_id": None, "review_rating": None,
            "source": "manual", "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        })
        return rid
    rid = _run(_seed())
    try:
        # LIST should not include the foreign row.
        rows = requests.get(
            f"{API}/marketing/review-requests?limit=500",
            headers=admin_headers, timeout=15,
        ).json()["review_requests"]
        assert rid not in {r["id"] for r in rows}
        # Cancel the foreign row → 404.
        r = requests.post(
            f"{API}/marketing/review-requests/{rid}/cancel",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 404
    finally:
        async def _clean():
            await _db().marketing_review_requests.delete_one({"id": rid})
        _run(_clean())
