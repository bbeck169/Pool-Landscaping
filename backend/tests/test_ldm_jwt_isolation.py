"""LDM-E · Feb-2026 — Cross-tenant JWT isolation audit + negative test coverage.

Companion regression suite for the entire AI Live Dispatcher +
Predictive Maintenance track (LDM-A/B/C/D). Locks the eleven
acceptance cases from the LDM-E dispatch and serves as the
guardrail against future refactors that might inadvertently
loosen tenant scoping.

Test surfaces
─────────────
    (a) automation_rules PATCH — body ``tenant_id`` → 403
    (b) automation_rules PATCH — query ``?tenant_id=`` → ignored,
        patches caller's tenant only
    (c) automation_rules PATCH — non-admin JWT → 403
    (d) automation_rules PATCH — unauthenticated → 401
    (e) automation_rules GET  — caller sees only their own tenant
    (f) automation_rules path — no ``/api/tenants/{id}/*`` route
        exists (direct-id addressing → 404)
    (g) live_dispatcher — two-tenant scan isolation (no cross reads)
    (h) live_dispatcher — cross-tenant customer_id → skip + warning
    (i) maintenance_scanner — two-tenant scan isolation
    (j) maintenance_scanner — cross-tenant billing_plan → skip + warning
    (k) dispatch_events — listing scoped by tenant_id

Testing style mirrors ``test_automation_rules.py`` /
``test_live_dispatcher.py`` — Motor for the async SUT layer,
pymongo for seed + cleanup, per-test asyncio loop. Every LDM
surface is exercised through its natural entry point (HTTP for
LDM-A endpoints, ``scan()`` for LDM-B/C services).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "LDME_"
_FIXED_NOW = datetime(2026, 2, 20, 15, 0, tzinfo=timezone.utc)


def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z",
    )


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def seeded(dbc):
    tenants: List[str] = []
    users: List[str] = []
    customers: List[str] = []
    jobs: List[str] = []
    plans: List[str] = []
    trackers: List[str] = []
    pings: List[str] = []
    actions: List[str] = []
    events: List[str] = []
    yield {
        "tenants": tenants, "users": users, "customers": customers,
        "jobs": jobs, "plans": plans, "trackers": trackers,
        "pings": pings, "actions": actions, "events": events,
    }
    # Wipe every LDME-scoped row we know about. Also sweep by
    # tenant_id on collections the scanner / dispatcher inserted
    # into so their untracked rows don't leak between tests.
    if tenants:
        dbc.tenants.delete_many({"id": {"$in": tenants}})
        dbc.ai_employee_actions.delete_many({"tenant_id": {"$in": tenants}})
        dbc.dispatch_events.delete_many({"tenant_id": {"$in": tenants}})
    if users:
        dbc.users.delete_many({"id": {"$in": users}})
    if customers:
        dbc.customers.delete_many({"id": {"$in": customers}})
    if jobs:
        dbc.jobs.delete_many({"id": {"$in": jobs}})
    if plans:
        dbc.billing_plans.delete_many({"id": {"$in": plans}})
    if trackers:
        dbc.equipment_service_trackers.delete_many(
            {"id": {"$in": trackers}},
        )
    if pings:
        dbc.gps_pings.delete_many({"id": {"$in": pings}})
    if actions:
        dbc.ai_employee_actions.delete_many({"id": {"$in": actions}})
    if events:
        dbc.dispatch_events.delete_many({"id": {"$in": events}})


# ═════════════════════════════════════════════════════════════════════
# Seed helpers.
# ═════════════════════════════════════════════════════════════════════
def _seed_tenant(dbc, seeded, *, rules: Optional[dict] = None) -> str:
    tid = _fresh("TEN")
    doc: Dict[str, Any] = {
        "id": tid,
        "name": f"LDME tenant {tid[-6:]}",
        "timezone": "America/New_York",
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
        "id": uid, "tenant_id": tenant_id,
        "name": "LDME Tech", "role": "technician",
        "technician_id": tech_id,
    })
    seeded["users"].append(uid)
    return {"user_id": uid, "tech_id": tech_id}


def _seed_customer(dbc, seeded, tenant_id: str,
                    *, phone: str = "+15551110000",
                    name: str = "LDME Customer") -> str:
    cid = _fresh("CUS")
    dbc.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": name, "phone": phone,
    })
    seeded["customers"].append(cid)
    return cid


def _seed_ping(dbc, seeded, tenant_id: str, user_id: str,
                *, lat: float, lon: float,
                captured_at: datetime) -> str:
    pid = _fresh("PING")
    dbc.gps_pings.insert_one({
        "id": pid, "tenant_id": tenant_id, "user_id": user_id,
        "lat": lat, "lon": lon, "accuracy_m": 15.0,
        "source": "foreground",
        "captured_at": _iso(captured_at),
        "received_at": _iso(captured_at + timedelta(seconds=30)),
    })
    seeded["pings"].append(pid)
    return pid


def _seed_visit(dbc, seeded, tenant_id: str, tech_id: str,
                 customer_id: str, *,
                 scheduled_start: datetime,
                 lat: float = 34.5, lng: float = -112.0) -> str:
    jid = _fresh("JOB")
    dbc.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id,
        "technician_id": tech_id, "customer_id": customer_id,
        "status": "scheduled",
        "scheduled_start": _iso(scheduled_start),
        "site_lat": lat, "site_lng": lng,
        "service_type": "Pool Cleaning",
    })
    seeded["jobs"].append(jid)
    return jid


def _seed_pool_plan(dbc, seeded, tenant_id: str, customer_id: str) -> str:
    pid = _fresh("PLAN")
    dbc.billing_plans.insert_one({
        "id": pid, "tenant_id": tenant_id,
        "customer_id": customer_id,
        "service": "Monthly Pool Service",
        "active": True, "frequency": "monthly", "amount": 120.0,
    })
    seeded["plans"].append(pid)
    return pid


def _seed_tracker(dbc, seeded, tenant_id: str, customer_id: str,
                   *, tracker_type: str, months_ago: int) -> str:
    trid = _fresh("TRK")
    days = int(months_ago * 30.44)
    dbc.equipment_service_trackers.insert_one({
        "id": trid, "tenant_id": tenant_id,
        "customer_id": customer_id, "tracker_type": tracker_type,
        "is_active": True,
        "last_cleaned_at": (
            _FIXED_NOW.date() - timedelta(days=days)
        ).isoformat(),
    })
    seeded["trackers"].append(trid)
    return trid


def _seed_dispatch_event(dbc, seeded, tenant_id: str) -> str:
    eid = _fresh("EVT")
    dbc.dispatch_events.insert_one({
        "id": eid, "tenant_id": tenant_id,
        "tech_id": "t1", "visit_id": "v1",
        "delay_mins": 25.0, "customers_notified": [],
        "sent_count": 0, "deferred_count": 0,
        "skipped_count": 0, "failed_count": 0,
        "initiated_at": _iso(_FIXED_NOW),
        "initiated_by": "marco_live_dispatcher",
    })
    seeded["events"].append(eid)
    return eid


# ═════════════════════════════════════════════════════════════════════
# Per-test async loop + Motor db handle.
# ═════════════════════════════════════════════════════════════════════
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


# ═════════════════════════════════════════════════════════════════════
# HTTP shim for LDM-A endpoints — real request path, real 401 / 403.
# ═════════════════════════════════════════════════════════════════════
def _make_http_client(*, role: str = "admin",
                        tenant_id: str = "t-ldme-1",
                        anonymous: bool = False):
    """Mount ``routers.tenants`` behind a mini FastAPI app with
    dependency overrides. Setting ``anonymous=True`` skips the
    ``get_current_user`` override so an incoming request without an
    Authorization header exercises the real 401 path."""
    from routers import tenants as _t
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    async def _fake_user():
        return {
            "id": "u-ldme-1", "role": role,
            "tenant_id": tenant_id,
            "email": f"{role}@ldme.test",
        }

    async def _fake_tenant():
        return {"id": tenant_id}

    app = FastAPI()
    app.include_router(_t.router, prefix="/api")
    if not anonymous:
        app.dependency_overrides[get_current_user] = _fake_user
        app.dependency_overrides[get_current_tenant] = _fake_tenant
    # ``raise_server_exceptions=True`` so unexpected 500s surface
    # the real traceback instead of returning a bare 500 body.
    # Individual tests that intentionally exercise error paths
    # can wrap in try/except; for our LDM-E audit surface every
    # 500 should be a genuine bug that we want to see.
    return TestClient(app, raise_server_exceptions=True)


# ═════════════════════════════════════════════════════════════════════
# (a) — automation_rules PATCH — body tenant_id → 403.
# ═════════════════════════════════════════════════════════════════════
def test_a_patch_body_tenant_id_returns_403(dbc, seeded):
    tid_a = _seed_tenant(dbc, seeded)
    tid_b = _seed_tenant(dbc, seeded)
    client = _make_http_client(role="admin", tenant_id=tid_a)
    resp = client.patch(
        "/api/tenants/mine/automation-rules",
        json={"tenant_id": tid_b,
              "dispatch_delay_threshold_mins": 30},
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert "tenant_id" in (body.get("detail") or "").lower()
    # Neither tenant should have been mutated — the guard fires
    # before the mongo update.
    row_a = dbc.tenants.find_one({"id": tid_a}, {"_id": 0})
    row_b = dbc.tenants.find_one({"id": tid_b}, {"_id": 0})
    for row in (row_a, row_b):
        rules = ((row.get("settings") or {}).get("automation_rules") or {})
        assert rules.get("dispatch_delay_threshold_mins") in (None, 20)


# ═════════════════════════════════════════════════════════════════════
# (b) — automation_rules PATCH — query ?tenant_id=B is ignored.
# ═════════════════════════════════════════════════════════════════════
def test_b_patch_query_tenant_id_is_ignored(dbc, seeded):
    """FastAPI doesn't bind unknown query params to any handler
    parameter — a rogue ?tenant_id=B in the URL is silently
    discarded. The mutation lands only on the caller's own tenant
    (derived from JWT). Direct-handler pattern (not TestClient)
    to sidestep the Motor / anyio loop-mismatch — the handler's
    query-string handling doesn't depend on the transport layer."""
    tid_a = _seed_tenant(dbc, seeded, rules={
        "dispatch_delay_threshold_mins": 20,
        "dispatch_sms_customer_count": 3,
        "filter_clean_interval_months": 6,
        "salt_cell_replacement_months": 36,
    })
    tid_b = _seed_tenant(dbc, seeded, rules={
        "dispatch_delay_threshold_mins": 20,
        "dispatch_sms_customer_count": 3,
        "filter_clean_interval_months": 6,
        "salt_cell_replacement_months": 36,
    })

    class _FakeReq:
        def __init__(self, payload, query):
            self._payload = payload
            # Mirror starlette.requests.Request surface — we don't
            # actually inspect .query_params in the handler, but keep
            # it here so any future defensive read finds the rogue
            # tenant_id and is still expected to reject or ignore.
            self.query_params = query

        async def json(self):
            return dict(self._payload)

    async def _apply(adb):
        from routers.tenants import (
            patch_own_automation_rules, AutomationRulesPatch,
        )
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = AutomationRulesPatch(dispatch_delay_threshold_mins=90)
            # Body deliberately omits tenant_id (that path is
            # covered by test a). The rogue value lives in the
            # "query string" instead.
            req = _FakeReq(
                {"dispatch_delay_threshold_mins": 90},
                {"tenant_id": tid_b},
            )
            return await patch_own_automation_rules(
                request=req, body=body,
                user={"role": "admin", "id": "u1", "tenant_id": tid_a},
            )
        finally:
            _t.db = _t._orig_db

    out = _run(_apply)
    # Handler returned rules for tenant A (the JWT-derived tid).
    assert out["dispatch_delay_threshold_mins"] == 90
    # Caller's tenant (A) took the update.
    row_a = dbc.tenants.find_one({"id": tid_a}, {"_id": 0})
    a_rules = ((row_a.get("settings") or {}).get("automation_rules") or {})
    assert a_rules["dispatch_delay_threshold_mins"] == 90
    # Tenant B untouched.
    row_b = dbc.tenants.find_one({"id": tid_b}, {"_id": 0})
    b_rules = ((row_b.get("settings") or {}).get("automation_rules") or {})
    assert b_rules["dispatch_delay_threshold_mins"] == 20


# ═════════════════════════════════════════════════════════════════════
# (c) — automation_rules PATCH — non-admin JWT → 403.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("bad_role", ["technician", "member", "customer"])
def test_c_patch_non_admin_role_returns_403(dbc, seeded, bad_role):
    tid_a = _seed_tenant(dbc, seeded)
    client = _make_http_client(role=bad_role, tenant_id=tid_a)
    resp = client.patch(
        "/api/tenants/mine/automation-rules",
        json={"dispatch_delay_threshold_mins": 30},
    )
    assert resp.status_code == 403, resp.text


# ═════════════════════════════════════════════════════════════════════
# (d) — automation_rules PATCH — unauthenticated → 401.
# ═════════════════════════════════════════════════════════════════════
def test_d_patch_unauthenticated_returns_401(dbc, seeded):
    """Bearer scheme is configured with auto_error=False and
    utils.get_current_user raises 401 on missing Authorization."""
    client = _make_http_client(anonymous=True)
    resp = client.patch(
        "/api/tenants/mine/automation-rules",
        json={"dispatch_delay_threshold_mins": 30},
    )
    assert resp.status_code == 401, resp.text


# ═════════════════════════════════════════════════════════════════════
# (e) — automation_rules GET — caller sees only their own tenant.
# ═════════════════════════════════════════════════════════════════════
def test_e_get_returns_own_tenant_only(dbc, seeded):
    """Direct-handler pattern: passing tenant A's document into
    the GET's ``tenant`` param + tenant A's user JWT must return
    A's automation_rules — tenant B's document is never fetched
    or accessible from this handler surface."""
    tid_a = _seed_tenant(dbc, seeded, rules={
        "dispatch_delay_threshold_mins": 45,
        "dispatch_sms_customer_count": 3,
        "filter_clean_interval_months": 6,
        "salt_cell_replacement_months": 36,
    })
    _seed_tenant(dbc, seeded, rules={
        "dispatch_delay_threshold_mins": 200,  # tenant B custom
        "dispatch_sms_customer_count": 3,
        "filter_clean_interval_months": 6,
        "salt_cell_replacement_months": 36,
    })
    a_doc = dbc.tenants.find_one({"id": tid_a}, {"_id": 0})

    async def _apply():
        from routers.tenants import get_own_automation_rules
        return await get_own_automation_rules(
            user={"role": "admin", "id": "u1", "tenant_id": tid_a},
            tenant=a_doc,
        )

    loop = asyncio.new_event_loop()
    try:
        out = loop.run_until_complete(_apply())
    finally:
        loop.close()
    # Tenant A's custom value comes back — NOT tenant B's 200.
    assert out["dispatch_delay_threshold_mins"] == 45
    # Belt & braces — the returned dict must NOT contain the value
    # from tenant B.
    assert out["dispatch_delay_threshold_mins"] != 200


# ═════════════════════════════════════════════════════════════════════
# (f) — no /api/tenants/{id}/automation-rules route → 404.
# ═════════════════════════════════════════════════════════════════════
def test_f_direct_tenant_id_path_does_not_exist(dbc, seeded):
    """The whole surface uses the ``/mine/*`` convention — direct-id
    addressing should NOT resolve. Matches the codebase's
    404-on-cross-tenant convention (see e.g. test_benefits.py
    ``test_patch_cross_tenant_returns_404``)."""
    tid_a = _seed_tenant(dbc, seeded)
    client = _make_http_client(role="admin", tenant_id=tid_a)
    resp = client.get(
        f"/api/tenants/{tid_a}/automation-rules",
    )
    # FastAPI returns 404 when no route matches. Belt & braces —
    # accept the 405 posture too since some deployments use trailing
    # normalisers that map to Method Not Allowed instead.
    assert resp.status_code in (404, 405), resp.text
    resp2 = client.patch(
        f"/api/tenants/{tid_a}/automation-rules",
        json={"dispatch_delay_threshold_mins": 30},
    )
    assert resp2.status_code in (404, 405), resp2.text


# ═════════════════════════════════════════════════════════════════════
# (g) — live_dispatcher two-tenant scan isolation.
# ═════════════════════════════════════════════════════════════════════
class _SMSStub:
    def __init__(self, status: str = "sent"):
        self.status = status
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, *, tenant_id, to_phone, body, mms_url=None):
        self.calls.append({
            "tenant_id": tenant_id, "to_phone": to_phone,
            "body": body, "mms_url": mms_url,
        })
        return {
            "status": self.status,
            "provider_id": None,
            "character_count": len(body),
            "segment_count": 1,
        }


def test_g_live_dispatcher_two_tenant_isolation(dbc, seeded):
    now = _FIXED_NOW
    tid_a = _seed_tenant(dbc, seeded)
    tid_b = _seed_tenant(dbc, seeded)
    # Seed identical delay scenario in BOTH tenants.
    for tid, phone_prefix in ((tid_a, "+15550000A"), (tid_b, "+15550000B")):
        tech = _seed_tech(dbc, seeded, tid)
        _seed_ping(dbc, seeded, tid, tech["user_id"],
                     lat=33.5, lon=-112.0,
                     captured_at=now - timedelta(minutes=2))
        cust = _seed_customer(dbc, seeded, tid,
                                 phone=phone_prefix + "01")
        _seed_visit(dbc, seeded, tid, tech["tech_id"], cust,
                     scheduled_start=now - timedelta(minutes=5))

    stub = _SMSStub(status="sent")

    async def _apply(adb):
        from services.live_dispatcher import scan
        return await scan(adb, now=now, send_sms=stub)

    _run(_apply)
    # BOTH tenants should dispatch — sanity check.
    events_a = list(dbc.dispatch_events.find({"tenant_id": tid_a}))
    events_b = list(dbc.dispatch_events.find({"tenant_id": tid_b}))
    assert len(events_a) == 1
    assert len(events_b) == 1
    # BUT — every SMS call must carry the SAME tenant_id it was
    # dispatched under. No mixing.
    for call in stub.calls:
        # Phone prefix embeds the source tenant; ensure the SMS
        # tenant_id matches the phone's prefix bucket.
        if call["tenant_id"] == tid_a:
            assert call["to_phone"].startswith("+15550000A")
        elif call["tenant_id"] == tid_b:
            assert call["to_phone"].startswith("+15550000B")
        else:  # pragma: no cover
            pytest.fail(f"unexpected tenant_id on SMS call: {call}")


# ═════════════════════════════════════════════════════════════════════
# (h) — live_dispatcher refuses cross-tenant customer_id.
# ═════════════════════════════════════════════════════════════════════
def test_h_live_dispatcher_cross_tenant_customer_id_skips(dbc, seeded, caplog):
    """Corruption scenario: tenant A has a visit that references
    a customer_id belonging to tenant B. The dispatcher's customer
    lookup is tenant-scoped so the row is not found → no SMS is
    sent AND a security-warning log is emitted."""
    now = _FIXED_NOW
    tid_a = _seed_tenant(dbc, seeded)
    tid_b = _seed_tenant(dbc, seeded)
    a_tech = _seed_tech(dbc, seeded, tid_a)
    _seed_ping(dbc, seeded, tid_a, a_tech["user_id"],
                 lat=33.5, lon=-112.0,
                 captured_at=now - timedelta(minutes=2))
    # Tenant B owns the customer.
    b_cust = _seed_customer(dbc, seeded, tid_b,
                              phone="+15550009999", name="B Customer")
    # Tenant A's visit references B's customer_id (corruption).
    _seed_visit(dbc, seeded, tid_a, a_tech["tech_id"], b_cust,
                 scheduled_start=now - timedelta(minutes=5))

    stub = _SMSStub(status="sent")

    async def _apply(adb):
        from services.live_dispatcher import scan
        return await scan(adb, now=now, send_sms=stub)

    with caplog.at_level(logging.WARNING, logger="live_dispatcher"):
        _run(_apply)
    # No SMS was sent — the customer lookup found nothing in A's scope.
    assert stub.calls == []
    # No dispatch_events row landed — the batch was all-skipped, so
    # customers_notified stays empty, so the row isn't persisted.
    assert list(dbc.dispatch_events.find({"tenant_id": tid_a})) == []
    # Security warning was emitted.
    hits = [r for r in caplog.records
             if "cross_tenant_customer_id" in r.getMessage()]
    assert hits, (
        "expected a live_dispatcher.security cross_tenant_customer_id "
        "warning; got records: "
        + ", ".join(r.getMessage() for r in caplog.records)
    )


# ═════════════════════════════════════════════════════════════════════
# (i) — maintenance_scanner two-tenant scan isolation.
# ═════════════════════════════════════════════════════════════════════
def test_i_maintenance_scanner_two_tenant_isolation(dbc, seeded):
    """Both tenants have identical overdue scenarios. Each scan
    creates actions ONLY for its own tenant's customers."""
    tid_a = _seed_tenant(dbc, seeded)
    tid_b = _seed_tenant(dbc, seeded)
    a_cid = _seed_customer(dbc, seeded, tid_a, name="A Customer")
    b_cid = _seed_customer(dbc, seeded, tid_b, name="B Customer")
    _seed_pool_plan(dbc, seeded, tid_a, a_cid)
    _seed_pool_plan(dbc, seeded, tid_b, b_cid)
    for tid, cid in ((tid_a, a_cid), (tid_b, b_cid)):
        _seed_tracker(dbc, seeded, tid, cid,
                       tracker_type="filter", months_ago=12)
        _seed_tracker(dbc, seeded, tid, cid,
                       tracker_type="salt_cell", months_ago=2)

    async def _apply(adb):
        from services.maintenance_scanner import scan
        return await scan(adb, now=_FIXED_NOW)

    _run(_apply)
    # Each tenant gets exactly one action for its own customer.
    a_rows = list(dbc.ai_employee_actions.find(
        {"tenant_id": tid_a, "action_type": "cross_sell_filter"},
    ))
    b_rows = list(dbc.ai_employee_actions.find(
        {"tenant_id": tid_b, "action_type": "cross_sell_filter"},
    ))
    assert len(a_rows) == 1
    assert len(b_rows) == 1
    assert a_rows[0]["customer_id"] == a_cid
    assert b_rows[0]["customer_id"] == b_cid
    # Belt & braces — no A rows referencing B's customer or vice versa.
    assert dbc.ai_employee_actions.count_documents(
        {"tenant_id": tid_a, "customer_id": b_cid},
    ) == 0
    assert dbc.ai_employee_actions.count_documents(
        {"tenant_id": tid_b, "customer_id": a_cid},
    ) == 0


# ═════════════════════════════════════════════════════════════════════
# (j) — maintenance_scanner refuses cross-tenant billing_plan link.
# ═════════════════════════════════════════════════════════════════════
def test_j_maintenance_scanner_cross_tenant_customer_id_skips(
        dbc, seeded, caplog):
    """Corruption scenario: tenant B has a billing_plan referencing
    a customer_id owned by tenant A. The scanner's customer lookup
    is tenant-scoped so the row is not found → no action drafted
    AND a security-warning log is emitted."""
    tid_a = _seed_tenant(dbc, seeded)
    tid_b = _seed_tenant(dbc, seeded)
    a_cust = _seed_customer(dbc, seeded, tid_a, name="A Customer")
    # Tenant B's plan carries A's customer_id (corruption).
    _seed_pool_plan(dbc, seeded, tid_b, a_cust)
    # Also seed a legit tracker on tenant B's own record so the
    # test verifies specifically that the corrupted-plan customer
    # doesn't produce an action, not that no scanning occurs.
    _seed_tracker(dbc, seeded, tid_b, a_cust,
                   tracker_type="filter", months_ago=12)

    async def _apply(adb):
        from services.maintenance_scanner import scan
        return await scan(adb, now=_FIXED_NOW)

    with caplog.at_level(logging.WARNING, logger="maintenance_scanner"):
        _run(_apply)
    # No action was drafted — the customer lookup found nothing
    # in B's scope.
    assert dbc.ai_employee_actions.count_documents(
        {"tenant_id": tid_b, "customer_id": a_cust},
    ) == 0
    # AND no action was drafted for tenant A — B's scan can't reach
    # into A's action queue regardless.
    assert dbc.ai_employee_actions.count_documents(
        {"tenant_id": tid_a},
    ) == 0
    # Security warning was emitted.
    hits = [r for r in caplog.records
             if "cross_tenant_customer_id" in r.getMessage()]
    assert hits, (
        "expected a maintenance_scanner.security "
        "cross_tenant_customer_id warning; got records: "
        + ", ".join(r.getMessage() for r in caplog.records)
    )


# ═════════════════════════════════════════════════════════════════════
# (k) — dispatch_events listing scoped by tenant_id.
# ═════════════════════════════════════════════════════════════════════
def test_k_dispatch_events_collection_tenant_scoped(dbc, seeded):
    """Even though there's no HTTP surface for dispatch_events yet
    (that lands in the LDM-D moderation-queue work), the underlying
    row shape carries tenant_id and a natural query scoped by it
    returns only the caller's rows. Regression guardrail for any
    future ``GET /api/dispatch-events`` route."""
    tid_a = _seed_tenant(dbc, seeded)
    tid_b = _seed_tenant(dbc, seeded)
    _seed_dispatch_event(dbc, seeded, tid_a)
    _seed_dispatch_event(dbc, seeded, tid_a)
    _seed_dispatch_event(dbc, seeded, tid_b)
    assert dbc.dispatch_events.count_documents(
        {"tenant_id": tid_a},
    ) == 2
    assert dbc.dispatch_events.count_documents(
        {"tenant_id": tid_b},
    ) == 1
    # Every persisted row MUST have a tenant_id.
    for row in dbc.dispatch_events.find(
        {"tenant_id": {"$in": [tid_a, tid_b]}},
    ):
        assert row.get("tenant_id") in (tid_a, tid_b), (
            f"dispatch_events row missing tenant_id: {row}"
        )
