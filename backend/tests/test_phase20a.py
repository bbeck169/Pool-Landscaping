"""Phase 20A tests — route optimization + auto-invoicing on submit."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL"); DB_NAME = _BE.get("DB_NAME")


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc(): return MongoClient(MONGO_URL)[DB_NAME]

@pytest.fixture(scope="module")
def tech_h(): return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def admin_h(): return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def sunbelt_tech_h():
    try: return {"Authorization": f"Bearer {_login('tech@sunbelt.com')['access_token']}"}
    except Exception: pytest.skip("sunbelt tech missing")


def _seed_pool_job(dbc, tenant_slug, tech_email, lat, lng, mins=15,
                    price=125.0, billable=True, service_type="Weekly Pool Service"):
    tenant = dbc.tenants.find_one({"slug": tenant_slug})
    user = dbc.users.find_one({"email": tech_email})
    jid = str(uuid.uuid4())
    dbc.jobs.insert_one({
        "id": jid, "tenant_id": tenant["id"],
        "customer_id": "cust-test", "customer_name": "TEST_ 20A",
        "title": service_type, "service_type": service_type, "job_type": service_type,
        "status": "scheduled", "technician_id": user["id"],
        "site_lat": lat, "site_lng": lng,
        "scheduled_start": (datetime.now(timezone.utc) + timedelta(minutes=mins)).isoformat(),
        "price": price, "billable": billable, "photos": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return jid


def _cleanup(dbc, jids, email="mike@aquaterra.com"):
    for jid in jids:
        dbc.jobs.delete_one({"id": jid})
        dbc.service_reports.delete_many({"job_id": jid})
        dbc.quotes.delete_many({"job_id": jid})
    u = dbc.users.find_one({"email": email})
    if u:
        dbc.time_entries.delete_many({"user_id": u["id"]})
    dbc.route_optimizations.delete_many({"tenant_id": dbc.tenants.find_one({"slug":"aquaterra"})["id"]})


# ─── 20A.1 · Route Optimization ────────────────────────────────────────────
# Feb-2026 HOTFIX (user report): technicians can NO LONGER call
# ``/schedule/optimize-route`` directly — it is a dispatcher/planner
# action. These tests use ``admin_h`` and pass ``user_id=<mike_uid>``
# so the admin-override path plans mike's route (identical semantics
# to the pre-hotfix behavior, just from the admin seat).
def _mike_uid(dbc):
    return dbc.users.find_one({"email": "mike@aquaterra.com"})["id"]


def test_route_optimize_orders_three_jobs(admin_h, tech_h, dbc):
    j1 = _seed_pool_job(dbc, "aquaterra", "mike@aquaterra.com", 33.60, -112.20, mins=30)
    j2 = _seed_pool_job(dbc, "aquaterra", "mike@aquaterra.com", 33.70, -112.20, mins=60)
    j3 = _seed_pool_job(dbc, "aquaterra", "mike@aquaterra.com", 33.65, -112.20, mins=90)
    try:
        r = requests.post(f"{API}/schedule/optimize-route?user_id=" + _mike_uid(dbc),
                          headers=admin_h,
                          json={"start_lat": 33.60, "start_lng": -112.20}, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert {j1, j2, j3}.issubset(set(data["ordered_job_ids"]))
        # Among our seeded three, nearest-neighbor from (33.60, -112.20) visits
        # j1 → j3 → j2 (Haversine ordering).
        seen = [j for j in data["ordered_job_ids"] if j in {j1, j2, j3}]
        assert seen == [j1, j3, j2]
        assert data["total_distance_m"] > 0
        assert data["cached"] is False
        # Feb-2026 · Router canonical badge set (see
        # ``routers/route_optimization.py::optimize_route`` docstring).
        # The legacy ``"nearest_neighbor"`` badge no longer exists —
        # the fallback now writes ``"haversine_fallback"``, and the
        # Google path badges either ``"google_directions"`` or the
        # composite ``"directions_v2+orion_bias"`` (ZIP tiebreaker
        # emits a warning on real seeded data).
        assert data["algorithm"] in (
            "google_directions",
            "directions_v2+orion_bias",
            "haversine_fallback",
        ), data["algorithm"]
    finally:
        _cleanup(dbc, [j1, j2, j3])


def test_route_optimize_cache_hit(admin_h, dbc):
    j1 = _seed_pool_job(dbc, "aquaterra", "mike@aquaterra.com", 33.60, -112.20)
    j2 = _seed_pool_job(dbc, "aquaterra", "mike@aquaterra.com", 33.70, -112.20)
    try:
        mike = _mike_uid(dbc)
        r1 = requests.post(f"{API}/schedule/optimize-route?user_id=" + mike,
                           headers=admin_h,
                           json={"start_lat": 33.60, "start_lng": -112.20}, timeout=15).json()
        r2 = requests.post(f"{API}/schedule/optimize-route?user_id=" + mike,
                           headers=admin_h,
                           json={"start_lat": 33.60, "start_lng": -112.20}, timeout=15).json()
        assert r1["cached"] is False
        assert r2["cached"] is True
        assert r1["ordered_job_ids"] == r2["ordered_job_ids"]
    finally:
        _cleanup(dbc, [j1, j2])


def test_route_optimize_cross_tenant_denied(tech_h, sunbelt_tech_h, dbc):
    # Aquaterra tech cannot pass user_id of a Sunbelt user.
    sunbelt_u = dbc.users.find_one({"email": "tech@sunbelt.com"})
    r = requests.post(f"{API}/schedule/optimize-route?user_id=" + sunbelt_u["id"],
                      headers=tech_h, json={}, timeout=15)
    assert r.status_code == 403


# ─── 20A.2 · Auto-invoicing on submit ──────────────────────────────────────
def _do_submit(tech_h, jid):
    requests.get(f"{API}/jobs/{jid}/service-report", headers=tech_h, timeout=15)
    return requests.post(f"{API}/jobs/{jid}/service-report/submit",
                         headers=tech_h, timeout=15)


def test_auto_invoice_on_billable_submit(tech_h, dbc):
    jid = _seed_pool_job(dbc, "aquaterra", "mike@aquaterra.com", 33.60, -112.20, price=180.0)
    try:
        r = _do_submit(tech_h, jid)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("invoice_id"), "invoice_id should be present in submit response"
        inv = dbc.quotes.find_one({"id": data["invoice_id"]})
        assert inv["job_id"] == jid
        assert inv["total"] == 180.0
        assert inv["auto_created_from_report"] is True
    finally:
        _cleanup(dbc, [jid])


def test_auto_invoice_skipped_for_non_billable(tech_h, dbc):
    jid = _seed_pool_job(dbc, "aquaterra", "mike@aquaterra.com", 33.60, -112.20,
                         billable=False, price=180.0)
    try:
        r = _do_submit(tech_h, jid)
        assert r.status_code == 200
        assert not r.json().get("invoice_id")
        assert dbc.quotes.count_documents({"job_id": jid}) == 0
    finally:
        _cleanup(dbc, [jid])


def test_auto_invoice_skipped_for_warranty_service_type(tech_h, dbc):
    jid = _seed_pool_job(dbc, "aquaterra", "mike@aquaterra.com", 33.60, -112.20,
                         service_type="Warranty Callback", price=180.0)
    try:
        r = _do_submit(tech_h, jid)
        assert r.status_code == 200
        assert not r.json().get("invoice_id")
    finally:
        _cleanup(dbc, [jid])


def test_auto_invoice_applies_referral_credit(tech_h, dbc):
    u = dbc.users.find_one({"email": "mike@aquaterra.com"})
    tenant = dbc.tenants.find_one({"slug": "aquaterra"})
    # Seed a 50%-off credit for the customer cust-test.
    dbc.service_credits.insert_one({
        "id": str(uuid.uuid4()), "tenant_id": tenant["id"],
        "customer_id": "cust-test", "kind": "percent_off_month",
        "pct": 50, "months_remaining": 1, "source": "referral",
        "granted_at": datetime.now(timezone.utc).isoformat(),
    })
    jid = _seed_pool_job(dbc, "aquaterra", "mike@aquaterra.com", 33.60, -112.20, price=200.0)
    try:
        r = _do_submit(tech_h, jid)
        inv_id = r.json().get("invoice_id")
        assert inv_id
        inv = dbc.quotes.find_one({"id": inv_id})
        assert inv["total"] == 100.0  # 50% off 200
        assert inv["applied_credits"] and inv["applied_credits"][0]["pct"] == 50
    finally:
        _cleanup(dbc, [jid])
        dbc.service_credits.delete_many({"customer_id": "cust-test"})


def test_auto_invoice_respects_tenant_setting_off(tech_h, admin_h, dbc):
    tenant = dbc.tenants.find_one({"slug": "aquaterra"})
    prior = (tenant.get("settings") or {}).get("auto_invoice_on_submit")
    dbc.tenants.update_one({"id": tenant["id"]},
                           {"$set": {"settings.auto_invoice_on_submit": False}})
    jid = _seed_pool_job(dbc, "aquaterra", "mike@aquaterra.com", 33.60, -112.20, price=180.0)
    try:
        r = _do_submit(tech_h, jid)
        assert not r.json().get("invoice_id")
    finally:
        _cleanup(dbc, [jid])
        # Restore prior setting (may have been unset — default True).
        if prior is None:
            dbc.tenants.update_one({"id": tenant["id"]},
                                   {"$unset": {"settings.auto_invoice_on_submit": ""}})
        else:
            dbc.tenants.update_one({"id": tenant["id"]},
                                   {"$set": {"settings.auto_invoice_on_submit": prior}})
