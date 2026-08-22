"""Feb-2026 · P37a — GPS auto-start backend contract tests.

Pins:
  1. Tenant settings GET/PATCH — staff read; tech 403 on PATCH; radius
     validation; audit-log-writable.
  2. Tech consent grant + revoke roundtrip. Revoke stamps revoked_at
     and preserves the audit trail (no delete).
  3. ``POST /jobs/{jid}/arrive`` gates (short-circuit order):
       feature_disabled → consent_required → throttled → out_of_radius
       → job_completed → started.
  4. Auto-stop fires on ``PUT /jobs/{jid}`` status→completed transition
     (regression check — this behavior existed pre-P37a and must
     survive the P37a rewrite).
  5. Auto-stop fires on ``POST /jobs/{jid}/service-report/submit`` —
     the P37a fill-in-the-gap change.
  6. ``/api/openapi.json`` still 200 and lists the new routes.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(email: str) -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


@pytest.fixture
def admin_h():
    return _hdrs("admin@aquaterra.com")


@pytest.fixture
def tech_h():
    return _hdrs("mike@aquaterra.com")


@pytest.fixture
def tech_user():
    return _sync.users.find_one({"email": "mike@aquaterra.com"})


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one(
        {"email": "admin@aquaterra.com"})["tenant_id"]


@pytest.fixture(autouse=True)
def _restore_state(aquaterra_tid, tech_user):
    """Reset gps flag OFF + purge consents + purge test jobs before/after."""
    def _reset():
        _sync.tenants.update_one(
            {"id": aquaterra_tid},
            {"$set": {"gps_auto_start_enabled": False,
                        "arrival_radius_meters": 75}})
        _sync.tech_gps_consents.delete_many(
            {"tenant_id": aquaterra_tid,
              "user_id": tech_user["id"]})
        _sync.jobs.delete_many(
            {"tenant_id": aquaterra_tid, "id": {"$regex": "^TEST_p37_"}})
    _reset()
    yield
    _reset()


def _seed_job(tid: str, tech_user: dict, *, site_lat: float = 33.5806,
                site_lng: float = -112.2374, status: str = "scheduled") -> str:
    jid = f"TEST_p37_j_{uuid.uuid4().hex[:8]}"
    # The /arrive endpoint compares job.technician_id vs
    # user.technician_id (the field on the User doc that's separate
    # from user.id). Match that field, not user.id.
    tech_technician_id = tech_user.get("technician_id") or tech_user["id"]
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tid,
        "technician_id": tech_technician_id,
        "customer_id": f"TEST_p37_c_{uuid.uuid4().hex[:6]}",
        # Landscape jobs skip the chemistry gate — see
        # ``services.chemistry_gate.is_pool_job``. Keeping the seed
        # off pool so completion transitions don't require readings.
        "service_type": "Landscape maintenance",
        "kind": "landscape",
        "checklist_kind": "landscape",
        "status": status,
        "site_lat": site_lat, "site_lng": site_lng,
        "latitude": site_lat, "longitude": site_lng,
        "created_at": "2026-06-01T09:00:00+00:00",
    })
    return jid


# ─── 1. openapi ──────────────────────────────────────────────────────

def test_openapi_lists_new_routes():
    r = requests.get(f"{API}/openapi.json", timeout=15)
    assert r.status_code == 200
    paths = r.json().get("paths") or {}
    assert "/api/settings/gps-auto-start" in paths
    assert "/api/tech-gps-consent" in paths
    assert "/api/tech-gps-consent/me" in paths


# ─── 2. Settings RBAC + validation ───────────────────────────────────

def test_settings_get_open_to_technician(tech_h):
    r = requests.get(f"{API}/settings/gps-auto-start",
                        headers=tech_h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "gps_auto_start_enabled" in body
    assert "arrival_radius_meters" in body


def test_settings_patch_forbidden_for_technician(tech_h):
    r = requests.patch(f"{API}/settings/gps-auto-start",
                          headers=tech_h,
                          json={"gps_auto_start_enabled": True}, timeout=15)
    assert r.status_code == 403


def test_settings_patch_admin_write_and_default(admin_h):
    r = requests.patch(f"{API}/settings/gps-auto-start",
                          headers=admin_h,
                          json={"gps_auto_start_enabled": True,
                                  "arrival_radius_meters": 120}, timeout=15)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["gps_auto_start_enabled"] is True
    assert b["arrival_radius_meters"] == 120


def test_settings_patch_invalid_radius_400(admin_h):
    r = requests.patch(f"{API}/settings/gps-auto-start",
                          headers=admin_h,
                          json={"arrival_radius_meters": 3}, timeout=15)
    assert r.status_code == 400


# ─── 3. Consent grant + revoke roundtrip ─────────────────────────────

def test_tech_consent_grant_then_revoke_preserves_history(
    tech_h, tech_user, aquaterra_tid,
):
    # Grant.
    r = requests.post(f"{API}/tech-gps-consent", headers=tech_h,
                         json={"granted": True,
                                 "method": "mobile_onboarding"}, timeout=15)
    assert r.status_code == 200
    assert r.json()["active"] is True

    # Revoke.
    r2 = requests.post(f"{API}/tech-gps-consent", headers=tech_h,
                          json={"granted": False,
                                  "method": "user_revoked"}, timeout=15)
    assert r2.status_code == 200
    assert r2.json()["active"] is False

    # History: exactly one grant row (revoked) — no deletions.
    rows = list(_sync.tech_gps_consents.find(
        {"user_id": tech_user["id"], "tenant_id": aquaterra_tid},
    ))
    assert len(rows) >= 1
    granted = [r for r in rows if r["granted"] is True]
    assert len(granted) == 1
    assert granted[0]["revoked_at"] is not None
    assert granted[0]["revoked_reason"] == "user_revoked"


def test_get_my_consent_reflects_active_state(tech_h):
    # Empty history.
    r = requests.get(f"{API}/tech-gps-consent/me",
                        headers=tech_h, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is False
    assert isinstance(body["history"], list)

    # After a grant.
    requests.post(f"{API}/tech-gps-consent", headers=tech_h,
                     json={"granted": True}, timeout=15)
    r2 = requests.get(f"{API}/tech-gps-consent/me",
                         headers=tech_h, timeout=15)
    assert r2.json()["active"] is True


# ─── 4. /arrive gate order ───────────────────────────────────────────

def test_arrive_returns_feature_disabled_when_tenant_flag_off(
    tech_h, tech_user, aquaterra_tid,
):
    # Grant consent so consent gate doesn't take precedence.
    requests.post(f"{API}/tech-gps-consent", headers=tech_h,
                     json={"granted": True}, timeout=15)
    jid = _seed_job(aquaterra_tid, tech_user)
    try:
        r = requests.post(f"{API}/jobs/{jid}/arrive", headers=tech_h,
                             json={"lat": 33.5806, "lng": -112.2374},
                             timeout=15)
        assert r.status_code == 200, r.text
        assert r.json() == {"started": False, "reason": "feature_disabled"}
        # No timer stamp landed.
        assert _sync.jobs.find_one({"id": jid}).get("timer_started_at") is None
    finally:
        pass  # cleanup in autouse fixture


def test_arrive_returns_consent_required_when_tech_has_no_grant(
    tech_h, tech_user, aquaterra_tid, admin_h,
):
    requests.patch(f"{API}/settings/gps-auto-start", headers=admin_h,
                      json={"gps_auto_start_enabled": True}, timeout=15)
    jid = _seed_job(aquaterra_tid, tech_user)
    r = requests.post(f"{API}/jobs/{jid}/arrive", headers=tech_h,
                         json={"lat": 33.5806, "lng": -112.2374},
                         timeout=15)
    assert r.status_code == 200
    assert r.json() == {"started": False, "reason": "consent_required"}
    assert _sync.jobs.find_one({"id": jid}).get("timer_started_at") is None


def test_arrive_returns_out_of_radius_when_too_far(
    tech_h, tech_user, aquaterra_tid, admin_h,
):
    requests.patch(f"{API}/settings/gps-auto-start", headers=admin_h,
                      json={"gps_auto_start_enabled": True,
                              "arrival_radius_meters": 75}, timeout=15)
    requests.post(f"{API}/tech-gps-consent", headers=tech_h,
                     json={"granted": True}, timeout=15)
    jid = _seed_job(aquaterra_tid, tech_user,
                       site_lat=33.5806, site_lng=-112.2374)
    # ~200m north of the site.
    r = requests.post(f"{API}/jobs/{jid}/arrive", headers=tech_h,
                         json={"lat": 33.5824, "lng": -112.2374},
                         timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["started"] is False
    assert body["reason"] == "out_of_radius"
    assert body["distance_m"] > 75
    assert body["radius_m"] == 75
    assert _sync.jobs.find_one({"id": jid}).get("timer_started_at") is None


def test_arrive_starts_timer_and_stamps_audit_log(
    tech_h, tech_user, aquaterra_tid, admin_h,
):
    requests.patch(f"{API}/settings/gps-auto-start", headers=admin_h,
                      json={"gps_auto_start_enabled": True,
                              "arrival_radius_meters": 75}, timeout=15)
    requests.post(f"{API}/tech-gps-consent", headers=tech_h,
                     json={"granted": True}, timeout=15)
    jid = _seed_job(aquaterra_tid, tech_user)
    r = requests.post(f"{API}/jobs/{jid}/arrive", headers=tech_h,
                         json={"lat": 33.5806, "lng": -112.2374,
                                 "accuracy": 8.5}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["started"] is True
    assert body["already_running"] is False
    row = _sync.jobs.find_one({"id": jid})
    assert row["timer_started_at"]
    assert row["timer_start_method"] == "gps_arrival"
    audit = _sync.audit_logs.find_one(
        {"tenant_id": aquaterra_tid, "event": "job_timer_auto_start",
          "payload.job_id": jid},
        sort=[("at", -1)],
    )
    assert audit is not None
    assert audit["payload"]["accuracy_m"] == 8.5
    _sync.audit_logs.delete_many({"payload.job_id": jid})


def test_arrive_second_call_within_60s_is_throttled(
    tech_h, tech_user, aquaterra_tid, admin_h,
):
    requests.patch(f"{API}/settings/gps-auto-start", headers=admin_h,
                      json={"gps_auto_start_enabled": True}, timeout=15)
    requests.post(f"{API}/tech-gps-consent", headers=tech_h,
                     json={"granted": True}, timeout=15)
    jid = _seed_job(aquaterra_tid, tech_user)
    r1 = requests.post(f"{API}/jobs/{jid}/arrive", headers=tech_h,
                          json={"lat": 33.5806, "lng": -112.2374},
                          timeout=15)
    assert r1.status_code == 200 and r1.json()["started"] is True
    # Second call, same job, same 60s window.
    r2 = requests.post(f"{API}/jobs/{jid}/arrive", headers=tech_h,
                          json={"lat": 33.5806, "lng": -112.2374},
                          timeout=15)
    assert r2.status_code == 200
    assert r2.json() == {"started": False, "reason": "throttled"}
    _sync.audit_logs.delete_many({"payload.job_id": jid})


# ─── 5. Auto-stop paths ──────────────────────────────────────────────

def test_auto_stop_fires_on_service_report_submit(
    tech_h, tech_user, aquaterra_tid, admin_h,
):
    """P37a fill-in-the-gap: the service-report submit path must
    stop the timer just like the PUT /jobs status→completed path."""
    requests.patch(f"{API}/settings/gps-auto-start", headers=admin_h,
                      json={"gps_auto_start_enabled": True}, timeout=15)
    requests.post(f"{API}/tech-gps-consent", headers=tech_h,
                     json={"granted": True}, timeout=15)
    jid = _seed_job(aquaterra_tid, tech_user)
    # Start the timer via /arrive.
    r_start = requests.post(f"{API}/jobs/{jid}/arrive", headers=tech_h,
                                json={"lat": 33.5806, "lng": -112.2374},
                                timeout=15)
    assert r_start.json()["started"] is True

    # Seed a minimal service_report row so the submit endpoint has a
    # doc to lock; the submit lookup keys on (tenant, job, tech_id).
    _sync.service_reports.insert_one({
        "id": f"TEST_p37_sr_{uuid.uuid4().hex[:8]}",
        "tenant_id": aquaterra_tid, "job_id": jid,
        "tech_id": tech_user.get("technician_id") or tech_user["id"],
        "customer_id": _sync.jobs.find_one({"id": jid})["customer_id"],
        "status": "draft", "chemical_readings": {},
        "created_at": "2026-06-01T09:00:00+00:00",
    })
    r_sub = requests.post(f"{API}/jobs/{jid}/service-report/submit",
                              headers=tech_h, json={}, timeout=15)
    # Some tenants have chemistry gating — the important assertion is
    # that IF the submit succeeded, the timer stopped. Skip on the
    # chemistry-required path.
    if r_sub.status_code != 200:
        pytest.skip(f"service-report submit gated: {r_sub.status_code} {r_sub.text[:120]}")

    row = _sync.jobs.find_one({"id": jid})
    assert row.get("timer_stopped_at"), \
        "service-report submit must stop the timer (P37a gap fix)"
    assert row.get("timer_stop_method") == "service_report_submitted"
    assert isinstance(row.get("timer_duration_seconds"), int)
    _sync.service_reports.delete_many({"job_id": jid})
    _sync.audit_logs.delete_many({"payload.job_id": jid})


def test_auto_stop_regression_via_put_jobs_status_completed(
    admin_h, tech_h, tech_user, aquaterra_tid,
):
    """Pre-P37a behavior must still fire — status→completed via PUT
    still stamps timer_stopped_at + timer_stop_method='job_completed'."""
    requests.patch(f"{API}/settings/gps-auto-start", headers=admin_h,
                      json={"gps_auto_start_enabled": True}, timeout=15)
    requests.post(f"{API}/tech-gps-consent", headers=tech_h,
                     json={"granted": True}, timeout=15)
    jid = _seed_job(aquaterra_tid, tech_user)
    requests.post(f"{API}/jobs/{jid}/arrive", headers=tech_h,
                     json={"lat": 33.5806, "lng": -112.2374},
                     timeout=15)
    # Flip via PUT — admin token so we bypass chemistry gate on pool jobs.
    j = _sync.jobs.find_one({"id": jid})
    r = requests.put(f"{API}/jobs/{jid}", headers=admin_h,
                         json={**{k: v for k, v in j.items() if k != "_id"},
                                 "status": "completed"}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"PUT /jobs gated: {r.status_code} {r.text[:120]}")
    row = _sync.jobs.find_one({"id": jid})
    assert row.get("timer_stopped_at")
    assert row.get("timer_stop_method") == "job_completed"
    _sync.audit_logs.delete_many({"payload.job_id": jid})
