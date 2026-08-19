"""Feb-2026 · Dispatch Board · db.jobs fallback.

Backend tests for the fallback path in ``dispatch_board.get_board``.

Contract:
  * Persisted-order path still wins (dispatch_route_orders row).
  * Customer-denorm path still works (customers geocoded + service_days).
  * When both prior paths yield empty AND ``date`` + ``tech_user_id``
    are supplied → hydrate route_stops from db.jobs.
  * Fallback ordering: route_index asc, scheduled_start asc as
    tiebreaker.
  * Multi-tenant safety.
  * Fallback is read-only (never writes dispatch_route_orders).
  * Backwards compat: caller without ``date`` param gets original
    behavior.
  * Fallback emits ``not_geocoded=true`` on stops whose customer
    lacks service_lat/lng; those stops appear in ``route_stops`` but
    NOT in ``pins``.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import demo_pw

API = "http://localhost:8001/api"

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": demo_pw(email)}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _tenant_of(email: str) -> str:
    return _run(_DB.users.find_one(
        {"email": email}, {"_id": 0, "tenant_id": 1}))["tenant_id"]


DATE = "2026-05-04"        # A Monday.
WEEKDAY = "monday"
TECH_A = f"TESTdb_tech_A_{uuid4().hex[:6]}"
TECH_B = f"TESTdb_tech_B_{uuid4().hex[:6]}"


async def _mkjob(*, tenant_id: str, tech_id: str, cust_id: str,
                  route_index: int | None = None,
                  scheduled_start: str | None = None,
                  title: str = "Fallback pool svc") -> str:
    jid = f"TESTdb_job_{uuid4().hex[:10]}"
    doc = {
        "id": jid, "tenant_id": tenant_id, "customer_id": cust_id,
        "tech_user_id": tech_id, "technician_id": tech_id,
        "title": title, "service_type": "pool_service",
        "scheduled_date": DATE, "status": "scheduled",
    }
    if route_index is not None:
        doc["route_index"] = route_index
    if scheduled_start:
        doc["scheduled_start"] = scheduled_start
    await _DB.jobs.insert_one(doc)
    return jid


async def _mkcust(*, tenant_id: str, name: str,
                    lat: float | None = None, lng: float | None = None,
                    service_days: list[str] | None = None,
                    assigned: list[str] | None = None) -> str:
    cid = f"TESTdb_cust_{uuid4().hex[:8]}"
    doc = {"id": cid, "tenant_id": tenant_id, "name": name,
           "service_address": f"{name} street"}
    if lat is not None:
        doc["service_lat"] = lat
        doc["service_lng"] = lng
    if service_days:
        doc["service_days"] = service_days
    if assigned:
        doc["assigned_tech_ids"] = assigned
    await _DB.customers.insert_one(doc)
    return cid


async def _wipe():
    await _DB.jobs.delete_many({"id": {"$regex": "^TESTdb_"}})
    await _DB.customers.delete_many({"id": {"$regex": "^TESTdb_"}})
    await _DB.dispatch_route_orders.delete_many(
        {"tech_user_id": {"$regex": "^TESTdb_"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


def _get_board(tok: str, **params) -> dict:
    r = requests.get(f"{API}/dispatch/board",
                     headers={"Authorization": f"Bearer {tok}"},
                     params=params, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# ═══════════════════════════════════════════════════════════════════════
# 1. Persisted-order path still wins.
# ═══════════════════════════════════════════════════════════════════════
def test_persisted_route_order_wins_over_jobs_fallback():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    # Two customers, both geocoded + assigned to TECH_A on Monday.
    c1 = _run(_mkcust(tenant_id=tenant_id, name="TESTdb Alice",
                      lat=33.7, lng=-112.2, service_days=[WEEKDAY],
                      assigned=[TECH_A]))
    c2 = _run(_mkcust(tenant_id=tenant_id, name="TESTdb Bob",
                      lat=33.71, lng=-112.21, service_days=[WEEKDAY],
                      assigned=[TECH_A]))
    # Persisted order — reverse.
    _run(_DB.dispatch_route_orders.insert_one({
        "tenant_id": tenant_id, "day": WEEKDAY, "tech_user_id": TECH_A,
        "ordered_customer_ids": [c2, c1],
        "source": "unit_test",
    }))
    # Also seed jobs (would trigger fallback if the top path failed).
    _run(_mkjob(tenant_id=tenant_id, tech_id=TECH_A, cust_id=c1,
                route_index=0))
    d = _get_board(tok, day=WEEKDAY, tech_user_id=TECH_A, date=DATE)
    ids = [s.get("customer_id") for s in d["route_stops"]]
    assert ids == [c2, c1], f"persisted order lost: {ids}"
    assert d["source"] == "denorm"


# ═══════════════════════════════════════════════════════════════════════
# 2. Customer-denorm path still works.
# ═══════════════════════════════════════════════════════════════════════
def test_customer_denorm_path_still_works_without_jobs():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    c1 = _run(_mkcust(tenant_id=tenant_id, name="TESTdb Carol",
                      lat=33.75, lng=-112.25, service_days=[WEEKDAY],
                      assigned=[TECH_A]))
    d = _get_board(tok, day=WEEKDAY, tech_user_id=TECH_A, date=DATE)
    ids = [s.get("customer_id") for s in d["route_stops"]]
    assert c1 in ids, f"denorm path missing customer: {ids}"
    assert d["source"] == "denorm"


# ═══════════════════════════════════════════════════════════════════════
# 3. Fallback path — jobs exist, no denorm, no dispatch_route_orders.
# ═══════════════════════════════════════════════════════════════════════
def test_jobs_fallback_triggers_and_orders_by_route_index():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    # Customer WITHOUT service_days / assigned_tech_ids — so denorm
    # path yields empty for this (tenant, day, tech).
    c1 = _run(_mkcust(tenant_id=tenant_id, name="TESTdb Diego",
                      lat=33.8, lng=-112.3))
    c2 = _run(_mkcust(tenant_id=tenant_id, name="TESTdb Erin",
                      lat=33.81, lng=-112.31))
    # Jobs on the date. c2 has lower route_index → must come first.
    _run(_mkjob(tenant_id=tenant_id, tech_id=TECH_A, cust_id=c1,
                route_index=1))
    _run(_mkjob(tenant_id=tenant_id, tech_id=TECH_A, cust_id=c2,
                route_index=0))
    d = _get_board(tok, day=WEEKDAY, tech_user_id=TECH_A, date=DATE)
    ids = [s.get("customer_id") for s in d["route_stops"]]
    assert ids == [c2, c1], f"fallback order wrong: {ids}"
    assert d["source"] == "jobs_fallback"


# ═══════════════════════════════════════════════════════════════════════
# 4. Fallback tiebreak — equal route_index → scheduled_start.
# ═══════════════════════════════════════════════════════════════════════
def test_jobs_fallback_tiebreak_by_scheduled_start():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    c1 = _run(_mkcust(tenant_id=tenant_id, name="TESTdb Faye",
                      lat=33.9, lng=-112.4))
    c2 = _run(_mkcust(tenant_id=tenant_id, name="TESTdb Gio",
                      lat=33.91, lng=-112.41))
    # Same route_index, different scheduled_start.
    _run(_mkjob(tenant_id=tenant_id, tech_id=TECH_A, cust_id=c1,
                route_index=5, scheduled_start=f"{DATE}T14:00:00"))
    _run(_mkjob(tenant_id=tenant_id, tech_id=TECH_A, cust_id=c2,
                route_index=5, scheduled_start=f"{DATE}T09:00:00"))
    d = _get_board(tok, day=WEEKDAY, tech_user_id=TECH_A, date=DATE)
    ids = [s.get("customer_id") for s in d["route_stops"]]
    assert ids == [c2, c1], f"tiebreak failed: {ids}"


# ═══════════════════════════════════════════════════════════════════════
# 5. Fallback is tenant-scoped.
# ═══════════════════════════════════════════════════════════════════════
def test_jobs_fallback_respects_tenant_isolation():
    tok = _login("super@aquaterra.com")
    tenant_a = _tenant_of("super@aquaterra.com")
    tenant_b = "other-tenant-should-not-bleed"
    c_a = _run(_mkcust(tenant_id=tenant_a, name="TESTdb TenantA",
                        lat=34.0, lng=-112.5))
    c_b = _run(_mkcust(tenant_id=tenant_b, name="TESTdb TenantB",
                        lat=34.01, lng=-112.51))
    _run(_mkjob(tenant_id=tenant_a, tech_id=TECH_A, cust_id=c_a,
                route_index=0))
    _run(_mkjob(tenant_id=tenant_b, tech_id=TECH_A, cust_id=c_b,
                route_index=0))
    d = _get_board(tok, day=WEEKDAY, tech_user_id=TECH_A, date=DATE)
    ids = [s.get("customer_id") for s in d["route_stops"]]
    assert c_a in ids
    assert c_b not in ids, f"tenant B bled into A: {ids}"


# ═══════════════════════════════════════════════════════════════════════
# 6. Fallback + not_geocoded chip.
# ═══════════════════════════════════════════════════════════════════════
def test_jobs_fallback_marks_not_geocoded_and_omits_from_pins():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    c_geo = _run(_mkcust(tenant_id=tenant_id, name="TESTdb GEO",
                          lat=34.1, lng=-112.6))
    c_no = _run(_mkcust(tenant_id=tenant_id, name="TESTdb NOGEO"))
    _run(_mkjob(tenant_id=tenant_id, tech_id=TECH_A, cust_id=c_geo,
                route_index=0))
    _run(_mkjob(tenant_id=tenant_id, tech_id=TECH_A, cust_id=c_no,
                route_index=1))
    d = _get_board(tok, day=WEEKDAY, tech_user_id=TECH_A, date=DATE)
    ids = [s.get("customer_id") for s in d["route_stops"]]
    assert c_geo in ids and c_no in ids
    no_row = next(s for s in d["route_stops"] if s["customer_id"] == c_no)
    geo_row = next(s for s in d["route_stops"] if s["customer_id"] == c_geo)
    assert no_row["not_geocoded"] is True
    assert geo_row["not_geocoded"] is False
    pin_ids = {p["customer_id"] for p in d["pins"]}
    assert c_geo in pin_ids
    assert c_no not in pin_ids, "not-geocoded pin leaked onto map"


# ═══════════════════════════════════════════════════════════════════════
# 7. Fallback is read-only — no dispatch_route_orders write.
# ═══════════════════════════════════════════════════════════════════════
def test_jobs_fallback_is_read_only():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    c1 = _run(_mkcust(tenant_id=tenant_id, name="TESTdb ReadOnly",
                      lat=34.2, lng=-112.7))
    _run(_mkjob(tenant_id=tenant_id, tech_id=TECH_A, cust_id=c1,
                route_index=0))
    _get_board(tok, day=WEEKDAY, tech_user_id=TECH_A, date=DATE)
    dro = _run(_DB.dispatch_route_orders.find_one(
        {"tenant_id": tenant_id, "day": WEEKDAY, "tech_user_id": TECH_A}))
    assert dro is None, f"fallback wrote to dispatch_route_orders: {dro}"


# ═══════════════════════════════════════════════════════════════════════
# 8. Backwards compat — no date param → original behavior.
# ═══════════════════════════════════════════════════════════════════════
def test_backwards_compat_no_date_param():
    tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    c1 = _run(_mkcust(tenant_id=tenant_id, name="TESTdb NoDate",
                      lat=34.3, lng=-112.8))
    _run(_mkjob(tenant_id=tenant_id, tech_id=TECH_A, cust_id=c1,
                route_index=0))
    # No `date` → fallback must NOT trigger. Denorm path also empty.
    d = _get_board(tok, day=WEEKDAY, tech_user_id=TECH_A)
    assert d["route_stops"] == []
    assert d["source"] == "denorm"
