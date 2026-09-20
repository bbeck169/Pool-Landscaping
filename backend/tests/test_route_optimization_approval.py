"""Feb-2026 · Optimize Route (tech→admin approval + 10 s undo) — pytest suite.

Ten scenarios:
    1.  Preview math correctness on a 4-stop fixture.
    2.  Completed / could_not_service jobs stay pinned at their route_index.
    3.  Unique (tenant, tech, date) pending — new request supersedes prior.
    4.  Tech request → admin approve → jobs' route_index actually rewritten.
    5.  Admin direct apply path (no request row required).
    6.  Undo within 10 s window restores the prior route_index values.
    7.  Undo past the 10 s window returns 410 Gone.
    8.  Reject flow marks status=rejected and does NOT touch route_index.
    9.  Apply writes a ``route_optimize_events`` ledger row with kind=optimize_approval.
   10.  Cross-tenant isolation — sunbelt admin cannot touch aquaterra jobs.

Follows the existing test_route_savings.py / test_route_optimization.py conventions:
* Live HTTP calls hit http://localhost:8001/api (backend runs under supervisord).
* Sync pymongo client for setup + assertions; use unique tech_user_id + date
  per test so parallel runs stay isolated. Every test cleans up its own jobs
  + request rows on exit.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


# ── Env + clients ─────────────────────────────────────────────────────
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_MONGO_URL = _ENV["MONGO_URL"]; _DB_NAME = _ENV["DB_NAME"]
_sync = _shared_db()
API = "http://localhost:8001/api"


# ── Auth helpers ──────────────────────────────────────────────────────
def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture(scope="module")
def admin_h(): return _hdrs("admin@aquaterra.com")


@pytest.fixture(scope="module")
def tech_h(): return _hdrs("mike@aquaterra.com")


@pytest.fixture(scope="module")
def tid_aquaterra() -> str:
    u = _sync.users.find_one({"email": "admin@aquaterra.com"})
    return u["tenant_id"]


@pytest.fixture(scope="module")
def tech_id_mike() -> str:
    u = _sync.users.find_one({"email": "mike@aquaterra.com"})
    return u["id"]


# ── Job seeding ───────────────────────────────────────────────────────
def _seed_jobs(tid: str, tech_id: str, date: str,
                 fixture: list[dict]) -> list[str]:
    """Insert TEST_ jobs directly into mongo. Returns the list of job ids.

    Each fixture dict may specify: status, lat, lng, route_index. Missing
    fields get sensible defaults.
    """
    ids: list[str] = []
    for i, spec in enumerate(fixture):
        jid = f"TEST_optroute_{uuid.uuid4().hex[:10]}"
        _sync.jobs.insert_one({
            "id": jid,
            "tenant_id": tid,
            "title": f"TEST_route_optimize job {i}",
            "customer_name": f"TEST_cust_{i}",
            "address": f"TEST_addr_{i}",
            "tech_user_id": tech_id,
            "technician_id": tech_id,
            "scheduled_date": date,
            "route_index": spec.get("route_index", i),
            "status": spec.get("status", "scheduled"),
            "lat": spec.get("lat"),
            "lng": spec.get("lng"),
        })
        ids.append(jid)
    return ids


def _cleanup_jobs(tid: str, tech_id: str, date: str) -> None:
    _sync.jobs.delete_many({"tenant_id": tid, "tech_user_id": tech_id,
                              "scheduled_date": date,
                              "id": {"$regex": "^TEST_optroute_"}})
    _sync.route_optimization_requests.delete_many(
        {"tenant_id": tid, "tech_user_id": tech_id, "route_date": date})
    _sync.route_optimize_events.delete_many(
        {"tenant_id": tid, "tech_user_id": tech_id, "route_date": date})


# A geographically-perverse layout that guarantees NN reorders it.
# Currently ordered [0, 1, 2, 3] but the closest-to-origin walk is
# a very different sequence — see test 1 for the exact expectation.
_LAYOUT_A = [
    # (lat, lng)
    (33.50, -112.10),  # slot 0 — far
    (33.44, -112.05),  # slot 1 — near origin
    (33.55, -112.15),  # slot 2 — very far
    (33.45, -112.06),  # slot 3 — near
]
ORIGIN_LAT = 33.44
ORIGIN_LNG = -112.04


def _future_date(days_ahead: int) -> str:
    """A YYYY-MM-DD comfortably in the future so the TTL check passes."""
    d = datetime.now(timezone.utc).date() + timedelta(days=days_ahead)
    return d.isoformat()


# ─── 1. Preview math correctness ─────────────────────────────────────
def test_preview_math_correctness(tech_h, tid_aquaterra, tech_id_mike):
    tid = tid_aquaterra; tech = tech_id_mike
    date = _future_date(1)
    _cleanup_jobs(tid, tech, date)
    jids = _seed_jobs(tid, tech, date, [
        {"lat": la, "lng": ln} for la, ln in _LAYOUT_A
    ])
    try:
        r = requests.post(f"{API}/jobs/route-optimization/preview",
                            headers=tech_h,
                            json={"date": date,
                                  "current_lat": ORIGIN_LAT,
                                  "current_lng": ORIGIN_LNG},
                            timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["date"] == date
        assert d["tech_user_id"] == tech
        # 4 stops, all reshufflable — the proposed_order must be a
        # complete permutation of the seeded stops. Post-Feb-2026 the
        # optimizer swapped from crow-fly nearest-neighbor to Google
        # Directions (`optimize:true`) with a Haversine fallback, so
        # the specific first-stop identity is no longer deterministic
        # — it depends on the road network. But the fixture is
        # geographically perverse enough that ANY sensible optimizer
        # must reorder the input.
        assert set(d["proposed_order"]) == set(jids)
        assert d["proposed_order"] != jids
        # Miles saved is > 0 given the perverse layout.
        assert d["miles_saved"] > 0
        assert d["minutes_saved"] >= 0
        assert d["stops_affected"] > 0
        assert d["no_change"] is False
        assert d["origin"]["source"] == "device_gps"
        # Algorithm badge is one of the two valid values.
        assert d["algorithm"] in ("google_directions", "haversine_fallback")
    finally:
        _cleanup_jobs(tid, tech, date)


# ─── 2. Pinned statuses stay put ─────────────────────────────────────
def test_completed_and_cns_stay_pinned(tech_h, tid_aquaterra, tech_id_mike):
    tid = tid_aquaterra; tech = tech_id_mike
    date = _future_date(2)
    _cleanup_jobs(tid, tech, date)
    jids = _seed_jobs(tid, tech, date, [
        {"lat": _LAYOUT_A[0][0], "lng": _LAYOUT_A[0][1], "status": "scheduled"},
        {"lat": _LAYOUT_A[1][0], "lng": _LAYOUT_A[1][1], "status": "completed"},
        {"lat": _LAYOUT_A[2][0], "lng": _LAYOUT_A[2][1], "status": "scheduled"},
        {"lat": _LAYOUT_A[3][0], "lng": _LAYOUT_A[3][1], "status": "could_not_service"},
    ])
    try:
        r = requests.post(f"{API}/jobs/route-optimization/preview",
                            headers=tech_h,
                            json={"date": date,
                                  "current_lat": ORIGIN_LAT,
                                  "current_lng": ORIGIN_LNG},
                            timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        # Slots 1 and 3 hold the completed/CNS jobs; they must stay in
        # those slots on the proposed_order.
        assert d["proposed_order"][1] == jids[1], "completed slot moved"
        assert d["proposed_order"][3] == jids[3], "CNS slot moved"
        # Pinned ids surfaced back to the client.
        assert set(d["pinned_ids"]) == {jids[1], jids[3]}
    finally:
        _cleanup_jobs(tid, tech, date)


# ─── 3. Supersede existing pending ───────────────────────────────────
def test_new_request_supersedes_prior_pending(tech_h, tid_aquaterra, tech_id_mike):
    tid = tid_aquaterra; tech = tech_id_mike
    date = _future_date(3)
    _cleanup_jobs(tid, tech, date)
    _seed_jobs(tid, tech, date, [
        {"lat": la, "lng": ln} for la, ln in _LAYOUT_A
    ])
    try:
        # First request.
        r1 = requests.post(f"{API}/jobs/route-optimization/request",
                            headers=tech_h,
                            json={"date": date,
                                  "current_lat": ORIGIN_LAT,
                                  "current_lng": ORIGIN_LNG},
                            timeout=10)
        assert r1.status_code == 200, r1.text
        rid1 = r1.json()["id"]
        # Second request from the same tech / date → supersedes.
        r2 = requests.post(f"{API}/jobs/route-optimization/request",
                            headers=tech_h,
                            json={"date": date,
                                  "current_lat": ORIGIN_LAT + 0.001,
                                  "current_lng": ORIGIN_LNG + 0.001},
                            timeout=10)
        assert r2.status_code == 200, r2.text
        rid2 = r2.json()["id"]
        assert rid1 != rid2
        # First row must be marked expired; only one pending remains.
        n_pending = _sync.route_optimization_requests.count_documents(
            {"tenant_id": tid, "tech_user_id": tech,
              "route_date": date, "status": "pending"})
        assert n_pending == 1
        first = _sync.route_optimization_requests.find_one({"id": rid1})
        assert first["status"] == "expired"
        assert first.get("resolved_by") == "superseded"
    finally:
        _cleanup_jobs(tid, tech, date)


# ─── 4. Tech request → admin approve → route_index rewrites ─────────
def test_tech_request_admin_approve_writes_route_index(tech_h, admin_h,
                                                        tid_aquaterra,
                                                        tech_id_mike):
    tid = tid_aquaterra; tech = tech_id_mike
    date = _future_date(4)
    _cleanup_jobs(tid, tech, date)
    jids = _seed_jobs(tid, tech, date, [
        {"lat": la, "lng": ln} for la, ln in _LAYOUT_A
    ])
    try:
        # Tech creates the pending suggestion.
        r_req = requests.post(f"{API}/jobs/route-optimization/request",
                                headers=tech_h,
                                json={"date": date,
                                      "current_lat": ORIGIN_LAT,
                                      "current_lng": ORIGIN_LNG},
                                timeout=10)
        assert r_req.status_code == 200, r_req.text
        rid = r_req.json()["id"]
        proposed = r_req.json()["after_order"]

        # Before approve — route_index unchanged.
        for i, jid in enumerate(jids):
            j = _sync.jobs.find_one({"id": jid})
            assert j["route_index"] == i, "route_index shifted pre-approve"

        # Admin approves.
        r_ap = requests.post(f"{API}/jobs/route-optimization/{rid}/approve",
                              headers=admin_h, timeout=10)
        assert r_ap.status_code == 200, r_ap.text
        applied = r_ap.json()
        assert applied["status"] == "approved"

        # After approve — route_index equals the proposed_order positions.
        for new_idx, jid in enumerate(proposed):
            j = _sync.jobs.find_one({"id": jid})
            assert j["route_index"] == new_idx, (
                f"route_index not updated for {jid}: "
                f"expected {new_idx}, got {j.get('route_index')}")

        # Pending row upgraded.
        row = _sync.route_optimization_requests.find_one({"id": rid})
        assert row["status"] == "approved"
        assert row.get("applied_id") == applied["applied_id"]
    finally:
        _cleanup_jobs(tid, tech, date)


# ─── 5. Admin direct apply ──────────────────────────────────────────
def test_admin_direct_apply(admin_h, tid_aquaterra, tech_id_mike):
    tid = tid_aquaterra; tech = tech_id_mike
    date = _future_date(5)
    _cleanup_jobs(tid, tech, date)
    jids = _seed_jobs(tid, tech, date, [
        {"lat": la, "lng": ln} for la, ln in _LAYOUT_A
    ])
    try:
        reversed_order = list(reversed(jids))
        r = requests.post(f"{API}/jobs/route-optimization/apply",
                            headers=admin_h,
                            json={"tech_user_id": tech,
                                  "date": date,
                                  "proposed_order": reversed_order,
                                  "miles_saved": 3.2,
                                  "minutes_saved": 6.4},
                            timeout=10)
        assert r.status_code == 200, r.text
        for new_idx, jid in enumerate(reversed_order):
            j = _sync.jobs.find_one({"id": jid})
            assert j["route_index"] == new_idx
        # An "applied" state row must be persisted for /undo lookup.
        applied_id = r.json()["applied_id"]
        row = _sync.route_optimization_requests.find_one(
            {"id": applied_id, "tenant_id": tid})
        assert row["status"] == "applied"
        assert row["undone"] is False
    finally:
        _cleanup_jobs(tid, tech, date)


# ─── 6. Undo within window ──────────────────────────────────────────
def test_undo_within_window_restores_route_index(admin_h, tid_aquaterra,
                                                    tech_id_mike):
    tid = tid_aquaterra; tech = tech_id_mike
    date = _future_date(6)
    _cleanup_jobs(tid, tech, date)
    jids = _seed_jobs(tid, tech, date, [
        {"lat": la, "lng": ln} for la, ln in _LAYOUT_A
    ])
    try:
        reversed_order = list(reversed(jids))
        r = requests.post(f"{API}/jobs/route-optimization/apply",
                            headers=admin_h,
                            json={"tech_user_id": tech, "date": date,
                                  "proposed_order": reversed_order,
                                  "miles_saved": 1.0, "minutes_saved": 1.0},
                            timeout=10)
        applied_id = r.json()["applied_id"]
        # Verify the reorder actually landed.
        assert _sync.jobs.find_one({"id": jids[0]})["route_index"] == 3

        # Undo before the 10s TTL.
        ru = requests.post(f"{API}/jobs/route-optimization/undo",
                             headers=admin_h,
                             json={"applied_id": applied_id},
                             timeout=10)
        assert ru.status_code == 200, ru.text
        for i, jid in enumerate(jids):
            j = _sync.jobs.find_one({"id": jid})
            assert j["route_index"] == i, (
                f"undo did not restore original for {jid}: {j.get('route_index')}")
        row = _sync.route_optimization_requests.find_one({"id": applied_id})
        assert row["undone"] is True
    finally:
        _cleanup_jobs(tid, tech, date)


# ─── 7. Undo past window returns 410 ────────────────────────────────
def test_undo_past_window_returns_410(admin_h, tid_aquaterra, tech_id_mike):
    tid = tid_aquaterra; tech = tech_id_mike
    date = _future_date(7)
    _cleanup_jobs(tid, tech, date)
    jids = _seed_jobs(tid, tech, date, [
        {"lat": la, "lng": ln} for la, ln in _LAYOUT_A
    ])
    try:
        r = requests.post(f"{API}/jobs/route-optimization/apply",
                            headers=admin_h,
                            json={"tech_user_id": tech, "date": date,
                                  "proposed_order": list(reversed(jids)),
                                  "miles_saved": 1.0, "minutes_saved": 1.0},
                            timeout=10)
        applied_id = r.json()["applied_id"]

        # Force the undo window to expire without a 10-second sleep.
        past = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        _sync.route_optimization_requests.update_one(
            {"id": applied_id},
            {"$set": {"undo_expires_at": past}})

        ru = requests.post(f"{API}/jobs/route-optimization/undo",
                             headers=admin_h,
                             json={"applied_id": applied_id},
                             timeout=10)
        assert ru.status_code == 410, ru.text
        # Route_index remains in the applied state — no restore happened.
        j = _sync.jobs.find_one({"id": jids[0]})
        assert j["route_index"] == 3
    finally:
        _cleanup_jobs(tid, tech, date)


# ─── 8. Reject flow ─────────────────────────────────────────────────
def test_reject_flow_leaves_route_index_untouched(tech_h, admin_h,
                                                    tid_aquaterra,
                                                    tech_id_mike):
    tid = tid_aquaterra; tech = tech_id_mike
    date = _future_date(8)
    _cleanup_jobs(tid, tech, date)
    jids = _seed_jobs(tid, tech, date, [
        {"lat": la, "lng": ln} for la, ln in _LAYOUT_A
    ])
    try:
        r_req = requests.post(f"{API}/jobs/route-optimization/request",
                                headers=tech_h,
                                json={"date": date,
                                      "current_lat": ORIGIN_LAT,
                                      "current_lng": ORIGIN_LNG},
                                timeout=10)
        rid = r_req.json()["id"]

        r_rej = requests.post(f"{API}/jobs/route-optimization/{rid}/reject",
                                headers=admin_h, timeout=10)
        assert r_rej.status_code == 200
        assert r_rej.json()["status"] == "rejected"

        # Job order is unchanged.
        for i, jid in enumerate(jids):
            j = _sync.jobs.find_one({"id": jid})
            assert j["route_index"] == i
        row = _sync.route_optimization_requests.find_one({"id": rid})
        assert row["status"] == "rejected"
    finally:
        _cleanup_jobs(tid, tech, date)


# ─── 9. Ledger event on apply ──────────────────────────────────────
def test_apply_writes_ledger_event(admin_h, tid_aquaterra, tech_id_mike):
    tid = tid_aquaterra; tech = tech_id_mike
    date = _future_date(9)
    _cleanup_jobs(tid, tech, date)
    jids = _seed_jobs(tid, tech, date, [
        {"lat": la, "lng": ln} for la, ln in _LAYOUT_A
    ])
    try:
        before = _sync.route_optimize_events.count_documents(
            {"tenant_id": tid, "tech_user_id": tech, "route_date": date})
        r = requests.post(f"{API}/jobs/route-optimization/apply",
                            headers=admin_h,
                            json={"tech_user_id": tech, "date": date,
                                  "proposed_order": list(reversed(jids)),
                                  "miles_saved": 2.5, "minutes_saved": 5.0},
                            timeout=10)
        assert r.status_code == 200, r.text
        after = _sync.route_optimize_events.count_documents(
            {"tenant_id": tid, "tech_user_id": tech, "route_date": date})
        assert after == before + 1
        ev = _sync.route_optimize_events.find_one(
            {"tenant_id": tid, "tech_user_id": tech, "route_date": date},
            sort=[("executed_at", -1)])
        assert ev["kind"] == "optimize_approval"
        assert ev["stop_count"] == 4
    finally:
        _cleanup_jobs(tid, tech, date)


# ─── 10. Cross-tenant isolation ───────────────────────────────────
def test_cross_tenant_isolation(tid_aquaterra, tech_id_mike):
    """A different-tenant admin cannot touch aquaterra jobs.

    Seeds a synthetic 2nd tenant + admin row at test time so the
    assertion always runs (no dependency on optional seed data).
    """
    from utils import hash_password
    other_tid = f"test_optroute_tenant_{uuid.uuid4().hex[:8]}"
    other_email = f"test_optroute_admin_{uuid.uuid4().hex[:6]}@example.com"
    _sync.tenants.insert_one({"id": other_tid, "name": "TEST_optroute_tenant"})
    _sync.users.insert_one({
        "id": f"test_optroute_u_{uuid.uuid4().hex[:8]}",
        "tenant_id": other_tid,
        "email": other_email,
        "name": "TEST optroute admin",
        "role": "admin",
        "active": True,
        "password_hash": hash_password("password123"),
    })

    tid = tid_aquaterra; tech = tech_id_mike
    date = _future_date(10)
    _cleanup_jobs(tid, tech, date)
    jids = _seed_jobs(tid, tech, date, [
        {"lat": la, "lng": ln} for la, ln in _LAYOUT_A
    ])
    try:
        other_h = _hdrs(other_email)
        # The other-tenant admin tries to apply against aquaterra's tech.
        r = requests.post(f"{API}/jobs/route-optimization/apply",
                            headers=other_h,
                            json={"tech_user_id": tech, "date": date,
                                  "proposed_order": list(reversed(jids)),
                                  "miles_saved": 1.0, "minutes_saved": 1.0},
                            timeout=10)
        # 403 (tenant check) or 200-with-zero-updates are both acceptable —
        # what matters is aquaterra jobs stay in their original slots.
        assert r.status_code in (200, 403)
        for i, jid in enumerate(jids):
            j = _sync.jobs.find_one({"id": jid})
            assert j["route_index"] == i, (
                f"cross-tenant leak: {jid} route_index moved to "
                f"{j.get('route_index')}")
    finally:
        _cleanup_jobs(tid, tech, date)
        _sync.users.delete_many({"email": other_email})
        _sync.tenants.delete_one({"id": other_tid})
