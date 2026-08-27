"""Feb 2026 · Marketing · Phase 1 — Custom Trigger Builder test suite.

Covers all five deliverables:

  1.  ``event_registry`` — all 15 canonical events, alias resolution,
      supports_negative_offset / is_scheduled_event gates.
  2.  ``trigger_evaluator`` — 4 delay modes (immediate / after /
      before / on_weekday), 9 filter dimensions, AND/OR combining,
      empty-conditions edge case.
  3.  ``event_dispatcher`` — idempotency via ledger dedupe.
  4.  ``migrate_sequences_to_v2`` — v1 → v2 conversion, second-pass
      no-op (idempotency), preservation of legacy fields.
  5.  Daily cron sweeps — per-tenant isolation on
      ``invoice_overdue`` / ``customer_birthday`` /
      ``service_anniversary``.
  6.  ``POST /marketing/sequences/{sid}/preview-matches`` — shape +
      cap semantics.

Pure-Python primitives use plain ``pytest``; endpoints use ``requests``
against the running server (same pattern as ``test_marketing_m5c.py``
so tests share the same asyncio loop rebinding trick).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests


# ═══════════════════════════════════════════════════════════════════════
# Test infra — loop rebinding + login (mirrors test_marketing_m5c.py)
# ═══════════════════════════════════════════════════════════════════════
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
             or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _rebind_db_to_loop():
    """Rebind ``config.db`` + service modules to a loop-owning Motor
    client so tests can drive async helpers directly."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import services.marketing.drip_events as _de
    _de.db = fresh_db
    import services.marketing.event_dispatcher as _ed
    _ed.db = fresh_db
    import services.marketing.phase1_sweeps as _ps
    _ps.db = fresh_db
    import services.migrations.migrate_sequences_to_v2 as _mig
    _mig.db = fresh_db
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


async def _tenant_id_of_admin():
    db = _db()
    u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                 {"_id": 0, "tenant_id": 1})
    return u["tenant_id"]


# ═══════════════════════════════════════════════════════════════════════
# 1. event_registry
# ═══════════════════════════════════════════════════════════════════════
def test_event_registry_has_all_15_canonical_events():
    from services.marketing.event_registry import EVENT_CATALOG
    expected = {
        "new_lead", "lead_status_changed",
        "estimate_sent", "estimate_signed",
        "job_scheduled", "job_scheduled_reminder_1d",
        "job_completed", "job_cancelled",
        "invoice_sent", "invoice_paid", "invoice_overdue",
        "payment_failed",
        "customer_birthday", "service_anniversary",
        "chemistry_out_of_range", "repair_flagged",
    }
    # 16 total — the spec says "15 event types"; the reminder is a
    # sub-form of job_scheduled so the human count is 15 (grouping
    # scheduled+reminder). The catalog carries both keys so the
    # dispatcher can dedupe them separately.
    assert expected.issubset(set(EVENT_CATALOG.keys()))


def test_event_registry_alias_canonicalisation():
    from services.marketing.event_registry import canonicalize_event_key
    assert canonicalize_event_key("service_completed") == "job_completed"
    assert canonicalize_event_key("customer_created") == "new_lead"
    assert canonicalize_event_key("estimate_accepted") == "estimate_signed"
    assert canonicalize_event_key("invoice_past_due_3_days") == "invoice_overdue"
    assert canonicalize_event_key("birthday") == "customer_birthday"
    # Unknown key returns as-is.
    assert canonicalize_event_key("totally_made_up") == "totally_made_up"
    # Empty is empty.
    assert canonicalize_event_key("") == ""


def test_event_registry_supports_negative_offset_gate():
    from services.marketing.event_registry import supports_negative_offset
    # Only scheduled events with allow_negative_offset=True support "before".
    assert supports_negative_offset("job_scheduled") is True
    assert supports_negative_offset("customer_birthday") is True
    # Non-scheduled events must not.
    assert supports_negative_offset("new_lead") is False
    assert supports_negative_offset("invoice_paid") is False


def test_event_registry_is_valid_event_gate():
    from services.marketing.event_registry import is_valid_event
    assert is_valid_event("job_scheduled") is True
    # Aliases resolve.
    assert is_valid_event("service_completed") is True
    # Unknown fails.
    assert is_valid_event("nope_never") is False


def test_event_registry_list_events_shape():
    from services.marketing.event_registry import list_events
    rows = list_events()
    assert len(rows) >= 15
    first = rows[0]
    assert set(first.keys()) >= {"key", "label", "entity", "scheduled"}


# ═══════════════════════════════════════════════════════════════════════
# 2. trigger_evaluator — delay modes
# ═══════════════════════════════════════════════════════════════════════
def test_delay_mode_immediate_returns_now():
    from services.marketing.trigger_evaluator import resolve_enrollment_time
    frozen = datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc)
    got = resolve_enrollment_time(
        {"delay": {"mode": "immediate"}}, {}, tenant_now=frozen,
    )
    assert got == frozen


def test_delay_mode_after_days_adds_seconds():
    from services.marketing.trigger_evaluator import resolve_enrollment_time
    frozen = datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc)
    got = resolve_enrollment_time(
        {"delay": {"mode": "after", "value": 3, "unit": "day"}},
        {}, tenant_now=frozen,
    )
    assert got == frozen + timedelta(days=3)


def test_delay_mode_after_hours_adds_seconds():
    from services.marketing.trigger_evaluator import resolve_enrollment_time
    frozen = datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc)
    got = resolve_enrollment_time(
        {"delay": {"mode": "after", "value": 4, "unit": "hour"}},
        {}, tenant_now=frozen,
    )
    assert got == frozen + timedelta(hours=4)


def test_delay_mode_before_anchors_on_scheduled_at():
    from services.marketing.trigger_evaluator import resolve_enrollment_time
    frozen = datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc)
    anchor = datetime(2026, 2, 20, 9, 0, tzinfo=timezone.utc).isoformat()
    got = resolve_enrollment_time(
        {"delay": {"mode": "before", "value": 2}},
        {"scheduled_at": anchor}, tenant_now=frozen,
    )
    assert got == datetime(2026, 2, 18, 9, 0, tzinfo=timezone.utc)


def test_delay_mode_before_falls_back_to_now_without_anchor():
    from services.marketing.trigger_evaluator import resolve_enrollment_time
    frozen = datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc)
    got = resolve_enrollment_time(
        {"delay": {"mode": "before", "value": 3}},
        {},  # no scheduled_at → fall back to now
        tenant_now=frozen,
    )
    assert got == frozen - timedelta(days=3)


def test_delay_mode_on_weekday_rolls_forward_to_next_matching_day():
    from services.marketing.trigger_evaluator import resolve_enrollment_time
    # Sunday, Feb 15 2026 · target Tuesday (weekday=1)
    frozen = datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc)
    got = resolve_enrollment_time(
        {"delay": {"mode": "on_weekday", "weekday": 1,
                     "time_local": "09:00"}},
        {}, tenant_now=frozen,
    )
    # Feb 17 2026 = Tuesday
    assert got.date() == datetime(2026, 2, 17).date()
    assert got.hour == 9 and got.minute == 0


def test_delay_mode_on_weekday_same_day_but_past_bumps_a_week():
    from services.marketing.trigger_evaluator import resolve_enrollment_time
    # Sunday 20:00 UTC, target Sunday 09:00 → already past
    frozen = datetime(2026, 2, 15, 20, 0, tzinfo=timezone.utc)
    got = resolve_enrollment_time(
        {"delay": {"mode": "on_weekday", "weekday": 6,
                     "time_local": "09:00"}},
        {}, tenant_now=frozen,
    )
    # Next Sunday = Feb 22
    assert got.date() == datetime(2026, 2, 22).date()


def test_delay_mode_invalid_raises():
    from services.marketing.trigger_evaluator import resolve_enrollment_time
    with pytest.raises(ValueError):
        resolve_enrollment_time(
            {"delay": {"mode": "never", "value": 1}}, {},
        )


# ═══════════════════════════════════════════════════════════════════════
# 3. trigger_evaluator — 9 filter dimensions
# ═══════════════════════════════════════════════════════════════════════
def _base_payload(event: str = "job_completed"):
    return {"event": event, "customer_id": "cust-1"}


def _base_ctx(**overrides):
    ctx = {
        "customer_id": "cust-1",
        "customer_segment": "pool",
        "work_class": "service",
        "tags": ["vip"],
        "technician_id": "tech-1",
        "crew_id": "crew-alpha",
        "job_value": 500,
        "zip": "85387",
        "last_visit_days_ago": 45,
        "custom_fields": {"pool_type": "salt"},
    }
    ctx.update(overrides)
    return ctx


def _trigger(cond_filters, event="job_completed", logic="AND"):
    return {
        "logic": logic,
        "conditions": [{
            "event": event,
            "delay": {"mode": "immediate"},
            "filters": cond_filters,
        }],
    }


def test_filter_customer_segment_match_and_mismatch():
    from services.marketing.trigger_evaluator import evaluate_conditions
    assert evaluate_conditions(
        _trigger({"customer_segment": ["pool"]}),
        _base_payload(), _base_ctx(),
    )
    assert not evaluate_conditions(
        _trigger({"customer_segment": ["landscape"]}),
        _base_payload(), _base_ctx(customer_segment="pool"),
    )


def test_filter_work_class_intersection():
    from services.marketing.trigger_evaluator import evaluate_conditions
    assert evaluate_conditions(
        _trigger({"work_class": ["service", "repair"]}),
        _base_payload(), _base_ctx(work_class="service"),
    )
    assert not evaluate_conditions(
        _trigger({"work_class": ["repair"]}),
        _base_payload(), _base_ctx(work_class="service"),
    )


def test_filter_tags_set_intersection():
    from services.marketing.trigger_evaluator import evaluate_conditions
    # ctx.tags = ["vip"]; filter demands overlap.
    assert evaluate_conditions(
        _trigger({"tags": ["vip", "referral"]}),
        _base_payload(), _base_ctx(),
    )
    # No overlap → False.
    assert not evaluate_conditions(
        _trigger({"tags": ["prospect"]}),
        _base_payload(), _base_ctx(),
    )


def test_filter_technician_id_and_crew_id():
    from services.marketing.trigger_evaluator import evaluate_conditions
    assert evaluate_conditions(
        _trigger({"technician_id": ["tech-1", "tech-2"]}),
        _base_payload(), _base_ctx(),
    )
    assert not evaluate_conditions(
        _trigger({"technician_id": ["tech-99"]}),
        _base_payload(), _base_ctx(),
    )
    assert evaluate_conditions(
        _trigger({"crew_id": ["crew-alpha"]}),
        _base_payload(), _base_ctx(),
    )


def test_filter_job_value_gte_gate():
    from services.marketing.trigger_evaluator import evaluate_conditions
    assert evaluate_conditions(
        _trigger({"job_value_gte": 300}),
        _base_payload(), _base_ctx(job_value=500),
    )
    assert not evaluate_conditions(
        _trigger({"job_value_gte": 1000}),
        _base_payload(), _base_ctx(job_value=500),
    )


def test_filter_zip_membership():
    from services.marketing.trigger_evaluator import evaluate_conditions
    assert evaluate_conditions(
        _trigger({"zip": ["85387", "85388"]}),
        _base_payload(), _base_ctx(zip="85387"),
    )
    assert not evaluate_conditions(
        _trigger({"zip": ["10001"]}),
        _base_payload(), _base_ctx(zip="85387"),
    )


def test_filter_last_visit_gte_days_gate():
    from services.marketing.trigger_evaluator import evaluate_conditions
    assert evaluate_conditions(
        _trigger({"last_visit_gte_days": 30}),
        _base_payload(), _base_ctx(last_visit_days_ago=45),
    )
    assert not evaluate_conditions(
        _trigger({"last_visit_gte_days": 60}),
        _base_payload(), _base_ctx(last_visit_days_ago=45),
    )


def test_filter_custom_fields_eq_and_gte():
    from services.marketing.trigger_evaluator import evaluate_conditions
    # eq — matches
    assert evaluate_conditions(
        _trigger({"custom_fields": [
            {"key": "pool_type", "op": "eq", "value": "salt"}]}),
        _base_payload(), _base_ctx(),
    )
    # neq — should NOT match
    assert not evaluate_conditions(
        _trigger({"custom_fields": [
            {"key": "pool_type", "op": "neq", "value": "salt"}]}),
        _base_payload(), _base_ctx(),
    )
    # gte on a numeric field
    assert evaluate_conditions(
        _trigger({"custom_fields": [
            {"key": "gallons", "op": "gte", "value": 10000}]}),
        _base_payload(),
        _base_ctx(custom_fields={"gallons": 12000}),
    )


def test_filter_missing_ctx_fails_closed_on_specified_filter():
    from services.marketing.trigger_evaluator import evaluate_conditions
    # zip filter present, ctx zip missing → must NOT match.
    assert not evaluate_conditions(
        _trigger({"zip": ["85387"]}),
        _base_payload(), _base_ctx(zip=None),
    )


def test_filter_empty_all_pass_through():
    from services.marketing.trigger_evaluator import evaluate_conditions
    # No filters specified → matches unconditionally on event equality.
    assert evaluate_conditions(
        _trigger({}), _base_payload(), _base_ctx(),
    )


# ═══════════════════════════════════════════════════════════════════════
# 4. trigger_evaluator — AND / OR combining
# ═══════════════════════════════════════════════════════════════════════
def test_and_logic_requires_all_conditions():
    from services.marketing.trigger_evaluator import evaluate_conditions
    trig = {
        "logic": "AND",
        "conditions": [
            {"event": "job_completed",
             "delay": {"mode": "immediate"},
             "filters": {"customer_segment": ["pool"]}},
            {"event": "job_completed",
             "delay": {"mode": "immediate"},
             "filters": {"zip": ["85387"]}},
        ],
    }
    ctx = _base_ctx()
    assert evaluate_conditions(trig, _base_payload("job_completed"), ctx)
    # Break the second condition — AND now fails.
    ctx2 = _base_ctx(zip="10001")
    assert not evaluate_conditions(trig, _base_payload("job_completed"), ctx2)


def test_or_logic_matches_any_condition():
    from services.marketing.trigger_evaluator import evaluate_conditions
    trig = {
        "logic": "OR",
        "conditions": [
            {"event": "job_completed",
             "delay": {"mode": "immediate"},
             "filters": {"zip": ["10001"]}},        # won't match
            {"event": "job_completed",
             "delay": {"mode": "immediate"},
             "filters": {"customer_segment": ["pool"]}},  # WILL match
        ],
    }
    assert evaluate_conditions(trig, _base_payload("job_completed"),
                                 _base_ctx())


def test_evaluate_empty_conditions_returns_false():
    from services.marketing.trigger_evaluator import evaluate_conditions
    assert not evaluate_conditions(
        {"logic": "AND", "conditions": []},
        _base_payload(), _base_ctx(),
    )


def test_event_key_mismatch_returns_false():
    from services.marketing.trigger_evaluator import evaluate_conditions
    trig = _trigger({}, event="invoice_paid")
    # Payload is job_completed → doesn't match invoice_paid condition.
    assert not evaluate_conditions(trig, _base_payload("job_completed"),
                                     _base_ctx())


def test_find_matching_condition_returns_first_hit():
    from services.marketing.trigger_evaluator import find_matching_condition
    trig = {
        "logic": "OR",
        "conditions": [
            {"event": "invoice_paid",
             "delay": {"mode": "immediate"}, "filters": {}},
            {"event": "job_completed",
             "delay": {"mode": "after", "value": 3, "unit": "day"},
             "filters": {}},
        ],
    }
    match = find_matching_condition(
        trig, _base_payload("job_completed"), _base_ctx(),
    )
    assert match is not None
    assert match["event"] == "job_completed"
    assert match["delay"]["value"] == 3


# ═══════════════════════════════════════════════════════════════════════
# 5. event_dispatcher — idempotency via ledger dedupe
# ═══════════════════════════════════════════════════════════════════════
def test_emit_event_deduplicates_on_same_correlation_id(admin_headers):
    """Second emit for the same (tenant, entity, event) returns
    ``deduped=1`` and does not fan out again."""
    async def _go():
        from services.marketing.event_dispatcher import emit_event
        tid = await _tenant_id_of_admin()
        db = _db()
        cid = f"phase1-cust-{uuid.uuid4().hex[:6]}"
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "Phase1 Dedupe",
            "service_line": "pool", "tags": [],
        })
        corr = f"dedupe-{uuid.uuid4().hex[:8]}"
        try:
            r1 = await emit_event(
                event="job_completed", tenant_id=tid,
                entity_id="job-x", customer_id=cid,
                payload_extras={"correlation_id": corr},
            )
            r2 = await emit_event(
                event="job_completed", tenant_id=tid,
                entity_id="job-x", customer_id=cid,
                payload_extras={"correlation_id": corr},
            )
            assert r1.get("deduped") == 0
            assert r2.get("deduped") == 1
        finally:
            await db.customers.delete_one({"id": cid})
            await db.marketing_event_ledger.delete_many({
                "tenant_id": tid, "correlation_id": corr,
            })
    _run(_go())


def test_emit_event_invalid_event_returns_early(admin_headers):
    async def _go():
        from services.marketing.event_dispatcher import emit_event
        tid = await _tenant_id_of_admin()
        r = await emit_event(
            event="totally_made_up_event",
            tenant_id=tid, entity_id="x", customer_id="y",
        )
        assert r.get("enrolled") == 0
        assert r.get("matched_sequences") == 0
    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# 6. migrate_sequences_to_v2 — v1 → v2 → v2 idempotency
# ═══════════════════════════════════════════════════════════════════════
def test_migration_converts_v1_scalar_to_v2_nested(admin_headers):
    async def _go():
        from services.migrations.migrate_sequences_to_v2 import (
            migrate_marketing_sequences_to_v2,
        )
        db = _db()
        tid = await _tenant_id_of_admin()
        sid = f"v2mig-{uuid.uuid4().hex[:8]}"
        await db.marketing_sequences.insert_one({
            "id": sid, "tenant_id": tid,
            "name": "V2 Mig Fixture",
            "trigger_type": "service_completed",
            "trigger_config": {},
            "steps": [],
            "active": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            report = await migrate_marketing_sequences_to_v2()
            assert report["migrated"] >= 1
            row = await db.marketing_sequences.find_one(
                {"id": sid}, {"_id": 0},
            )
            assert row["schema_version"] == 2
            assert row["trigger"]["logic"] == "AND"
            assert row["trigger"]["conditions"][0]["event"] == "job_completed"
            # Legacy fields preserved.
            assert row["trigger_type"] == "service_completed"
        finally:
            await db.marketing_sequences.delete_one({"id": sid})
    _run(_go())


def test_migration_second_pass_is_noop(admin_headers):
    async def _go():
        from services.migrations.migrate_sequences_to_v2 import (
            migrate_marketing_sequences_to_v2,
        )
        db = _db()
        tid = await _tenant_id_of_admin()
        sid = f"v2noop-{uuid.uuid4().hex[:8]}"
        await db.marketing_sequences.insert_one({
            "id": sid, "tenant_id": tid,
            "name": "V2 Noop Fixture",
            "trigger_type": "birthday",
            "trigger_config": {},
            "steps": [],
            "active": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            r1 = await migrate_marketing_sequences_to_v2()
            n_migrated_first = r1["migrated"]
            assert n_migrated_first >= 1
            # Second run — the SAME sequence should NOT count as migrated.
            r2 = await migrate_marketing_sequences_to_v2()
            # After the first pass everything is v2, so migrated must be
            # <= n_migrated_first and the specific sid must be already_v2.
            row = await db.marketing_sequences.find_one(
                {"id": sid}, {"_id": 0, "schema_version": 1},
            )
            assert row["schema_version"] == 2
            # Ensure no new writes stamped on the second pass by
            # confirming migrated didn't grow.
            assert r2["migrated"] <= r1["migrated"], (r1, r2)
        finally:
            await db.marketing_sequences.delete_one({"id": sid})
    _run(_go())


def test_migration_preserves_invoice_past_due_days_offset(admin_headers):
    """The legacy ``invoice_past_due_N_days`` sequence carries
    ``days_past_due`` in trigger_config — the migration lifts it into
    a ``delay=after N days`` on the canonicalised ``invoice_overdue``
    event."""
    async def _go():
        from services.migrations.migrate_sequences_to_v2 import (
            migrate_marketing_sequences_to_v2,
        )
        db = _db()
        tid = await _tenant_id_of_admin()
        sid = f"v2pd-{uuid.uuid4().hex[:8]}"
        await db.marketing_sequences.insert_one({
            "id": sid, "tenant_id": tid,
            "name": "Past Due 7d",
            "trigger_type": "invoice_past_due_N_days",
            "trigger_config": {"days_past_due": 7},
            "steps": [],
            "active": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            await migrate_marketing_sequences_to_v2()
            row = await db.marketing_sequences.find_one(
                {"id": sid}, {"_id": 0},
            )
            cond = row["trigger"]["conditions"][0]
            assert cond["event"] == "invoice_overdue"
            assert cond["delay"]["mode"] == "after"
            assert cond["delay"]["value"] == 7
            assert cond["delay"]["unit"] == "day"
        finally:
            await db.marketing_sequences.delete_one({"id": sid})
    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# 7. Daily cron sweeps — per-tenant isolation
# ═══════════════════════════════════════════════════════════════════════
def test_sweep_customer_birthday_fires_and_dedupes(admin_headers):
    async def _go():
        db = _db()
        tid = await _tenant_id_of_admin()
        # Insert a customer whose birthday IS today (arbitrary year).
        today_mmdd = datetime.now(timezone.utc).strftime("%m-%d")
        cid = f"bday-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": "Bday Test",
            "birthday": f"1990-{today_mmdd}",
            "service_line": "pool", "tags": [],
        })
        try:
            from services.marketing.phase1_sweeps import (
                _sweep_customer_birthday,
            )
            await _sweep_customer_birthday(tid)
            # Second call — the ledger dedupes on
            # ``{cid}:birthday:{year}`` so nothing new should be
            # inserted.
            await _sweep_customer_birthday(tid)
            year = datetime.now(timezone.utc).year
            corr = f"{cid}:birthday:{year}"
            ledger_rows = await db.marketing_event_ledger.count_documents(
                {"tenant_id": tid, "correlation_id": corr},
            )
            assert ledger_rows == 1, (
                f"expected exactly one ledger row, got {ledger_rows}"
            )
        finally:
            await db.customers.delete_one({"id": cid})
            await db.marketing_event_ledger.delete_many(
                {"tenant_id": tid,
                 "correlation_id": f"{cid}:birthday:{datetime.now(timezone.utc).year}"},
            )
    _run(_go())


def test_sweep_invoice_overdue_only_hits_unpaid_past_due_invoices(admin_headers):
    async def _go():
        db = _db()
        tid = await _tenant_id_of_admin()
        cid = f"od-cust-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid, "name": "OD Cust",
        })
        # 3 invoices: 1 unpaid+past_due, 1 paid+past_due, 1 unpaid+future.
        past = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=5)).date().isoformat()
        docs = [
            {"id": f"inv-hit-{uuid.uuid4().hex[:6]}", "tenant_id": tid,
             "customer_id": cid, "doc_type": "invoice",
             "due_date": past, "payment_status": "unpaid",
             "total": 100, "amount_paid": 0,
             "created_at": datetime.now(timezone.utc).isoformat()},
            {"id": f"inv-paid-{uuid.uuid4().hex[:6]}", "tenant_id": tid,
             "customer_id": cid, "doc_type": "invoice",
             "due_date": past, "payment_status": "paid",
             "total": 100, "amount_paid": 100,
             "created_at": datetime.now(timezone.utc).isoformat()},
            {"id": f"inv-future-{uuid.uuid4().hex[:6]}", "tenant_id": tid,
             "customer_id": cid, "doc_type": "invoice",
             "due_date": future, "payment_status": "unpaid",
             "total": 100, "amount_paid": 0,
             "created_at": datetime.now(timezone.utc).isoformat()},
        ]
        await db.quotes.insert_many(docs)
        try:
            from services.marketing.phase1_sweeps import (
                _sweep_invoice_overdue,
            )
            await _sweep_invoice_overdue(tid)
            # Ledger should have exactly ONE overdue row (the "hit" invoice).
            hit_id = docs[0]["id"]
            rows = await db.marketing_event_ledger.count_documents({
                "tenant_id": tid, "trigger_type": "invoice_overdue",
                "correlation_id": hit_id,
            })
            assert rows == 1, f"expected 1 overdue emit, got {rows}"
            # The paid and future invoices must NOT be in the ledger.
            for skip_doc in (docs[1], docs[2]):
                assert 0 == await db.marketing_event_ledger.count_documents({
                    "tenant_id": tid, "trigger_type": "invoice_overdue",
                    "correlation_id": skip_doc["id"],
                })
        finally:
            await db.quotes.delete_many({"customer_id": cid})
            await db.customers.delete_one({"id": cid})
            await db.marketing_event_ledger.delete_many({
                "tenant_id": tid, "trigger_type": "invoice_overdue",
                "customer_id": cid,
            })
    _run(_go())


def test_sweep_service_anniversary_skips_year_zero(admin_headers):
    """A customer created today has 0-year anniversary — must NOT fire."""
    async def _go():
        db = _db()
        tid = await _tenant_id_of_admin()
        cid = f"anniv-{uuid.uuid4().hex[:8]}"
        await db.customers.insert_one({
            "id": cid, "tenant_id": tid,
            "name": "Same-day cust",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            from services.marketing.phase1_sweeps import (
                _sweep_service_anniversary,
            )
            await _sweep_service_anniversary(tid)
            rows = await db.marketing_event_ledger.count_documents({
                "tenant_id": tid, "trigger_type": "service_anniversary",
                "customer_id": cid,
            })
            assert rows == 0
        finally:
            await db.customers.delete_one({"id": cid})
    _run(_go())


def test_daily_phase1_trigger_sweep_isolates_tenants(admin_headers):
    """The main sweep entry point walks every tenant even if one
    tenant's inner call crashes. We simulate a crash by monkey-
    patching one of the sub-sweeps."""
    async def _go():
        from services.marketing import phase1_sweeps as _ps
        original = _ps._sweep_invoice_overdue

        async def _boom(_tid: str) -> int:
            raise RuntimeError("simulated tenant crash")

        _ps._sweep_invoice_overdue = _boom
        try:
            result = await _ps.daily_phase1_trigger_sweep()
        finally:
            _ps._sweep_invoice_overdue = original
        # Even though every tenant's invoice_overdue call crashed,
        # the function returned a normal summary and moved on.
        assert result["tenants"] >= 1
        assert result["tenants_errored"] >= 1
    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# 8. preview-matches endpoint — shape + cap
# ═══════════════════════════════════════════════════════════════════════
def _find_seq_id(headers, trigger_type):
    """Return the id of any existing sequence for the admin's tenant
    with the given legacy trigger_type. Ensures the endpoint has a
    real target to preview."""
    r = requests.get(f"{API}/marketing/sequences",
                      headers=headers, timeout=15)
    for s in r.json().get("sequences", []):
        if s.get("trigger_type") == trigger_type:
            return s["id"]
    return None


def test_preview_matches_response_shape(admin_headers):
    """Every response field mandated by the Phase 2 spec is present."""
    async def _go():
        # Guarantee a sequence exists we can preview against.
        db = _db()
        tid = await _tenant_id_of_admin()
        sid = f"prv-{uuid.uuid4().hex[:8]}"
        await db.marketing_sequences.insert_one({
            "id": sid, "tenant_id": tid,
            "name": "Preview Fixture",
            "trigger_type": "customer_created",
            "trigger_config": {},
            "trigger": {
                "logic": "AND",
                "conditions": [{
                    "event": "new_lead",
                    "delay": {"mode": "immediate"},
                    "filters": {},
                }],
            },
            "schema_version": 2, "steps": [], "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            r = requests.post(
                f"{API}/marketing/sequences/{sid}/preview-matches",
                headers=admin_headers, json={}, timeout=30,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            for key in ("sequence_id", "evaluated_at", "match_count",
                        "sample", "truncated"):
                assert key in body, key
            assert body["sequence_id"] == sid
            assert isinstance(body["sample"], list)
            assert isinstance(body["truncated"], bool)
        finally:
            await db.marketing_sequences.delete_one({"id": sid})
    _run(_go())


def test_preview_matches_respects_sample_cap(admin_headers):
    """Sample is capped at 25 even when the internal walk finds more."""
    async def _go():
        db = _db()
        tid = await _tenant_id_of_admin()
        sid = f"prvcap-{uuid.uuid4().hex[:8]}"
        # Seed 30 customers so the walk yields well over 25.
        cust_ids = [f"prvcap-cust-{uuid.uuid4().hex[:6]}"
                     for _ in range(30)]
        await db.customers.insert_many([
            {"id": cid, "tenant_id": tid,
              "name": f"Preview Cap {i}",
              "service_line": "pool", "tags": [],
              "created_at": datetime.now(timezone.utc).isoformat()}
            for i, cid in enumerate(cust_ids)
        ])
        await db.marketing_sequences.insert_one({
            "id": sid, "tenant_id": tid,
            "name": "Preview Cap Fixture",
            "trigger_type": "customer_created",
            "trigger_config": {},
            "trigger": {
                "logic": "AND",
                "conditions": [{
                    "event": "new_lead",
                    "delay": {"mode": "immediate"},
                    "filters": {},
                }],
            },
            "schema_version": 2, "steps": [], "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            r = requests.post(
                f"{API}/marketing/sequences/{sid}/preview-matches",
                headers=admin_headers, json={}, timeout=45,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            # Sample is HARD-capped at 25.
            assert len(body["sample"]) <= 25
            # If we found >25 matches we must announce truncation.
            if body["match_count"] > 25:
                assert body["truncated"] is True
        finally:
            await db.marketing_sequences.delete_one({"id": sid})
            await db.customers.delete_many({"id": {"$in": cust_ids}})
    _run(_go())


def test_preview_matches_404_for_unknown_sequence(admin_headers):
    r = requests.post(
        f"{API}/marketing/sequences/does-not-exist-{uuid.uuid4().hex[:6]}/preview-matches",
        headers=admin_headers, json={}, timeout=15,
    )
    assert r.status_code == 404, r.text


def test_preview_matches_accepts_trigger_override(admin_headers):
    """Passing ``trigger_override`` in the body dry-runs the unsaved
    rule (used by the Phase-2 builder)."""
    async def _go():
        db = _db()
        tid = await _tenant_id_of_admin()
        sid = f"prvov-{uuid.uuid4().hex[:8]}"
        await db.marketing_sequences.insert_one({
            "id": sid, "tenant_id": tid,
            "name": "Preview Override Fixture",
            "trigger_type": "customer_created",
            "trigger_config": {},
            "schema_version": 2, "steps": [], "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            r = requests.post(
                f"{API}/marketing/sequences/{sid}/preview-matches",
                headers=admin_headers, timeout=30,
                json={"trigger_override": {
                    "logic": "AND",
                    "conditions": [{
                        "event": "new_lead",
                        "delay": {"mode": "immediate"},
                        # zip filter that no customer has → 0 matches
                        "filters": {"zip": ["99999-not-real"]},
                    }],
                }},
            )
            assert r.status_code == 200, r.text
            assert r.json()["match_count"] == 0
        finally:
            await db.marketing_sequences.delete_one({"id": sid})
    _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# 9. GET /marketing/sequences/event-catalog — Phase-2 UI feed
# ═══════════════════════════════════════════════════════════════════════
def test_event_catalog_endpoint_returns_all_canonical_events(admin_headers):
    r = requests.get(f"{API}/marketing/sequences/event-catalog",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "events" in body and "count" in body
    events = body["events"]
    assert body["count"] == len(events)
    # Every canonical event catalog entry must be present.
    from services.marketing.event_registry import EVENT_CATALOG
    returned_ids = {e["id"] for e in events}
    assert returned_ids == set(EVENT_CATALOG.keys()), (
        f"missing={set(EVENT_CATALOG.keys()) - returned_ids} "
        f"extra={returned_ids - set(EVENT_CATALOG.keys())}"
    )


def test_event_catalog_each_entry_has_four_metadata_fields(admin_headers):
    r = requests.get(f"{API}/marketing/sequences/event-catalog",
                      headers=admin_headers, timeout=15)
    body = r.json()
    for e in body["events"]:
        assert set(e.keys()) == {"id", "label", "entity", "scheduled",
                                  "allow_negative_offset"}, e
        assert isinstance(e["id"], str) and e["id"]
        assert isinstance(e["label"], str) and e["label"]
        assert isinstance(e["entity"], str) and e["entity"]
        assert isinstance(e["scheduled"], bool)
        assert isinstance(e["allow_negative_offset"], bool)


def test_event_catalog_ordering_is_deterministic(admin_headers):
    """Same request → same order; entities grouped
    lead → estimate → job → invoice → payment → customer."""
    r1 = requests.get(f"{API}/marketing/sequences/event-catalog",
                       headers=admin_headers, timeout=15).json()
    r2 = requests.get(f"{API}/marketing/sequences/event-catalog",
                       headers=admin_headers, timeout=15).json()
    ids1 = [e["id"] for e in r1["events"]]
    ids2 = [e["id"] for e in r2["events"]]
    assert ids1 == ids2, "order not deterministic"
    # Verify entity grouping order.
    seen_entities = []
    for e in r1["events"]:
        if e["entity"] not in seen_entities:
            seen_entities.append(e["entity"])
    order_index = {"lead": 0, "estimate": 1, "job": 2,
                   "invoice": 3, "payment": 4, "customer": 5}
    idxs = [order_index.get(x, 99) for x in seen_entities]
    assert idxs == sorted(idxs), f"entity grouping wrong: {seen_entities}"


def test_event_catalog_negative_offset_flag_matches_registry(admin_headers):
    r = requests.get(f"{API}/marketing/sequences/event-catalog",
                      headers=admin_headers, timeout=15).json()
    by_id = {e["id"]: e for e in r["events"]}
    # Spot-check: job_scheduled + customer_birthday allow "before"
    # delays; new_lead + invoice_paid do NOT.
    assert by_id["job_scheduled"]["allow_negative_offset"] is True
    assert by_id["customer_birthday"]["allow_negative_offset"] is True
    assert by_id["new_lead"]["allow_negative_offset"] is False
    assert by_id["invoice_paid"]["allow_negative_offset"] is False


def test_event_catalog_endpoint_requires_admin_auth():
    """Unauthenticated request rejects with 401/403 (Depends(require_admin))."""
    r = requests.get(f"{API}/marketing/sequences/event-catalog", timeout=15)
    assert r.status_code in (401, 403), r.status_code


def test_legacy_triggers_registry_untouched(admin_headers):
    """The M5c-era ``/triggers/registry`` MUST keep its exact shape
    (legacy consumers depend on ``type`` + ``config_schema``)."""
    r = requests.get(f"{API}/marketing/sequences/triggers/registry",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    triggers = r.json()["triggers"]
    # Every entry must expose the legacy shape (type + config_schema).
    for t in triggers:
        assert "type" in t
        assert "config_schema" in t
    # A couple of legacy ids are still present (backwards compat).
    types = {t["type"] for t in triggers}
    for legacy in ("service_completed", "customer_created",
                    "invoice_past_due_N_days", "birthday"):
        assert legacy in types, (
            f"legacy trigger {legacy!r} must remain in the legacy registry"
        )


# ═══════════════════════════════════════════════════════════════════════
# 10. Post-migration state — every schema_v2 sequence uses canonical events
# ═══════════════════════════════════════════════════════════════════════
def test_all_schema_v2_sequences_use_canonical_event_ids(admin_headers):
    async def _go():
        db = _db()
        # Force a re-run so the assertion sees the LATEST rules.
        from services.migrations.migrate_sequences_to_v2 import (
            migrate_marketing_sequences_to_v2,
        )
        await migrate_marketing_sequences_to_v2()

        from services.marketing.event_registry import is_valid_event
        offenders: list = []
        rows = await db.marketing_sequences.find(
            {"schema_version": {"$gte": 2}},
            {"_id": 0, "id": 1, "tenant_id": 1, "trigger_type": 1,
              "trigger": 1},
        ).to_list(1000)
        assert rows, "no v2 sequences found — migration did not run"
        for r in rows:
            conds = ((r.get("trigger") or {}).get("conditions") or [])
            for c in conds:
                ev = str(c.get("event") or "")
                if not is_valid_event(ev):
                    offenders.append({
                        "id": r["id"], "trigger_type": r.get("trigger_type"),
                        "bad_event": ev,
                    })
        assert not offenders, (
            f"non-canonical events leaked into v2 sequences: {offenders}"
        )
    _run(_go())


def test_non_event_legacy_triggers_have_empty_v2_conditions(admin_headers):
    """``manual`` and ``segment_join`` sequences must migrate to
    ``conditions:[]`` — the evaluator returns False on empty
    conditions, so they never accidentally fire from emit_event."""
    async def _go():
        db = _db()
        from services.migrations.migrate_sequences_to_v2 import (
            migrate_marketing_sequences_to_v2,
        )
        await migrate_marketing_sequences_to_v2()
        rows = await db.marketing_sequences.find(
            {"schema_version": {"$gte": 2},
              "trigger_type": {"$in": ["manual", "segment_join"]}},
            {"_id": 0, "id": 1, "trigger_type": 1, "trigger": 1},
        ).to_list(200)
        for r in rows:
            conds = ((r.get("trigger") or {}).get("conditions") or [])
            assert conds == [], (
                f"sequence {r['id']} (trigger_type={r['trigger_type']}) "
                f"should have empty v2 conditions, got {conds}"
            )
    _run(_go())
