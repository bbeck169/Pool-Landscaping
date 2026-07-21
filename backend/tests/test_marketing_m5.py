"""Feb-2026 · Marketing Slice M5a — Sequence CRUD, enrolment,
tick handler, cascade-delete + tenant isolation."""
from __future__ import annotations

import asyncio, os, uuid
from datetime import datetime, timedelta, timezone

import pytest, requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
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


def _run(coro):
    """One shared event loop for the whole module — motor caches
    ``get_io_loop()`` on the module-level ``config.db`` client, so we
    must NOT create a fresh loop per test call."""
    return _LOOP.run_until_complete(coro)


def _rebind_config_db_to_our_loop():
    """When this test module co-runs with M3/M4, ``config.db`` has
    already been bound to a stale event loop.  Swap in a fresh motor
    client tied to our persistent ``_LOOP`` and patch every router
    that imported ``db`` at load-time so the tick handler works."""
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
    return fresh_db


# Rebind LAZILY: pytest imports all test modules at collection time, so
# doing this at import would clobber the ``config.db`` client that
# M3/M4 tests need to keep on their own loops.  Fire once via an
# autouse module fixture instead — that runs after M3/M4 finish.
@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    _rebind_config_db_to_our_loop()
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"],
                               io_loop=_LOOP)[os.environ["DB_NAME"]]


def _pick_templates(admin_headers):
    """Pull one email + one sms template id for the current tenant so
    the tests don't hard-code seed IDs."""
    r = requests.get(f"{API}/marketing/templates?active=true",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    rows = r.json().get("templates", [])
    email = next(t for t in rows if t["channel"] == "email")
    sms   = next(t for t in rows if t["channel"] == "sms")
    return email, sms


# ═══════════════════════════════════════════════════════════════════════
# Trigger registry + RBAC
# ═══════════════════════════════════════════════════════════════════════
def test_registry_admin_only(admin_headers, tech_headers, customer_headers):
    r = requests.get(f"{API}/marketing/sequences/triggers/registry",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    types = {t["type"] for t in r.json()["triggers"]}
    for t in ("service_completed", "invoice_sent", "invoice_past_due_N_days",
               "customer_created", "birthday", "review_left",
               "manual", "segment_join"):
        assert t in types, f"trigger registry missing {t}"

    for h in (tech_headers, customer_headers):
        assert requests.get(f"{API}/marketing/sequences/triggers/registry",
                             headers=h, timeout=15).status_code in (401, 403)


def test_list_seeded_sequences(admin_headers):
    r = requests.get(f"{API}/marketing/sequences", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["sequences"]}
    assert "Post-service follow-up" in names
    assert "Past-due reminder" in names


def test_crud_rbac_non_admin_blocked(tech_headers, customer_headers):
    for h in (tech_headers, customer_headers):
        assert requests.get(f"{API}/marketing/sequences", headers=h,
                             timeout=15).status_code in (401, 403)
        assert requests.post(f"{API}/marketing/sequences", headers=h,
                              json={"name": "x", "trigger_type": "manual",
                                    "steps": []},
                              timeout=15).status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════
# CRUD flow
# ═══════════════════════════════════════════════════════════════════════
def test_crud_flow(admin_headers):
    email_tpl, sms_tpl = _pick_templates(admin_headers)
    body = {
        "name": "M5 crud", "trigger_type": "manual",
        "steps": [
            {"order": 0, "channel": "email", "template_id": email_tpl["id"],
             "delay_from": "trigger", "delay_hours": 1, "condition": None},
            {"order": 1, "channel": "sms", "template_id": sms_tpl["id"],
             "delay_from": "previous_step", "delay_hours": 24,
             "condition": {"if_engaged": True}},
        ],
    }
    r = requests.post(f"{API}/marketing/sequences", headers=admin_headers,
                       json=body, timeout=15)
    assert r.status_code == 201, r.text
    seq = r.json()
    sid = seq["id"]
    assert seq["active"] is False
    assert seq["stop_on_reply"] is True
    assert seq["stop_on_unsubscribe"] is True
    # Condition field roundtrips
    assert seq["steps"][1]["condition"] == {"if_engaged": True}

    # GET
    got = requests.get(f"{API}/marketing/sequences/{sid}",
                        headers=admin_headers, timeout=15)
    assert got.status_code == 200

    # PATCH — flip active + rename
    r = requests.patch(f"{API}/marketing/sequences/{sid}", headers=admin_headers,
                        json={"name": "M5 crud renamed", "active": True}, timeout=15)
    assert r.status_code == 200 and r.json()["active"] is True

    # DELETE (soft) → active=false
    assert requests.delete(f"{API}/marketing/sequences/{sid}",
                            headers=admin_headers, timeout=15).status_code == 204
    got = requests.get(f"{API}/marketing/sequences/{sid}",
                        headers=admin_headers, timeout=15).json()
    assert got["active"] is False


def test_bad_trigger_and_channel_mismatch_rejected(admin_headers):
    email_tpl, sms_tpl = _pick_templates(admin_headers)

    # Unknown trigger
    r = requests.post(f"{API}/marketing/sequences", headers=admin_headers,
                       json={"name": "bad trig", "trigger_type": "nope", "steps": []},
                       timeout=15)
    assert r.status_code == 422

    # Channel mismatch (step says email but template is sms)
    r = requests.post(f"{API}/marketing/sequences", headers=admin_headers,
                       json={"name": "bad ch", "trigger_type": "manual",
                             "steps": [{"order": 0, "channel": "email",
                                         "template_id": sms_tpl["id"],
                                         "delay_from": "trigger",
                                         "delay_hours": 0}]},
                       timeout=15)
    assert r.status_code == 422, r.text

    # Unknown template
    r = requests.post(f"{API}/marketing/sequences", headers=admin_headers,
                       json={"name": "bad tpl", "trigger_type": "manual",
                             "steps": [{"order": 0, "channel": "email",
                                         "template_id": "does-not-exist",
                                         "delay_from": "trigger",
                                         "delay_hours": 0}]},
                       timeout=15)
    assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
# Manual enrolment + duplicate guard
# ═══════════════════════════════════════════════════════════════════════
def test_manual_enrol_and_dedupe(admin_headers):
    email_tpl, _ = _pick_templates(admin_headers)
    # Create a fresh sequence with 1 immediate step
    r = requests.post(f"{API}/marketing/sequences", headers=admin_headers,
                       json={"name": f"M5 enrol {uuid.uuid4().hex[:6]}",
                             "trigger_type": "manual", "active": True,
                             "steps": [{"order": 0, "channel": "email",
                                         "template_id": email_tpl["id"],
                                         "delay_from": "trigger",
                                         "delay_hours": 0}]},
                       timeout=15)
    assert r.status_code == 201
    sid = r.json()["id"]

    # Enrol a real customer
    async def _pick_customer():
        db = _db()
        u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "tenant_id": 1})
        c = await db.customers.find_one(
            {"tenant_id": u["tenant_id"]}, {"_id": 0, "id": 1},
        )
        return c["id"] if c else None
    cid = _run(_pick_customer())
    assert cid, "expected at least one customer in the demo tenant"

    r = requests.post(f"{API}/marketing/sequences/{sid}/enrol",
                       headers=admin_headers,
                       json={"customer_ids": [cid]}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enrolled_count"] == 1
    assert body["skipped_count"] == 0

    # Second enrol with the same customer → dedupe skip
    r2 = requests.post(f"{API}/marketing/sequences/{sid}/enrol",
                        headers=admin_headers,
                        json={"customer_ids": [cid]}, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["enrolled_count"] == 0
    assert r2.json()["skipped_count"] == 1

    # List enrolments
    r3 = requests.get(f"{API}/marketing/sequences/{sid}/enrolments",
                       headers=admin_headers, timeout=15)
    assert r3.status_code == 200
    assert r3.json()["total"] >= 1

    # Halt endpoint
    eid = r3.json()["enrolments"][0]["id"]
    r4 = requests.post(f"{API}/marketing/sequences/{sid}/halt/{eid}",
                        headers=admin_headers, timeout=15)
    assert r4.status_code == 200

    # cleanup
    requests.delete(f"{API}/marketing/sequences/{sid}",
                     headers=admin_headers, timeout=15)


def test_enrol_via_segment(admin_headers):
    """Feeding segment_id resolves matched customer_ids."""
    email_tpl, _ = _pick_templates(admin_headers)
    # Create sequence
    r = requests.post(f"{API}/marketing/sequences", headers=admin_headers,
                       json={"name": f"M5 seg-enrol {uuid.uuid4().hex[:6]}",
                             "trigger_type": "segment_join",
                             "trigger_config": {"segment_id": "placeholder"},
                             "active": True,
                             "steps": [{"order": 0, "channel": "email",
                                         "template_id": email_tpl["id"],
                                         "delay_from": "trigger",
                                         "delay_hours": 0}]},
                       timeout=15)
    sid = r.json()["id"]

    # Reuse a seeded segment (VIP customers)
    seg = requests.get(f"{API}/marketing/audience-segments",
                        headers=admin_headers, timeout=15).json()["segments"]
    vip = next((s for s in seg if s["name"] == "VIP customers"), None)
    assert vip, "expected seeded 'VIP customers' segment"

    r = requests.post(f"{API}/marketing/sequences/{sid}/enrol",
                       headers=admin_headers,
                       json={"segment_id": vip["id"]}, timeout=15)
    assert r.status_code == 200, r.text
    # Enrolled_count could legitimately be 0 in a tenant with no VIPs — we
    # only assert the call succeeded and returned the shape we expect.
    assert "enrolled_count" in r.json() and "skipped_count" in r.json()

    requests.delete(f"{API}/marketing/sequences/{sid}",
                     headers=admin_headers, timeout=15)


# ═══════════════════════════════════════════════════════════════════════
# Cascade delete: halt active enrolments
# ═══════════════════════════════════════════════════════════════════════
def test_delete_cascades_active_enrolments(admin_headers):
    email_tpl, _ = _pick_templates(admin_headers)
    r = requests.post(f"{API}/marketing/sequences", headers=admin_headers,
                       json={"name": f"M5 casc {uuid.uuid4().hex[:6]}",
                             "trigger_type": "manual", "active": True,
                             "steps": [{"order": 0, "channel": "email",
                                         "template_id": email_tpl["id"],
                                         "delay_from": "trigger",
                                         "delay_hours": 0}]},
                       timeout=15)
    sid = r.json()["id"]

    async def _pick_customer():
        db = _db()
        u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "tenant_id": 1})
        c = await db.customers.find_one(
            {"tenant_id": u["tenant_id"]}, {"_id": 0, "id": 1},
        )
        return c["id"]
    cid = _run(_pick_customer())
    requests.post(f"{API}/marketing/sequences/{sid}/enrol",
                   headers=admin_headers,
                   json={"customer_ids": [cid]}, timeout=15)

    # Confirm active enrolment exists
    rows = requests.get(f"{API}/marketing/sequences/{sid}/enrolments",
                         headers=admin_headers, timeout=15).json()
    active_before = [e for e in rows["enrolments"] if e["status"] == "active"]
    assert active_before, "expected at least one active enrolment"

    # Delete → cascade halt
    assert requests.delete(f"{API}/marketing/sequences/{sid}",
                            headers=admin_headers, timeout=15).status_code == 204
    rows2 = requests.get(f"{API}/marketing/sequences/{sid}/enrolments",
                          headers=admin_headers, timeout=15).json()
    for e in rows2["enrolments"]:
        assert e["status"] != "active", \
            f"enrolment {e['id']} still active after sequence delete"
        if e["id"] in {a["id"] for a in active_before}:
            assert e["status"] == "halted"
            assert e["halt_reason"] == "sequence_deleted"


# ═══════════════════════════════════════════════════════════════════════
# Tick handler — records deliveries + advances / completes
# ═══════════════════════════════════════════════════════════════════════
def test_tick_advances_and_records_mock_delivery(admin_headers):
    email_tpl, sms_tpl = _pick_templates(admin_headers)

    async def _go():
        from routers.marketing_sequences import process_due_enrolments
        db = _db()
        u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "tenant_id": 1})
        tenant_id = u["tenant_id"]
        cust = await db.customers.find_one(
            {"tenant_id": tenant_id}, {"_id": 0, "id": 1},
        )
        cid = cust["id"]

        now = datetime.now(timezone.utc)
        # Insert sequence + enrolment directly so we can force
        # ``next_send_at`` into the past without waiting.
        seq_id = f"m5-tick-{uuid.uuid4().hex[:6]}"
        await db.marketing_sequences.insert_one({
            "id": seq_id, "tenant_id": tenant_id,
            "name": "M5 tick", "description": "",
            "trigger_type": "manual", "trigger_config": {},
            "steps": [
                {"order": 0, "channel": "email",
                 "template_id": email_tpl["id"],
                 "delay_from": "trigger", "delay_hours": 0, "condition": None},
                {"order": 1, "channel": "sms",
                 "template_id": sms_tpl["id"],
                 "delay_from": "previous_step", "delay_hours": 0, "condition": None},
            ],
            "active": True, "stop_on_reply": True, "stop_on_unsubscribe": True,
            "system": False,
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
        })
        enr_id = f"m5-enr-{uuid.uuid4().hex[:6]}"
        await db.marketing_drip_enrolments.insert_one({
            "id": enr_id, "tenant_id": tenant_id,
            "sequence_id": seq_id, "customer_id": cid,
            "trigger_source": "manual",
            "enrolled_at": now.isoformat(),
            "current_step": 0,
            "next_send_at": (now - timedelta(minutes=1)).isoformat(),
            "status": "active", "halt_reason": None, "history": [],
        })

        try:
            # First tick → send email, cursor moves to step 1
            r1 = await process_due_enrolments(tenant_id)
            assert r1["sent"] == 1
            e = await db.marketing_drip_enrolments.find_one(
                {"id": enr_id}, {"_id": 0},
            )
            assert e["current_step"] == 1
            assert e["status"] == "active"
            assert len(e["history"]) == 1
            assert e["history"][0]["channel"] == "email"

            # A mock delivery row exists for step 0
            deliveries = await db.marketing_deliveries.find(
                {"enrolment_id": enr_id}, {"_id": 0},
            ).to_list(10)
            assert len(deliveries) == 1
            assert deliveries[0]["mock"] is True
            assert deliveries[0]["channel"] == "email"
            assert deliveries[0]["step_index"] == 0
            assert deliveries[0]["provider_response_stub"]["ok"] is True

            # Force step 1 due, run again
            await db.marketing_drip_enrolments.update_one(
                {"id": enr_id},
                {"$set": {"next_send_at": (now - timedelta(minutes=1)).isoformat()}},
            )
            r2 = await process_due_enrolments(tenant_id)
            assert r2["sent"] == 1
            e = await db.marketing_drip_enrolments.find_one(
                {"id": enr_id}, {"_id": 0},
            )
            assert e["status"] == "completed"
            assert e["next_send_at"] is None
            assert e["current_step"] == 2
            assert len(e["history"]) == 2
            assert e["history"][1]["channel"] == "sms"

            # A 3rd tick is idempotent (nothing due)
            r3 = await process_due_enrolments(tenant_id)
            assert r3["sent"] == 0
        finally:
            await db.marketing_sequences.delete_one({"id": seq_id})
            await db.marketing_drip_enrolments.delete_many({"sequence_id": seq_id})
            await db.marketing_deliveries.delete_many({"sequence_id": seq_id})

    _run(_go())


def test_tick_skips_inactive_sequences(admin_headers):
    """A sequence toggled off must NOT keep sending on the next tick."""
    email_tpl, _ = _pick_templates(admin_headers)

    async def _go():
        from routers.marketing_sequences import process_due_enrolments
        db = _db()
        u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "tenant_id": 1})
        tenant_id = u["tenant_id"]
        cust = await db.customers.find_one(
            {"tenant_id": tenant_id}, {"_id": 0, "id": 1},
        )
        cid = cust["id"]
        now = datetime.now(timezone.utc)
        seq_id = f"m5-off-{uuid.uuid4().hex[:6]}"
        enr_id = f"m5-off-e-{uuid.uuid4().hex[:6]}"
        await db.marketing_sequences.insert_one({
            "id": seq_id, "tenant_id": tenant_id,
            "name": "M5 off", "trigger_type": "manual",
            "trigger_config": {},
            "steps": [{"order": 0, "channel": "email",
                        "template_id": email_tpl["id"],
                        "delay_from": "trigger",
                        "delay_hours": 0, "condition": None}],
            "active": False,   # ← intentionally inactive
            "stop_on_reply": True, "stop_on_unsubscribe": True,
            "system": False, "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        })
        await db.marketing_drip_enrolments.insert_one({
            "id": enr_id, "tenant_id": tenant_id,
            "sequence_id": seq_id, "customer_id": cid,
            "trigger_source": "manual", "enrolled_at": now.isoformat(),
            "current_step": 0,
            "next_send_at": (now - timedelta(minutes=1)).isoformat(),
            "status": "active", "halt_reason": None, "history": [],
        })
        try:
            r = await process_due_enrolments(tenant_id)
            # The tick pass counts due rows but must NOT record a
            # delivery when the parent sequence is inactive.
            deliveries = await db.marketing_deliveries.count_documents(
                {"enrolment_id": enr_id},
            )
            assert deliveries == 0
            e = await db.marketing_drip_enrolments.find_one({"id": enr_id})
            assert e["current_step"] == 0
        finally:
            await db.marketing_sequences.delete_one({"id": seq_id})
            await db.marketing_drip_enrolments.delete_many({"sequence_id": seq_id})
            await db.marketing_deliveries.delete_many({"sequence_id": seq_id})

    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Cross-tenant isolation
# ═══════════════════════════════════════════════════════════════════════
def test_cross_tenant_isolation(admin_headers):
    async def _seed_foreign():
        db = _db()
        u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "tenant_id": 1})
        others = await db.tenants.find(
            {"id": {"$ne": u["tenant_id"]}}, {"_id": 0, "id": 1},
        ).to_list(1)
        assert others
        sid = f"m5-cross-{uuid.uuid4().hex[:8]}"
        await db.marketing_sequences.insert_one({
            "id": sid, "tenant_id": others[0]["id"],
            "name": "foreign seq", "description": "",
            "trigger_type": "manual", "trigger_config": {},
            "steps": [], "active": True,
            "stop_on_reply": True, "stop_on_unsubscribe": True,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        })
        return sid
    sid = _run(_seed_foreign())
    try:
        assert requests.get(f"{API}/marketing/sequences/{sid}",
                             headers=admin_headers, timeout=15).status_code == 404
        assert requests.patch(f"{API}/marketing/sequences/{sid}",
                               headers=admin_headers, json={"name": "hijack"},
                               timeout=15).status_code == 404
        assert requests.delete(f"{API}/marketing/sequences/{sid}",
                                headers=admin_headers, timeout=15).status_code == 404
        assert requests.post(f"{API}/marketing/sequences/{sid}/enrol",
                              headers=admin_headers,
                              json={"customer_ids": ["nobody"]},
                              timeout=15).status_code == 404
    finally:
        async def _clean():
            await _db().marketing_sequences.delete_one({"id": sid})
        _run(_clean())
