"""Feb-2026 · Marketing Slice F — Preferences + Suppression list."""
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
    for modname in ("routers.marketing_preferences",
                     "routers.marketing_sequences",
                     "routers.marketing_review_requests",
                     "services.marketing.drip_events"):
        import importlib
        try:
            m = importlib.import_module(modname)
            m.db = fresh_db
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


async def _tenant_of_admin():
    u = await _db().users.find_one({"email": "admin@aquaterra.com"},
                                    {"_id": 0, "tenant_id": 1})
    return u["tenant_id"]


# ═══════════════════════════════════════════════════════════════════════
# Customer preferences · logged-in flow
# ═══════════════════════════════════════════════════════════════════════
def test_customer_prefs_default_all_true(customer_headers):
    r = requests.get(f"{API}/customer-portal/preferences",
                      headers=customer_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["channel_opt_in"]["email_marketing"] is True
    assert body["channel_opt_in"]["email_transactional"] is True
    assert body["channel_opt_in"]["sms_transactional"] is True
    assert body["category_opt_in"]["review_requests"] is True


def test_customer_prefs_transactional_locked(customer_headers):
    """Flipping any transactional flag off → 422."""
    for key in ("email_transactional", "sms_transactional"):
        r = requests.patch(
            f"{API}/customer-portal/preferences",
            headers=customer_headers,
            json={"channel_opt_in": {key: False}},
            timeout=15,
        )
        assert r.status_code == 422, (key, r.text)


def test_customer_prefs_admin_and_tech_blocked(admin_headers, tech_headers):
    for h in (admin_headers, tech_headers):
        assert requests.get(f"{API}/customer-portal/preferences",
                             headers=h, timeout=15).status_code in (401, 403)


def test_customer_prefs_off_creates_suppression(customer_headers):
    """PATCH email_marketing=false → suppression row auto-created;
    PATCH back to true → suppression soft-deleted."""
    # OFF
    r = requests.patch(
        f"{API}/customer-portal/preferences", headers=customer_headers,
        json={"channel_opt_in": {"email_marketing": False}}, timeout=15,
    )
    assert r.status_code == 200
    assert r.json()["channel_opt_in"]["email_marketing"] is False

    async def _find_suppression():
        db = _db()
        u = await db.users.find_one({"email": "customer@aquaterra.com"},
                                     {"_id": 0, "tenant_id": 1,
                                      "customer_id": 1, "id": 1})
        tid = u["tenant_id"]
        cid = u.get("customer_id") or u["id"]
        cust = await db.customers.find_one({"id": cid, "tenant_id": tid},
                                            {"_id": 0, "email": 1})
        s = await db.marketing_suppressions.find_one({
            "tenant_id": tid, "channel": "email",
            "address": (cust.get("email") or "").lower(),
            "category": "all", "deleted_at": None,
        }, {"_id": 0})
        return s, tid, cid
    row, tid, cid = _run(_find_suppression())
    assert row is not None, "suppression row missing after opt-out"
    assert row["reason"] == "user_unsubscribe"

    # ON — soft delete
    r2 = requests.patch(
        f"{API}/customer-portal/preferences", headers=customer_headers,
        json={"channel_opt_in": {"email_marketing": True}}, timeout=15,
    )
    assert r2.status_code == 200
    async def _still_active():
        return await _db().marketing_suppressions.find_one({
            "tenant_id": tid, "customer_id": cid, "channel": "email",
            "category": "all", "deleted_at": None,
        })
    assert _run(_still_active()) is None


# ═══════════════════════════════════════════════════════════════════════
# Magic-link (public) unsubscribe
# ═══════════════════════════════════════════════════════════════════════
def _make_token(customer_id, tenant_id, expire_days=90, sub="unsub",
                secret_override=None):
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    secret = secret_override or os.environ["JWT_SECRET"]
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": sub, "cid": customer_id, "tid": tenant_id,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(days=expire_days),
    }, secret, algorithm="HS256")


def test_unsub_token_verify_and_apply():
    async def _pick():
        db = _db()
        u = await db.users.find_one({"email": "customer@aquaterra.com"},
                                     {"_id": 0, "tenant_id": 1,
                                      "customer_id": 1, "id": 1})
        return u["tenant_id"], u.get("customer_id") or u["id"]
    tid, cid = _run(_pick())
    tok = _make_token(cid, tid)
    # Verify — public, no auth.
    r = requests.get(f"{API}/portal/preferences/token/verify?token={tok}",
                      timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["customer_id"] == cid
    assert body["tenant_id"] == tid

    # Apply — flip SMS marketing off via token.
    r2 = requests.post(f"{API}/portal/preferences/via-token",
                        json={"token": tok,
                              "channel_opt_in": {"sms_marketing": False}},
                        timeout=15)
    assert r2.status_code == 200
    assert r2.json()["channel_opt_in"]["sms_marketing"] is False

    # Transactional flip via token still blocked.
    r3 = requests.post(f"{API}/portal/preferences/via-token",
                        json={"token": tok,
                              "channel_opt_in": {"email_transactional": False}},
                        timeout=15)
    assert r3.status_code == 422

    # Restore ON so downstream tests aren't disrupted.
    requests.post(f"{API}/portal/preferences/via-token",
                   json={"token": tok,
                         "channel_opt_in": {"sms_marketing": True}},
                   timeout=15)


def test_unsub_token_expired_and_tampered():
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    expired = jwt.encode({
        "sub": "unsub", "cid": "x", "tid": "y",
        "iat": int((datetime.now(timezone.utc) - timedelta(days=100)).timestamp()),
        "exp": datetime.now(timezone.utc) - timedelta(days=1),
    }, os.environ["JWT_SECRET"], algorithm="HS256")
    assert requests.get(
        f"{API}/portal/preferences/token/verify?token={expired}",
        timeout=15,
    ).status_code == 401
    tampered = jwt.encode({
        "sub": "unsub", "cid": "x", "tid": "y",
        "exp": datetime.now(timezone.utc) + timedelta(days=1),
    }, "not-the-secret" + "x" * 40, algorithm="HS256")
    assert requests.get(
        f"{API}/portal/preferences/token/verify?token={tampered}",
        timeout=15,
    ).status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# Suppression list CRUD + RBAC
# ═══════════════════════════════════════════════════════════════════════
def test_suppression_crud(admin_headers, tech_headers, customer_headers):
    # Add
    r = requests.post(
        f"{API}/marketing/suppressions", headers=admin_headers,
        json={"channel": "email", "address": "OPT@out.example",
              "reason": "manual_admin"},
        timeout=15,
    )
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["address"] == "opt@out.example"     # lowercased

    # List includes it
    lst = requests.get(f"{API}/marketing/suppressions",
                        headers=admin_headers, timeout=15).json()
    assert any(s["id"] == row["id"] for s in lst["suppressions"])

    # Non-admin blocked
    for h in (tech_headers, customer_headers):
        assert requests.get(f"{API}/marketing/suppressions",
                             headers=h, timeout=15).status_code in (401, 403)
        assert requests.post(f"{API}/marketing/suppressions",
                              headers=h,
                              json={"channel": "email", "address": "x@x.co"},
                              timeout=15).status_code in (401, 403)

    # Delete → 204, subsequent delete → 404
    assert requests.delete(
        f"{API}/marketing/suppressions/{row['id']}",
        headers=admin_headers, timeout=15,
    ).status_code == 204
    assert requests.delete(
        f"{API}/marketing/suppressions/{row['id']}",
        headers=admin_headers, timeout=15,
    ).status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# Enforcement — M6 review request tick honours suppression
# ═══════════════════════════════════════════════════════════════════════
def test_m6_tick_skips_suppressed_recipients(admin_headers):
    async def _go():
        from routers.marketing_review_requests import (
            _config_for, _enqueue_one, m6_tick_all_tenants,
        )
        db = _db()
        tid = await _tenant_of_admin()
        cfg = await _config_for(tid)
        # Ensure config enabled + immediate.
        assert cfg["enabled"] is True
        cust_id = f"slice-f-{uuid.uuid4().hex[:6]}"
        cust_email = f"{cust_id}@ex.com"
        await db.customers.insert_one({
            "id": cust_id, "tenant_id": tid, "name": "Slice F",
            "email": cust_email, "phone": "+15550100",
        })
        # Suppress this customer's email for the "review_requests" category.
        sup_id = f"slice-f-sup-{uuid.uuid4().hex[:6]}"
        await db.marketing_suppressions.insert_one({
            "id": sup_id, "tenant_id": tid, "channel": "email",
            "address": cust_email.lower(), "reason": "user_unsubscribe",
            "category": "review_requests", "customer_id": cust_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": "test", "deleted_at": None,
        })
        # Enqueue directly (with delay_hours=0 the tick fires it).
        cfg["delay_hours"] = 0
        row = await _enqueue_one(tid, cust_id, None, cfg, source="manual")
        assert row is not None
        try:
            await m6_tick_all_tenants()
            # Row must be flipped to failed + halt_reason=suppressed.
            r = await db.marketing_review_requests.find_one(
                {"id": row["id"]}, {"_id": 0},
            )
            assert r["status"] == "failed"
            assert r["halt_reason"] == "suppressed"
            # And ZERO delivery recorded.
            n = await db.marketing_deliveries.count_documents(
                {"review_request_id": row["id"]},
            )
            assert n == 0
        finally:
            await db.marketing_review_requests.delete_one({"id": row["id"]})
            await db.marketing_suppressions.delete_one({"id": sup_id})
            await db.customers.delete_one({"id": cust_id})

    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Enforcement — M5 sequence tick halts on suppression
# ═══════════════════════════════════════════════════════════════════════
def test_m5_tick_halts_suppressed_enrolments(admin_headers):
    async def _go():
        from routers.marketing_sequences import process_due_enrolments
        db = _db()
        tid = await _tenant_of_admin()
        # Grab an email template.
        tpl = await db.marketing_templates.find_one(
            {"tenant_id": tid, "channel": "email", "active": True},
            {"_id": 0, "id": 1},
        )
        seq_id = f"slice-f-seq-{uuid.uuid4().hex[:6]}"
        cust_id = f"slice-f-c-{uuid.uuid4().hex[:6]}"
        cust_email = f"{cust_id}@ex.com"
        sup_id = f"slice-f-sup-{uuid.uuid4().hex[:6]}"
        enr_id = f"slice-f-e-{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc)
        await db.customers.insert_one({
            "id": cust_id, "tenant_id": tid, "name": "Slice F seq",
            "email": cust_email,
        })
        await db.marketing_sequences.insert_one({
            "id": seq_id, "tenant_id": tid, "name": "Slice F seq",
            "description": "", "trigger_type": "manual", "trigger_config": {},
            "steps": [{"order": 0, "channel": "email",
                        "template_id": tpl["id"],
                        "delay_from": "trigger", "delay_hours": 0,
                        "condition": None}],
            "active": True, "stop_on_reply": True, "stop_on_unsubscribe": True,
            "system": False, "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        })
        await db.marketing_suppressions.insert_one({
            "id": sup_id, "tenant_id": tid, "channel": "email",
            "address": cust_email.lower(), "reason": "user_unsubscribe",
            "category": "all", "customer_id": cust_id,
            "created_at": now.isoformat(), "created_by": "test",
            "deleted_at": None,
        })
        await db.marketing_drip_enrolments.insert_one({
            "id": enr_id, "tenant_id": tid, "sequence_id": seq_id,
            "customer_id": cust_id, "trigger_source": "manual",
            "enrolled_at": now.isoformat(), "current_step": 0,
            "next_send_at": (now - timedelta(minutes=1)).isoformat(),
            "status": "active", "halt_reason": None, "history": [],
        })
        try:
            await process_due_enrolments(tid)
            e = await db.marketing_drip_enrolments.find_one(
                {"id": enr_id}, {"_id": 0},
            )
            assert e["status"] == "halted"
            assert e["halt_reason"] == "suppressed"
            # No delivery recorded either.
            n = await db.marketing_deliveries.count_documents(
                {"enrolment_id": enr_id},
            )
            assert n == 0
        finally:
            await db.marketing_sequences.delete_one({"id": seq_id})
            await db.marketing_drip_enrolments.delete_many({"id": enr_id})
            await db.marketing_deliveries.delete_many({"enrolment_id": enr_id})
            await db.marketing_suppressions.delete_one({"id": sup_id})
            await db.customers.delete_one({"id": cust_id})

    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Cross-tenant isolation on suppression list
# ═══════════════════════════════════════════════════════════════════════
def test_cross_tenant_isolation(admin_headers):
    async def _seed_foreign():
        db = _db()
        mine = await _tenant_of_admin()
        others = await db.tenants.find({"id": {"$ne": mine}},
                                        {"_id": 0, "id": 1}).to_list(1)
        assert others
        sid = f"slice-f-cross-{uuid.uuid4().hex[:6]}"
        await db.marketing_suppressions.insert_one({
            "id": sid, "tenant_id": others[0]["id"],
            "channel": "email", "address": "foreign@ex.com",
            "reason": "manual_admin", "category": None,
            "customer_id": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": "test", "deleted_at": None,
        })
        return sid
    sid = _run(_seed_foreign())
    try:
        rows = requests.get(
            f"{API}/marketing/suppressions?limit=500",
            headers=admin_headers, timeout=15,
        ).json()["suppressions"]
        assert sid not in {s["id"] for s in rows}
        assert requests.delete(
            f"{API}/marketing/suppressions/{sid}",
            headers=admin_headers, timeout=15,
        ).status_code == 404
    finally:
        async def _clean():
            await _db().marketing_suppressions.delete_one({"id": sid})
        _run(_clean())
