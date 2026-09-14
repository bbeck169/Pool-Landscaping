"""Feb-2026 · Phase — Recommended Schedule auto-assign v1 tests.

Covers the four branches of the auto-assign step on
``POST /api/recurring-jobs``:

1. Happy path — no tech/day + at least one peer route in the
   same (service_type, frequency) → 200 with
   ``auto_assign_info.auto_assigned=true`` + populated fields +
   persisted ``assigned_tech_id`` + ``day_of_week``.
2. No peer routes → ``auto_assigned=false,
   reason="no_existing_routes"``. Record still persists without
   a tech/day.
3. Customer has no coords → ``auto_assigned=false,
   reason="no_geocode"``. Record still persists.
4. Manual field wins — payload carries either ``assigned_tech_id``
   OR ``day_of_week`` → auto-assign skipped;
   ``auto_assigned=false, reason="manual_override"``.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]

_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or (
    (_PUBLIC_URL.rstrip("/") + "/api") if _PUBLIC_URL else
    "http://localhost:8001/api"
)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdr(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _tenant_of(email: str) -> str:
    return _sync.users.find_one({"email": email})["tenant_id"]


@pytest.fixture
def autoassign_ctx():
    """Seed one peer recurring template + its geocoded customer so
    the auto-assign step has an existing route to hug. The new
    customer is planted a short drive from the peer so the
    centroid pick is deterministic (a single slot always wins)."""
    tid = _tenant_of("super@aquaterra.com")

    # Ensure the tenant has at least one technician.
    tech = _sync.users.find_one({"tenant_id": tid, "role": "technician"},
                                 {"_id": 0, "id": 1, "name": 1})
    if not tech:
        pytest.skip("no technician seeded for this tenant")

    peer_cust = {
        "id": "aa-peer-cust", "tenant_id": tid,
        "name": "Peer Customer",
        "latitude": 33.4484, "longitude": -112.0740,       # Phoenix
    }
    new_cust = {
        "id": "aa-new-cust", "tenant_id": tid,
        "name": "New Customer",
        "latitude": 33.4600, "longitude": -112.0800,       # ~1.5 km N
    }
    orphan_cust = {
        "id": "aa-orphan-cust", "tenant_id": tid,
        "name": "Orphan Customer (no coords)",
    }
    _sync.customers.insert_many([peer_cust, new_cust, orphan_cust])

    peer_tpl = {
        "id": "aa-peer-tpl", "tenant_id": tid,
        "customer_id": peer_cust["id"],
        "customer_name": peer_cust["name"],
        "service_type": "Weekly Pool Service",
        "frequency": "weekly",
        "day_of_week": 2,                                    # Wednesday
        "assigned_tech_id": tech["id"],
        "start_date": "2026-02-01",
        "price_cents": 15000,
        "active": True,
        "is_active": True,
    }
    _sync.recurring_job_templates.insert_one(peer_tpl)

    yield {"tenant_id": tid, "tech": tech,
            "peer_customer_id": peer_cust["id"],
            "new_customer_id": new_cust["id"],
            "orphan_customer_id": orphan_cust["id"]}

    _sync.customers.delete_many(
        {"id": {"$in": ["aa-peer-cust", "aa-new-cust", "aa-orphan-cust"]}})
    _sync.recurring_job_templates.delete_many(
        {"tenant_id": tid,
         "$or": [{"id": "aa-peer-tpl"},
                  {"customer_id": {"$in": ["aa-new-cust",
                                              "aa-orphan-cust"]}}]})


# ══════════════════════════════════════════════════════════════════
# 1. Happy path — no tech/day + one peer route.
# ══════════════════════════════════════════════════════════════════

def test_route_proximity_assigns_from_nearest_slot(autoassign_ctx):
    hdr = _hdr("super@aquaterra.com")
    payload = {
        "customer_id": autoassign_ctx["new_customer_id"],
        "service_type": "Weekly Pool Service",
        "frequency": "weekly",
        "start_date": "2026-02-15",
        "price_cents": 15000,
        "is_active": True,
    }
    r = requests.post(f"{API}/recurring-jobs", json=payload,
                       headers=hdr, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    info = body.get("auto_assign_info") or {}
    assert info.get("auto_assigned") is True
    assert info.get("reason") == "route_proximity"
    assert info.get("technician_id") == autoassign_ctx["tech"]["id"]
    assert info.get("day_of_week") == 2                        # Wed
    assert info.get("technician_name") == autoassign_ctx["tech"].get("name")
    # Persisted fields on the doc — a follow-up GET must see the
    # assignment stamped, not just the client-only info bundle.
    assert body["assigned_tech_id"] == autoassign_ctx["tech"]["id"]
    assert body["day_of_week"] == 2
    assert body["auto_assigned"] is True
    assert body["auto_assign_reason"] == "route_proximity"
    assert isinstance(body["auto_assign_extra_minutes"], int)
    # ~1.5 km peer → ~2 min at 45 km/h. Assert a sane bound.
    assert 0 <= body["auto_assign_extra_minutes"] <= 5
    assert body["auto_assign_source_meters"] > 0


# ══════════════════════════════════════════════════════════════════
# 2. No peer routes → no_existing_routes.
# ══════════════════════════════════════════════════════════════════

def test_no_peer_routes_falls_through(autoassign_ctx):
    hdr = _hdr("super@aquaterra.com")
    payload = {
        "customer_id": autoassign_ctx["new_customer_id"],
        # No peer at monthly cadence.
        "service_type": "Monthly Deep Clean",
        "frequency": "monthly",
        "day_of_month": 15,
        "start_date": "2026-02-15",
        "price_cents": 15000,
        "is_active": True,
    }
    r = requests.post(f"{API}/recurring-jobs", json=payload,
                       headers=hdr, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    info = body.get("auto_assign_info") or {}
    assert info.get("auto_assigned") is False
    assert info.get("reason") == "no_existing_routes"
    # Record persisted with no tech/dow.
    assert body.get("assigned_tech_id") is None
    assert body.get("day_of_week") is None
    assert body["auto_assigned"] is False
    assert body["auto_assign_reason"] == "no_existing_routes"


# ══════════════════════════════════════════════════════════════════
# 3. Customer has no coords → no_geocode.
# ══════════════════════════════════════════════════════════════════

def test_no_geocode_falls_through(autoassign_ctx):
    hdr = _hdr("super@aquaterra.com")
    payload = {
        "customer_id": autoassign_ctx["orphan_customer_id"],
        "service_type": "Weekly Pool Service",
        "frequency": "weekly",
        "start_date": "2026-02-15",
        "price_cents": 15000,
        "is_active": True,
    }
    r = requests.post(f"{API}/recurring-jobs", json=payload,
                       headers=hdr, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    info = body.get("auto_assign_info") or {}
    assert info.get("auto_assigned") is False
    assert info.get("reason") == "no_geocode"
    assert body.get("assigned_tech_id") is None
    assert body.get("day_of_week") is None


# ══════════════════════════════════════════════════════════════════
# 4. Manual override — any of {tech, dow, crew} wins.
# ══════════════════════════════════════════════════════════════════

def test_manual_tech_skips_auto_assign(autoassign_ctx):
    hdr = _hdr("super@aquaterra.com")
    payload = {
        "customer_id": autoassign_ctx["new_customer_id"],
        "service_type": "Weekly Pool Service",
        "frequency": "weekly",
        "day_of_week": 4,                                     # Friday, mismatched
        "assigned_tech_id": autoassign_ctx["tech"]["id"],
        "start_date": "2026-02-15",
        "price_cents": 15000,
        "is_active": True,
    }
    r = requests.post(f"{API}/recurring-jobs", json=payload,
                       headers=hdr, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    info = body.get("auto_assign_info") or {}
    assert info.get("auto_assigned") is False
    assert info.get("reason") == "manual_override"
    # Manual choice preserved bit-for-bit.
    assert body["day_of_week"] == 4
    assert body["assigned_tech_id"] == autoassign_ctx["tech"]["id"]


def test_manual_dow_only_still_skips_auto_assign(autoassign_ctx):
    """Only a day set (no tech) → still counts as manual — the
    caller is opting-out of the "recommend both" heuristic."""
    hdr = _hdr("super@aquaterra.com")
    payload = {
        "customer_id": autoassign_ctx["new_customer_id"],
        "service_type": "Weekly Pool Service",
        "frequency": "weekly",
        "day_of_week": 0,                                     # Monday
        "start_date": "2026-02-15",
        "price_cents": 15000,
        "is_active": True,
    }
    r = requests.post(f"{API}/recurring-jobs", json=payload,
                       headers=hdr, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    info = body.get("auto_assign_info") or {}
    assert info.get("auto_assigned") is False
    assert info.get("reason") == "manual_override"
    assert body["day_of_week"] == 0
    assert body["assigned_tech_id"] is None


# ══════════════════════════════════════════════════════════════════
# 5. Minutes heuristic math — validate the 750-m-per-min conversion
# ══════════════════════════════════════════════════════════════════

def test_minutes_heuristic_math():
    """Direct unit-test the ``compute_route_proximity_assignment``
    minutes computation: distance / 750 → minutes."""
    from services.recurring_jobs.route_proximity import (
        _haversine_m, _METERS_PER_MINUTE,
    )
    # ~15 km between two Phoenix-area points.
    d = _haversine_m(33.4484, -112.0740, 33.5000, -112.2000)
    minutes = round(d / _METERS_PER_MINUTE)
    # 15 km / 750 m per min ≈ 20 min ± 2 min cushion.
    assert 15 <= minutes <= 25, (d, minutes)
