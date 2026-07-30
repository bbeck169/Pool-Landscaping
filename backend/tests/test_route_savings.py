"""Phase 10 · sub-item F — Weekly route-savings KPI."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"

_LOOP = asyncio.new_event_loop(); asyncio.set_event_loop(_LOOP)
from services import route_events as _rev  # noqa: E402
_FRESH = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_rev.db = _FRESH[_ENV["DB_NAME"]]


def _run(c):
    try: asyncio.set_event_loop(_LOOP)
    except Exception: pass
    return _LOOP.run_until_complete(c)


def _login(email):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=10)
    return r.json()["access_token"]


def _tid():
    return _sync.users.find_one({"email": "manager@aquaterra.com"})["tenant_id"]


# ── 1. Aggregation math — 7d and 30d ranges ───────────────────────
def test_aggregation_7d_and_30d_ranges():
    tid = f"tenant_p10f_{uuid.uuid4().hex[:6]}"
    _sync.route_optimize_events.delete_many({"tenant_id": tid})
    now = datetime.now(timezone.utc)
    def _at(days_ago):
        return (now - timedelta(days=days_ago)).replace(hour=10).isoformat()
    _sync.route_optimize_events.insert_many([
        {"tenant_id": tid, "event_id": "e1", "kind": "optimize",
          "tech_user_id": "tA", "route_date": "2026-07-29",
          "savings_km": 3.5, "stop_count": 4, "executed_at": _at(1)},
        {"tenant_id": tid, "event_id": "e2", "kind": "optimize",
          "tech_user_id": "tA", "route_date": "2026-07-28",
          "savings_km": 2.0, "stop_count": 3, "executed_at": _at(2)},
        {"tenant_id": tid, "event_id": "e3", "kind": "insert",
          "tech_user_id": "tB", "route_date": "2026-07-27",
          "savings_km": 0.0, "added_distance_km": 1.5,
          "stop_count": 2, "executed_at": _at(3)},
        {"tenant_id": tid, "event_id": "e4", "kind": "optimize",
          "tech_user_id": "tB", "route_date": "2026-07-01",
          "savings_km": 7.7, "stop_count": 5, "executed_at": _at(20)},
    ])
    r7 = _run(_rev.weekly_summary(tenant_id=tid, range_="7d"))
    assert r7["total_savings_km"] == 5.5  # 3.5 + 2.0 + 0.0
    assert r7["total_optimize_events"] == 2
    assert r7["total_insert_events"] == 1
    assert len(r7["per_day"]) == 7
    # tA has more savings than tB in 7d.
    top = r7["top_techs"]
    assert top[0]["tech_user_id"] == "tA"
    assert top[0]["savings_km"] == 5.5

    r30 = _run(_rev.weekly_summary(tenant_id=tid, range_="30d"))
    assert r30["total_savings_km"] == 13.2  # 5.5 + 7.7
    assert len(r30["per_day"]) == 30
    _sync.route_optimize_events.delete_many({"tenant_id": tid})


# ── 2. Empty-week returns valid shape with zeros ──────────────────
def test_empty_range_returns_zeros():
    tid = f"tenant_p10f_empty_{uuid.uuid4().hex[:6]}"
    _sync.route_optimize_events.delete_many({"tenant_id": tid})
    r = _run(_rev.weekly_summary(tenant_id=tid, range_="7d"))
    assert r["total_savings_km"] == 0
    assert r["total_optimize_events"] == 0
    assert r["total_insert_events"] == 0
    assert len(r["per_day"]) == 7
    assert all(d["savings_km"] == 0 and d["event_count"] == 0
                 for d in r["per_day"])
    assert r["top_techs"] == []


# ── 3. Role guard: tech + customer → 403 ──────────────────────────
def test_weekly_savings_role_guard():
    for email in ("landscaper@aquaterra.com", "customer@aquaterra.com"):
        tok = _login(email)
        r = requests.get(f"{API}/dispatch/route/savings/weekly?range=7d",
                          headers={"Authorization": f"Bearer {tok}"},
                          timeout=10)
        assert r.status_code == 403, f"{email}: {r.status_code}"


# ── 4. Live endpoint returns shape + range clamps ─────────────────
def test_weekly_savings_endpoint_shape():
    tok = _login("manager@aquaterra.com")
    r = requests.get(f"{API}/dispatch/route/savings/weekly?range=7d",
                      headers={"Authorization": f"Bearer {tok}"},
                      timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["range"] == "7d"
    assert "period_start" in d and "period_end" in d
    assert isinstance(d["per_day"], list) and len(d["per_day"]) == 7
    assert isinstance(d["top_techs"], list)

    # bogus range clamps to 7d
    r = requests.get(f"{API}/dispatch/route/savings/weekly?range=xyz",
                      headers={"Authorization": f"Bearer {tok}"},
                      timeout=10)
    assert r.status_code == 200
    assert r.json()["range"] == "7d"


# ── 5. Optimize→apply writes an event log row ─────────────────────
def test_apply_writes_event_log():
    tid = _tid()
    tok = _login("manager@aquaterra.com")
    # Seed one job for a hypothetical tech.
    tech = "tech_p10f_apply"
    date_str = "2026-07-30"
    jid = f"jseed_{uuid.uuid4().hex[:10]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid, "title": "seed",
        "address": "seed", "tech_user_id": tech, "technician_id": tech,
        "scheduled_date": date_str, "route_index": 0,
        "lat": 33.71, "lon": -112.20})
    before = _sync.route_optimize_events.count_documents(
        {"tenant_id": tid, "tech_user_id": tech})
    r = requests.post(f"{API}/dispatch/route/apply",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"tech_user_id": tech, "route_date": date_str,
                              "ordered_job_ids": [jid], "savings_km": 4.2},
                       timeout=10)
    assert r.status_code == 200, r.text
    after = _sync.route_optimize_events.count_documents(
        {"tenant_id": tid, "tech_user_id": tech})
    assert after == before + 1
    ev = _sync.route_optimize_events.find_one(
        {"tenant_id": tid, "tech_user_id": tech},
        sort=[("executed_at", -1)])
    assert ev["kind"] == "optimize"
    assert ev["savings_km"] == 4.2
    _sync.jobs.delete_one({"id": jid})
    _sync.route_optimize_events.delete_many({"tenant_id": tid,
                                                "tech_user_id": tech})
