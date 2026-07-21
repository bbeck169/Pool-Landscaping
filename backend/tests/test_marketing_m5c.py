"""Feb-2026 · Marketing Slice M5c — event hooks + daily sweep + tick.

Every test rebinds the module-level ``config.db`` client to a
persistent loop before running any async code (motor-loop-cache
workaround also used by ``test_marketing_m5.py``).
"""
from __future__ import annotations

import asyncio, os, uuid
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


def _pick_template_ids(admin_headers, channel="email"):
    r = requests.get(f"{API}/marketing/templates?active=true",
                      headers=admin_headers, timeout=15)
    for t in r.json().get("templates", []):
        if t["channel"] == channel:
            return t["id"]
    raise AssertionError("no template")


async def _tenant_id_of_admin():
    db = _db()
    u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                 {"_id": 0, "tenant_id": 1})
    return u["tenant_id"]


async def _foreign_tenant_id(mine):
    db = _db()
    r = await db.tenants.find({"id": {"$ne": mine}},
                                {"_id": 0, "id": 1}).to_list(1)
    return r[0]["id"] if r else None


async def _make_sequence(tenant_id, trigger_type, tpl_id, active=True,
                         trigger_config=None):
    db = _db()
    now = datetime.now(timezone.utc).isoformat()
    sid = f"m5c-{trigger_type}-{uuid.uuid4().hex[:6]}"
    await db.marketing_sequences.insert_one({
        "id": sid, "tenant_id": tenant_id,
        "name": f"M5c {trigger_type}", "description": "",
        "trigger_type": trigger_type,
        "trigger_config": trigger_config or {},
        "steps": [{"order": 0, "channel": "email", "template_id": tpl_id,
                    "delay_from": "trigger", "delay_hours": 0, "condition": None}],
        "active": active, "stop_on_reply": True, "stop_on_unsubscribe": True,
        "system": False, "created_at": now, "updated_at": now,
    })
    return sid


async def _cleanup_sequence(sid):
    db = _db()
    await db.marketing_sequences.delete_one({"id": sid})
    await db.marketing_drip_enrolments.delete_many({"sequence_id": sid})
    await db.marketing_deliveries.delete_many({"sequence_id": sid})


# ═══════════════════════════════════════════════════════════════════════
# Registry — all 8 triggers wired
# ═══════════════════════════════════════════════════════════════════════
def test_registry_no_wiring_gap(admin_headers):
    """Post-M5c every trigger is either event-fired or daily-eval'd —
    no entry may carry a ``not_yet_wired: true`` flag."""
    r = requests.get(f"{API}/marketing/sequences/triggers/registry",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    triggers = r.json()["triggers"]
    assert len(triggers) == 8
    for t in triggers:
        assert t.get("not_yet_wired") is not True, \
            f"trigger {t['type']} still flagged not_yet_wired"


# ═══════════════════════════════════════════════════════════════════════
# Immediate event bus — on_event()
# ═══════════════════════════════════════════════════════════════════════
def test_on_event_fanout_only_hits_active_matching_same_tenant(admin_headers):
    """One active + one inactive + one wrong-tenant sequence; only the
    active same-tenant sequence gets an enrolment."""
    tpl = _pick_template_ids(admin_headers, "email")

    async def _go():
        from services.marketing.drip_events import on_event
        mine = await _tenant_id_of_admin()
        other = await _foreign_tenant_id(mine)
        assert other, "need a foreign tenant seeded"

        active = await _make_sequence(mine, "service_completed", tpl, active=True)
        inactive = await _make_sequence(mine, "service_completed", tpl, active=False)
        foreign = await _make_sequence(other, "service_completed", tpl, active=True)
        wrong_trig = await _make_sequence(mine, "customer_created", tpl, active=True)

        db = _db()
        cid = f"m5c-cust-{uuid.uuid4().hex[:6]}"
        await db.customers.insert_one({
            "id": cid, "tenant_id": mine, "name": "M5c CustFan",
        })
        try:
            r = await on_event("service_completed", mine, cid)
            assert r["enrolled"] == 1, r
            assert r["sequences"] == 1     # only the active same-tenant match
            # Second fire → dedupe skip
            r2 = await on_event("service_completed", mine, cid)
            assert r2["enrolled"] == 0
            assert r2["skipped"] == 1

            # Foreign tenant + inactive + wrong-trigger sequences must have 0 enrolments.
            for sid in (inactive, foreign, wrong_trig):
                cnt = await db.marketing_drip_enrolments.count_documents(
                    {"sequence_id": sid},
                )
                assert cnt == 0, f"sequence {sid} should have 0 enrolments"
        finally:
            for sid in (active, inactive, foreign, wrong_trig):
                await _cleanup_sequence(sid)
            await db.customers.delete_one({"id": cid})

    _run(_go())


def test_on_event_covers_all_four_immediate_triggers(admin_headers):
    """Sanity check for the other three immediate triggers."""
    tpl = _pick_template_ids(admin_headers, "email")

    async def _go():
        from services.marketing.drip_events import on_event
        mine = await _tenant_id_of_admin()
        db = _db()
        cid = f"m5c-immed-{uuid.uuid4().hex[:6]}"
        await db.customers.insert_one({"id": cid, "tenant_id": mine, "name": "M5c Immed"})

        seqs = []
        for trig in ("invoice_sent", "customer_created", "review_left"):
            seqs.append(await _make_sequence(mine, trig, tpl, active=True))
        try:
            for trig in ("invoice_sent", "customer_created", "review_left"):
                r = await on_event(trig, mine, cid)
                assert r["enrolled"] == 1, (trig, r)
        finally:
            for sid in seqs:
                await _cleanup_sequence(sid)
            await db.customers.delete_one({"id": cid})

    _run(_go())


def test_on_event_ignores_unknown_and_daily_triggers(admin_headers):
    """``on_event`` MUST refuse to enrol on triggers that only the
    daily sweep should handle, otherwise a domain hook could
    accidentally fire a birthday drip mid-day."""
    tpl = _pick_template_ids(admin_headers, "email")

    async def _go():
        from services.marketing.drip_events import on_event
        mine = await _tenant_id_of_admin()
        db = _db()
        cid = f"m5c-noimmed-{uuid.uuid4().hex[:6]}"
        await db.customers.insert_one({"id": cid, "tenant_id": mine, "name": "M5c NoImmed"})
        sids = []
        for trig in ("birthday", "segment_join",
                     "invoice_past_due_N_days", "manual"):
            sids.append(await _make_sequence(mine, trig, tpl, active=True))
        try:
            for trig in ("birthday", "segment_join",
                         "invoice_past_due_N_days", "manual", "bogus"):
                r = await on_event(trig, mine, cid)
                assert r["enrolled"] == 0, (trig, r)
        finally:
            for sid in sids:
                await _cleanup_sequence(sid)
            await db.customers.delete_one({"id": cid})

    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Daily sweep — past-due, birthday, segment-join
# ═══════════════════════════════════════════════════════════════════════
def test_daily_sweep_past_due(admin_headers):
    tpl = _pick_template_ids(admin_headers, "email")

    async def _go():
        from services.marketing.drip_events import daily_marketing_trigger_sweep
        mine = await _tenant_id_of_admin()
        db = _db()
        # 3-days-past-due sequence.
        sid = await _make_sequence(
            mine, "invoice_past_due_N_days", tpl, active=True,
            trigger_config={"days_past_due": 3},
        )
        # Customer + invoice with due_date exactly 3 days ago.
        cid = f"m5c-pd-{uuid.uuid4().hex[:6]}"
        due = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
        await db.customers.insert_one(
            {"id": cid, "tenant_id": mine, "name": "M5c PastDue"}
        )
        inv_id = f"m5c-inv-{cid[:6]}"
        await db.quotes.insert_one({
            "id": inv_id, "tenant_id": mine, "customer_id": cid,
            "doc_type": "invoice", "total": 500, "amount_paid": 0,
            "payment_status": "unpaid", "due_date": due,
        })
        try:
            r = await daily_marketing_trigger_sweep()
            assert r["past_due_enrolled"] >= 1

            got = await db.marketing_drip_enrolments.find_one(
                {"sequence_id": sid, "customer_id": cid}, {"_id": 0},
            )
            assert got is not None
            assert got["trigger_source"] == "invoice_past_due_N_days"

            # Idempotent: same-day rerun does not create a second enrolment.
            before = await db.marketing_drip_enrolments.count_documents(
                {"sequence_id": sid, "customer_id": cid},
            )
            await daily_marketing_trigger_sweep()
            after = await db.marketing_drip_enrolments.count_documents(
                {"sequence_id": sid, "customer_id": cid},
            )
            assert before == after == 1
        finally:
            await _cleanup_sequence(sid)
            await db.customers.delete_one({"id": cid})
            await db.quotes.delete_one({"id": inv_id})

    _run(_go())


def test_daily_sweep_birthday(admin_headers):
    tpl = _pick_template_ids(admin_headers, "email")

    async def _go():
        from services.marketing.drip_events import daily_marketing_trigger_sweep
        mine = await _tenant_id_of_admin()
        db = _db()
        sid = await _make_sequence(mine, "birthday", tpl, active=True)
        now = datetime.now(timezone.utc)
        today_bday = f"1985-{now.strftime('%m-%d')}"
        cid = f"m5c-bday-{uuid.uuid4().hex[:6]}"
        cid_other = f"m5c-bday2-{uuid.uuid4().hex[:6]}"
        # Wrong-day birthday (guaranteed different mm-dd).
        other_dt = now - timedelta(days=45)
        await db.customers.insert_many([
            {"id": cid, "tenant_id": mine, "name": "M5c Bday", "birthday": today_bday},
            {"id": cid_other, "tenant_id": mine, "name": "M5c NoBday",
             "birthday": f"1985-{other_dt.strftime('%m-%d')}"},
        ])
        try:
            await daily_marketing_trigger_sweep()
            match = await db.marketing_drip_enrolments.find_one(
                {"sequence_id": sid, "customer_id": cid},
            )
            miss = await db.marketing_drip_enrolments.find_one(
                {"sequence_id": sid, "customer_id": cid_other},
            )
            assert match is not None
            assert miss is None
        finally:
            await _cleanup_sequence(sid)
            await db.customers.delete_many({"id": {"$in": [cid, cid_other]}})

    _run(_go())


def test_daily_sweep_segment_join_delta_only(admin_headers):
    """The FIRST sweep enrols every current member.  The SECOND sweep,
    after adding one net-new member, enrols ONLY that new member."""
    tpl = _pick_template_ids(admin_headers, "email")

    async def _go():
        from services.marketing.drip_events import daily_marketing_trigger_sweep
        mine = await _tenant_id_of_admin()
        db = _db()

        # A segment matching a very unique tag so we control membership.
        tag = f"m5c-tag-{uuid.uuid4().hex[:6]}"
        seg_id = f"m5c-seg-{uuid.uuid4().hex[:6]}"
        await db.marketing_audience_segments.insert_one({
            "id": seg_id, "tenant_id": mine,
            "name": "m5c seg", "description": "",
            "conditions": [{"field": "tags", "op": "contains_any", "value": [tag]}],
            "active": True, "system": False,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        })
        sid = await _make_sequence(
            mine, "segment_join", tpl, active=True,
            trigger_config={"segment_id": seg_id},
        )
        c1 = f"m5c-sj1-{uuid.uuid4().hex[:6]}"
        c2 = f"m5c-sj2-{uuid.uuid4().hex[:6]}"
        await db.customers.insert_one(
            {"id": c1, "tenant_id": mine, "name": "M5c seg one", "tags": [tag]}
        )
        try:
            # First sweep — one member matches.
            await daily_marketing_trigger_sweep()
            e1 = await db.marketing_drip_enrolments.find_one(
                {"sequence_id": sid, "customer_id": c1},
            )
            assert e1 is not None

            # Add second customer to the segment, sweep again.
            await db.customers.insert_one(
                {"id": c2, "tenant_id": mine, "name": "M5c seg two", "tags": [tag]}
            )
            await daily_marketing_trigger_sweep()
            e2 = await db.marketing_drip_enrolments.find_one(
                {"sequence_id": sid, "customer_id": c2},
            )
            assert e2 is not None
            # c1 still has EXACTLY one enrolment — no re-fire.
            n1 = await db.marketing_drip_enrolments.count_documents(
                {"sequence_id": sid, "customer_id": c1},
            )
            assert n1 == 1
        finally:
            await _cleanup_sequence(sid)
            await db.marketing_audience_segments.delete_one({"id": seg_id})
            await db.customers.delete_many({"id": {"$in": [c1, c2]}})

    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Tick + deactivation regression
# ═══════════════════════════════════════════════════════════════════════
def test_tick_stops_when_sequence_deactivated(admin_headers):
    tpl_e = _pick_template_ids(admin_headers, "email")
    tpl_s = _pick_template_ids(admin_headers, "sms")

    async def _go():
        from services.marketing.drip_events import sequences_tick_all_tenants
        mine = await _tenant_id_of_admin()
        db = _db()
        now = datetime.now(timezone.utc)
        sid = f"m5c-tickstop-{uuid.uuid4().hex[:6]}"
        await db.marketing_sequences.insert_one({
            "id": sid, "tenant_id": mine, "name": "M5c stop", "description": "",
            "trigger_type": "manual", "trigger_config": {},
            "steps": [
                {"order": 0, "channel": "email", "template_id": tpl_e,
                 "delay_from": "trigger", "delay_hours": 0, "condition": None},
                {"order": 1, "channel": "sms", "template_id": tpl_s,
                 "delay_from": "previous_step", "delay_hours": 0, "condition": None},
            ],
            "active": True, "stop_on_reply": True, "stop_on_unsubscribe": True,
            "system": False, "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        })
        cid = f"m5c-tickcust-{uuid.uuid4().hex[:6]}"
        await db.customers.insert_one({"id": cid, "tenant_id": mine, "name": "M5c Tick"})
        enr_id = f"m5c-e-{uuid.uuid4().hex[:6]}"
        await db.marketing_drip_enrolments.insert_one({
            "id": enr_id, "tenant_id": mine, "sequence_id": sid,
            "customer_id": cid, "trigger_source": "manual",
            "enrolled_at": now.isoformat(),
            "current_step": 0,
            "next_send_at": (now - timedelta(minutes=1)).isoformat(),
            "status": "active", "halt_reason": None, "history": [],
        })
        try:
            # First tick fires step 0 → mock delivery recorded.
            r1 = await sequences_tick_all_tenants()
            deliveries = await db.marketing_deliveries.count_documents(
                {"enrolment_id": enr_id},
            )
            assert deliveries == 1

            # Deactivate the sequence + force step 1 due.
            await db.marketing_sequences.update_one(
                {"id": sid}, {"$set": {"active": False}},
            )
            await db.marketing_drip_enrolments.update_one(
                {"id": enr_id},
                {"$set": {"next_send_at": (now - timedelta(minutes=1)).isoformat()}},
            )
            await sequences_tick_all_tenants()
            deliveries2 = await db.marketing_deliveries.count_documents(
                {"enrolment_id": enr_id},
            )
            assert deliveries2 == 1, "tick fired a step on an inactive sequence"
        finally:
            await db.marketing_sequences.delete_one({"id": sid})
            await db.marketing_drip_enrolments.delete_many({"sequence_id": sid})
            await db.marketing_deliveries.delete_many({"sequence_id": sid})
            await db.customers.delete_one({"id": cid})

    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Full end-to-end via HTTP hooks — customer.create + service_report + review
# ═══════════════════════════════════════════════════════════════════════
def test_customer_created_hook_end_to_end(admin_headers):
    """POST /customers → drip event bus → enrolment created."""
    tpl = _pick_template_ids(admin_headers, "email")

    async def _seq():
        mine = await _tenant_id_of_admin()
        return await _make_sequence(mine, "customer_created", tpl, active=True), mine
    sid, mine = _run(_seq())
    try:
        r = requests.post(
            f"{API}/customers", headers=admin_headers,
            json={"name": f"M5c CH {uuid.uuid4().hex[:6]}",
                   "email": f"m5c-{uuid.uuid4().hex[:6]}@ex.com",
                   "phone": "555-0100"},
            timeout=15,
        )
        assert r.status_code in (200, 201), r.text
        new_cid = r.json()["id"]

        async def _check():
            db = _db()
            row = await db.marketing_drip_enrolments.find_one(
                {"sequence_id": sid, "customer_id": new_cid},
                {"_id": 0},
            )
            return row, new_cid
        row, new_cid = _run(_check())
        assert row is not None, "customer create → drip enrolment missing"
        assert row["trigger_source"] == "customer_created"

        # Cleanup the customer we just created
        async def _clean():
            await _db().customers.delete_one({"id": new_cid})
        _run(_clean())
    finally:
        _run(_cleanup_sequence(sid))
