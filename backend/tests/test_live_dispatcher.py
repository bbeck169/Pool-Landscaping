"""LDM-B · Feb-2026 — AI Live Dispatcher scan tests.

Locks the eight acceptance cases from
``memory/SPEC_LIVE_DISPATCHER_AND_MAINTENANCE.md`` §LDM-B tests:

    1. Tenant-scoped isolation — tenant A tech doesn't reach into
       tenant B customers, and vice versa.
    2. Threshold respected — default 20 vs custom 30 both honored.
    3. Quiet hours skip — send_sms returning ``status="deferred"``
       still stamps the dedupe slot (per user-approved matrix).
    4. Opt-out skip — send_sms returning ``skipped_opted_out``
       still stamps the dedupe slot.
    5. Dedupe window — two back-to-back scans → exactly one
       dispatch_events row + one SMS burst.
    6. N-customer selection — default 3 vs custom 5 both honored.
    7. No pings → tech skipped gracefully (no dispatch event).
    8. All-failed batch → dedupe slot NOT stamped (retry next tick).

Testing style
─────────────
Real Motor DB via a per-test asyncio loop (matches P52 /
test_automation_rules.py conventions). ``send_sms`` is injected as
a stub so we drive its return status deterministically without
touching the real adapter chain (BYO / RC HTTP / quiet-hours defer).
Cleanup is scoped to LDMB_-tagged rows so full-suite runs stay
hermetic.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "LDMB_"

# Reference "now" — Wed 2026-02-11 15:00:00 UTC.
_FIXED_NOW = datetime(2026, 2, 11, 15, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z",
    )


def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


# ═════════════════════════════════════════════════════════════════════
# Test-scoped cleanup.
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def seeded(dbc):
    """Track every LDMB_-tagged row we insert; drop them on teardown."""
    tenants: List[str] = []
    users: List[str] = []
    jobs: List[str] = []
    customers: List[str] = []
    pings: List[str] = []
    events: List[str] = []
    yield {
        "tenants": tenants, "users": users, "jobs": jobs,
        "customers": customers, "pings": pings, "events": events,
    }
    if tenants:
        dbc.tenants.delete_many({"id": {"$in": tenants}})
    if users:
        dbc.users.delete_many({"id": {"$in": users}})
    if jobs:
        dbc.jobs.delete_many({"id": {"$in": jobs}})
    if customers:
        dbc.customers.delete_many({"id": {"$in": customers}})
    if pings:
        dbc.gps_pings.delete_many({"id": {"$in": pings}})
    # Sweep dispatch_events by tenant_id — the scan may have
    # inserted rows we didn't track by id.
    if tenants:
        dbc.dispatch_events.delete_many({"tenant_id": {"$in": tenants}})
    if events:
        dbc.dispatch_events.delete_many({"id": {"$in": events}})


# ═════════════════════════════════════════════════════════════════════
# Seed helpers — write everything via sync pymongo so we don't fight
# Motor's loop binding.
# ═════════════════════════════════════════════════════════════════════
def _seed_tenant(dbc, seeded, *, rules: Optional[dict] = None) -> str:
    tid = _fresh("TEN")
    doc: Dict[str, Any] = {
        "id": tid,
        "name": f"LDMB tenant {tid[-6:]}",
        "timezone": "America/New_York",
        "created_at": _iso(_FIXED_NOW - timedelta(days=30)),
    }
    if rules is not None:
        doc["settings"] = {"automation_rules": rules}
    dbc.tenants.insert_one(doc)
    seeded["tenants"].append(tid)
    return tid


def _seed_tech(dbc, seeded, tenant_id: str) -> Dict[str, str]:
    uid = _fresh("USR")
    tech_id = _fresh("TECH")
    dbc.users.insert_one({
        "id": uid,
        "tenant_id": tenant_id,
        "name": "LDMB Tech",
        "role": "technician",
        "technician_id": tech_id,
    })
    seeded["users"].append(uid)
    return {"user_id": uid, "tech_id": tech_id}


def _seed_customer(dbc, seeded, tenant_id: str,
                    *, phone: str = "+15551234567") -> str:
    cid = _fresh("CUS")
    dbc.customers.insert_one({
        "id": cid,
        "tenant_id": tenant_id,
        "name": "LDMB Customer",
        "phone": phone,
    })
    seeded["customers"].append(cid)
    return cid


def _seed_visit(dbc, seeded, tenant_id: str, tech_id: str,
                 customer_id: str, *, scheduled_start: datetime,
                 lat: float = 33.5, lng: float = -112.0,
                 status: str = "scheduled") -> str:
    jid = _fresh("JOB")
    dbc.jobs.insert_one({
        "id": jid,
        "tenant_id": tenant_id,
        "technician_id": tech_id,
        "customer_id": customer_id,
        "status": status,
        "scheduled_start": _iso(scheduled_start),
        "scheduled_date": scheduled_start.date().isoformat(),
        "site_lat": lat,
        "site_lng": lng,
        "service_type": "Pool Cleaning",
    })
    seeded["jobs"].append(jid)
    return jid


def _seed_ping(dbc, seeded, tenant_id: str, user_id: str,
                *, lat: float, lon: float, captured_at: datetime) -> str:
    pid = _fresh("PING")
    dbc.gps_pings.insert_one({
        "id": pid,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "lat": lat,
        "lon": lon,
        "accuracy_m": 15.0,
        "source": "foreground",
        "captured_at": _iso(captured_at),
        "received_at": _iso(captured_at + timedelta(seconds=30)),
    })
    seeded["pings"].append(pid)
    return pid


# ═════════════════════════════════════════════════════════════════════
# send_sms stubs — track invocations so we can assert on the call
# pattern without touching the real adapter.
# ═════════════════════════════════════════════════════════════════════
class _SMSStub:
    """Callable stub matching ``services.comms_sms_adapter.send_sms``
    signature. Records every call and returns a status per the ctor
    arg (default ``sent``)."""

    def __init__(self, status: str = "sent"):
        self.status = status
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, *, tenant_id: str, to_phone: str,
                        body: str, mms_url: Optional[str] = None,
                        context: Any = None,
                        ) -> Dict[str, Any]:
        # SAFE-SEND-A · Feb-2026 — real ``comms_sms_adapter.send_sms``
        # now requires ``context`` as a kwarg-only param.  The stub
        # captures it so tests can assert on the stamped context
        # (defaults to ``None`` when a legacy test doesn't care).
        self.calls.append({
            "tenant_id": tenant_id, "to_phone": to_phone,
            "body": body, "mms_url": mms_url,
            "context": context,
        })
        return {
            "status": self.status,
            "provider_id": None,
            "character_count": len(body),
            "segment_count": 1,
        }


def _run(coro_factory):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    adb = client[DB_NAME]
    try:
        return loop.run_until_complete(coro_factory(adb))
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


def _far_dest_visit(dbc, seeded, tenant_id, tech_id, customer_id,
                     *, scheduled_start: datetime, sender_delay_km=100):
    """Seed a visit far from ping origin (0,0) so haversine yields
    a large enough delay to breach the default 20-min threshold.
    100 miles at 30mph = 200 minutes travel = massive delay."""
    return _seed_visit(
        dbc, seeded, tenant_id, tech_id, customer_id,
        scheduled_start=scheduled_start,
        lat=34.5, lng=-112.0,  # ~1° away from (33.5, -112.0)
    )


# ═════════════════════════════════════════════════════════════════════
# Test 1 — tenant isolation.
# ═════════════════════════════════════════════════════════════════════
def test_1_tenant_scoped_isolation(dbc, seeded):
    """Tenant A's late tech does not trigger SMS to tenant B customers."""
    now = _FIXED_NOW
    # Tenant A — set up a delay scenario.
    ta = _seed_tenant(dbc, seeded)
    a_tech = _seed_tech(dbc, seeded, ta)
    a_cust = _seed_customer(dbc, seeded, ta, phone="+15551110000")
    _seed_ping(dbc, seeded, ta, a_tech["user_id"],
                 lat=33.5, lon=-112.0,
                 captured_at=now - timedelta(minutes=2))
    _far_dest_visit(dbc, seeded, ta, a_tech["tech_id"], a_cust,
                     scheduled_start=now - timedelta(minutes=5))
    # Tenant B — has a customer that MUST NOT receive an SMS.
    tb = _seed_tenant(dbc, seeded)
    _seed_tech(dbc, seeded, tb)
    b_cust = _seed_customer(dbc, seeded, tb, phone="+15559990000")
    # (no visit on B → nothing to trigger)

    stub = _SMSStub(status="sent")

    async def _apply(adb):
        from services.live_dispatcher import scan
        return await scan(adb, now=now, send_sms=stub)

    stats = _run(_apply)
    # Delay detected + dispatched — but ONLY for tenant A.
    assert stats["dispatches_fired"] == 1
    assert stats["sms_sent"] == 1
    assert len(stub.calls) == 1
    assert stub.calls[0]["to_phone"] == "+15551110000"
    assert stub.calls[0]["tenant_id"] == ta
    # dispatch_events row is tenant-scoped to A.
    events_a = list(dbc.dispatch_events.find({"tenant_id": ta}))
    events_b = list(dbc.dispatch_events.find({"tenant_id": tb}))
    assert len(events_a) == 1
    assert len(events_b) == 0
    assert b_cust not in events_a[0]["customers_notified"]


# ═════════════════════════════════════════════════════════════════════
# Test 2 — threshold respected (default 20 vs custom 30).
# ═════════════════════════════════════════════════════════════════════
def test_2_threshold_respected_default_vs_custom(dbc, seeded):
    """Same delay profile, two tenants: default 20-min threshold
    fires; custom 30-min threshold does NOT fire (delay is between
    the two)."""
    now = _FIXED_NOW
    # Craft a delay ~25 min:
    #   - Tech at (33.5, -112.0) at now-2min.
    #   - Visit at ~10 miles → 20 min travel.
    #   - scheduled_start = now - 5 min → arrival at now+20min
    #     → 25 min late.
    #   ~0.145° lat step ≈ 10 miles at this latitude.
    def _seed_scenario(tenant_id: str):
        tech = _seed_tech(dbc, seeded, tenant_id)
        cust = _seed_customer(dbc, seeded, tenant_id,
                                 phone=f"+1555{tenant_id[-7:].replace('_', '0')}")
        _seed_ping(dbc, seeded, tenant_id, tech["user_id"],
                     lat=33.5, lon=-112.0,
                     captured_at=now - timedelta(minutes=2))
        _seed_visit(dbc, seeded, tenant_id, tech["tech_id"], cust,
                     scheduled_start=now - timedelta(minutes=5),
                     lat=33.645, lng=-112.0)  # ~10 miles north
        return tech

    ta = _seed_tenant(dbc, seeded)  # default rules (threshold=20)
    _seed_scenario(ta)
    tb = _seed_tenant(dbc, seeded, rules={
        "dispatch_delay_threshold_mins": 30,
        "dispatch_sms_customer_count": 3,
        "filter_clean_interval_months": 6,
        "salt_cell_replacement_months": 36,
    })
    _seed_scenario(tb)

    stub = _SMSStub(status="sent")

    async def _apply(adb):
        from services.live_dispatcher import scan
        return await scan(adb, now=now, send_sms=stub)

    stats = _run(_apply)
    # Only tenant A (threshold 20) fires. Tenant B (threshold 30) skips.
    fired_tenants = {c["tenant_id"] for c in stub.calls}
    assert ta in fired_tenants
    assert tb not in fired_tenants
    events_a = list(dbc.dispatch_events.find({"tenant_id": ta}))
    events_b = list(dbc.dispatch_events.find({"tenant_id": tb}))
    assert len(events_a) == 1
    assert len(events_b) == 0


# ═════════════════════════════════════════════════════════════════════
# Test 3 — quiet-hours ``deferred`` stamps dedupe.
# ═════════════════════════════════════════════════════════════════════
def test_3_deferred_status_stamps_dedupe_slot(dbc, seeded):
    now = _FIXED_NOW
    ta = _seed_tenant(dbc, seeded)
    tech = _seed_tech(dbc, seeded, ta)
    cust = _seed_customer(dbc, seeded, ta, phone="+15550003333")
    _seed_ping(dbc, seeded, ta, tech["user_id"],
                 lat=33.5, lon=-112.0,
                 captured_at=now - timedelta(minutes=2))
    _far_dest_visit(dbc, seeded, ta, tech["tech_id"], cust,
                     scheduled_start=now - timedelta(minutes=5))

    stub = _SMSStub(status="deferred")

    async def _apply(adb):
        from services.live_dispatcher import scan
        return await scan(adb, now=now, send_sms=stub)

    stats = _run(_apply)
    assert stats["sms_deferred"] == 1
    assert stats["sms_sent"] == 0
    # dispatch_events row exists — deferred consumes the dedupe slot.
    events = list(dbc.dispatch_events.find({"tenant_id": ta}))
    assert len(events) == 1
    assert events[0]["deferred_count"] == 1
    assert cust in events[0]["customers_notified"]


# ═════════════════════════════════════════════════════════════════════
# Test 4 — opt-out ``skipped_opted_out`` stamps dedupe.
# ═════════════════════════════════════════════════════════════════════
def test_4_opted_out_status_stamps_dedupe_slot(dbc, seeded):
    now = _FIXED_NOW
    ta = _seed_tenant(dbc, seeded)
    tech = _seed_tech(dbc, seeded, ta)
    cust = _seed_customer(dbc, seeded, ta, phone="+15550004444")
    _seed_ping(dbc, seeded, ta, tech["user_id"],
                 lat=33.5, lon=-112.0,
                 captured_at=now - timedelta(minutes=2))
    _far_dest_visit(dbc, seeded, ta, tech["tech_id"], cust,
                     scheduled_start=now - timedelta(minutes=5))

    stub = _SMSStub(status="skipped_opted_out")

    async def _apply(adb):
        from services.live_dispatcher import scan
        return await scan(adb, now=now, send_sms=stub)

    stats = _run(_apply)
    assert stats["sms_skipped"] == 1
    assert stats["sms_sent"] == 0
    events = list(dbc.dispatch_events.find({"tenant_id": ta}))
    assert len(events) == 1
    assert events[0]["skipped_count"] == 1
    assert cust in events[0]["customers_notified"]


# ═════════════════════════════════════════════════════════════════════
# Test 5 — dedupe window: 2 back-to-back scans → 1 SMS + 1 event.
# ═════════════════════════════════════════════════════════════════════
def test_5_dedupe_window_prevents_double_send(dbc, seeded):
    now = _FIXED_NOW
    ta = _seed_tenant(dbc, seeded)
    tech = _seed_tech(dbc, seeded, ta)
    cust = _seed_customer(dbc, seeded, ta, phone="+15550005555")
    _seed_ping(dbc, seeded, ta, tech["user_id"],
                 lat=33.5, lon=-112.0,
                 captured_at=now - timedelta(minutes=2))
    _far_dest_visit(dbc, seeded, ta, tech["tech_id"], cust,
                     scheduled_start=now - timedelta(minutes=5))

    stub = _SMSStub(status="sent")

    async def _apply(adb):
        from services.live_dispatcher import scan
        s1 = await scan(adb, now=now, send_sms=stub)
        # 2nd scan 5 min later — still inside 30-min dedupe window.
        s2 = await scan(adb, now=now + timedelta(minutes=5),
                         send_sms=stub)
        return (s1, s2)

    s1, s2 = _run(_apply)
    assert s1["dispatches_fired"] == 1
    assert s2["dispatches_fired"] == 0  # deduped
    assert len(stub.calls) == 1
    assert len(list(dbc.dispatch_events.find({"tenant_id": ta}))) == 1


# ═════════════════════════════════════════════════════════════════════
# Test 6 — N-customer selection: default 3 vs custom 5.
# ═════════════════════════════════════════════════════════════════════
def test_6_n_customer_selection_default_and_custom(dbc, seeded):
    """Same tech has 6 upcoming customers. Default rules → notify
    3; custom rules with count=5 → notify 5."""
    now = _FIXED_NOW

    def _seed_six_customer_route(tenant_id: str):
        tech = _seed_tech(dbc, seeded, tenant_id)
        _seed_ping(dbc, seeded, tenant_id, tech["user_id"],
                     lat=33.5, lon=-112.0,
                     captured_at=now - timedelta(minutes=2))
        # 6 consecutive upcoming customers on same route.
        for i in range(6):
            c = _seed_customer(dbc, seeded, tenant_id,
                                 phone=f"+15551{i:06d}")
            _seed_visit(
                dbc, seeded, tenant_id, tech["tech_id"], c,
                scheduled_start=now
                    - timedelta(minutes=5)  # first is late
                    + timedelta(minutes=30 * i),
                lat=34.5, lng=-112.0,
            )
        return tech

    ta = _seed_tenant(dbc, seeded)  # default count=3
    _seed_six_customer_route(ta)
    tb = _seed_tenant(dbc, seeded, rules={
        "dispatch_delay_threshold_mins": 20,
        "dispatch_sms_customer_count": 5,
        "filter_clean_interval_months": 6,
        "salt_cell_replacement_months": 36,
    })
    _seed_six_customer_route(tb)

    stub = _SMSStub(status="sent")

    async def _apply(adb):
        from services.live_dispatcher import scan
        return await scan(adb, now=now, send_sms=stub)

    _run(_apply)
    calls_a = [c for c in stub.calls if c["tenant_id"] == ta]
    calls_b = [c for c in stub.calls if c["tenant_id"] == tb]
    assert len(calls_a) == 3, f"default count=3 expected, got {len(calls_a)}"
    assert len(calls_b) == 5, f"custom count=5 expected, got {len(calls_b)}"
    events_a = list(dbc.dispatch_events.find({"tenant_id": ta}))
    events_b = list(dbc.dispatch_events.find({"tenant_id": tb}))
    assert len(events_a[0]["customers_notified"]) == 3
    assert len(events_b[0]["customers_notified"]) == 5


# ═════════════════════════════════════════════════════════════════════
# Test 7 — no pings → tech skipped gracefully.
# ═════════════════════════════════════════════════════════════════════
def test_7_no_recent_pings_skips_tech_gracefully(dbc, seeded):
    now = _FIXED_NOW
    ta = _seed_tenant(dbc, seeded)
    tech = _seed_tech(dbc, seeded, ta)
    cust = _seed_customer(dbc, seeded, ta, phone="+15550007777")
    # Stale ping — 30 min old, outside the 10-min freshness window.
    _seed_ping(dbc, seeded, ta, tech["user_id"],
                 lat=33.5, lon=-112.0,
                 captured_at=now - timedelta(minutes=30))
    _far_dest_visit(dbc, seeded, ta, tech["tech_id"], cust,
                     scheduled_start=now - timedelta(minutes=5))

    stub = _SMSStub(status="sent")

    async def _apply(adb):
        from services.live_dispatcher import scan
        return await scan(adb, now=now, send_sms=stub)

    stats = _run(_apply)
    assert stats["techs_evaluated"] == 1
    assert stats["delays_detected"] == 0
    assert stats["dispatches_fired"] == 0
    assert len(stub.calls) == 0
    assert list(dbc.dispatch_events.find({"tenant_id": ta})) == []


# ═════════════════════════════════════════════════════════════════════
# Test 8 — all-failed batch: dedupe NOT stamped (retry next tick).
# ═════════════════════════════════════════════════════════════════════
def test_8_all_failed_leaves_dedupe_window_open(dbc, seeded):
    now = _FIXED_NOW
    ta = _seed_tenant(dbc, seeded)
    tech = _seed_tech(dbc, seeded, ta)
    cust = _seed_customer(dbc, seeded, ta, phone="+15550008888")
    _seed_ping(dbc, seeded, ta, tech["user_id"],
                 lat=33.5, lon=-112.0,
                 captured_at=now - timedelta(minutes=2))
    _far_dest_visit(dbc, seeded, ta, tech["tech_id"], cust,
                     scheduled_start=now - timedelta(minutes=5))

    failed_stub = _SMSStub(status="failed")

    async def _first_scan(adb):
        from services.live_dispatcher import scan
        return await scan(adb, now=now, send_sms=failed_stub)

    stats = _run(_first_scan)
    assert stats["sms_failed"] == 1
    assert stats["dispatches_fired"] == 0
    assert list(dbc.dispatch_events.find({"tenant_id": ta})) == []

    # Second scan — send_sms succeeds this time. Because the
    # failed-only first pass did NOT stamp a dedupe row, the
    # window is still open and this run MUST fire.
    success_stub = _SMSStub(status="sent")

    async def _second_scan(adb):
        from services.live_dispatcher import scan
        return await scan(adb, now=now + timedelta(minutes=5),
                            send_sms=success_stub)

    stats2 = _run(_second_scan)
    assert stats2["dispatches_fired"] == 1
    assert stats2["sms_sent"] == 1
    events = list(dbc.dispatch_events.find({"tenant_id": ta}))
    assert len(events) == 1
    assert events[0]["sent_count"] == 1
    assert events[0]["failed_count"] == 0


# ═════════════════════════════════════════════════════════════════════
# Extra smoke — automation_rules defaults hydration.
# ═════════════════════════════════════════════════════════════════════
def test_scan_uses_ldm_a_defaults_when_rules_missing(dbc, seeded):
    """A tenant that never received the automation_rules_v1 backfill
    still fires — the scan hydrates defaults inline."""
    now = _FIXED_NOW
    ta = _seed_tenant(dbc, seeded)  # no rules field at all
    dbc.tenants.update_one(
        {"id": ta}, {"$unset": {"settings.automation_rules": ""}},
    )
    tech = _seed_tech(dbc, seeded, ta)
    cust = _seed_customer(dbc, seeded, ta, phone="+15550009999")
    _seed_ping(dbc, seeded, ta, tech["user_id"],
                 lat=33.5, lon=-112.0,
                 captured_at=now - timedelta(minutes=2))
    _far_dest_visit(dbc, seeded, ta, tech["tech_id"], cust,
                     scheduled_start=now - timedelta(minutes=5))

    stub = _SMSStub(status="sent")

    async def _apply(adb):
        from services.live_dispatcher import scan
        return await scan(adb, now=now, send_sms=stub)

    stats = _run(_apply)
    assert stats["dispatches_fired"] == 1
    assert len(stub.calls) == 1
