"""Phase 34f — Active/Inactive customer toggle + auto-cancel cascade."""
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH  = {"email": "mike@aquaterra.com",  "password": "password123"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def tech_tok():
    return _login(TECH)


def _mk_name():
    return f"TEST-active-{uuid.uuid4().hex[:8]}"


def _iso(delta_days=0):
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).strftime("%Y-%m-%d")


def _cleanup_customer(tok, cid, job_ids=()):
    for jid in job_ids:
        requests.delete(f"{API}/jobs/{jid}", headers=_auth(tok), timeout=15)
    if cid:
        requests.delete(f"{API}/customers/{cid}", headers=_auth(tok), timeout=15)


def _seed(tok, *, future=1, past=0, auto_recurring=False, with_customer_kwargs=None):
    """Create a customer + N future scheduled jobs + M past completed jobs."""
    body = {"name": _mk_name()}
    if with_customer_kwargs:
        body.update(with_customer_kwargs)
    c = requests.post(f"{API}/customers", json=body,
                       headers=_auth(tok), timeout=15).json()
    cid = c["id"]
    job_ids = []
    for i in range(future):
        j = requests.post(f"{API}/jobs",
                           json={"title": f"future {i}",
                                  "customer_id": cid,
                                  "scheduled_date": _iso(7 + i),
                                  "status": "scheduled"},
                           headers=_auth(tok), timeout=15).json()
        job_ids.append(j["id"])
    for i in range(past):
        j = requests.post(f"{API}/jobs",
                           json={"title": f"past {i}",
                                  "customer_id": cid,
                                  "scheduled_date": _iso(-14 - i),
                                  "status": "completed"},
                           headers=_auth(tok), timeout=15).json()
        job_ids.append(j["id"])
    if auto_recurring and job_ids:
        # Flip auto_recurring on the first future job to simulate a
        # Phase-20 recurring instance.
        requests.put(f"{API}/jobs/{job_ids[0]}",
                     json={"auto_recurring": True},
                     headers=_auth(tok), timeout=15)
    return cid, job_ids


# --------------------------------------------------------------------------
def test_default_customer_is_active(admin_tok):
    r = requests.post(f"{API}/customers", json={"name": _mk_name()},
                       headers=_auth(admin_tok), timeout=15)
    assert r.status_code == 200
    cid = r.json()["id"]
    try:
        assert r.json().get("is_active") is True
    finally:
        _cleanup_customer(admin_tok, cid)


def test_deactivate_cancels_future_jobs(admin_tok):
    cid, jobs = _seed(admin_tok, future=3, past=0)
    try:
        # Flip is_active → false via full-body PUT.
        r = requests.put(f"{API}/customers/{cid}",
                          json={"name": "test", "is_active": False},
                          headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("is_active") is False
        assert body.get("cancelled_job_count") == 3, body
        # All three jobs now cancelled.
        for jid in jobs:
            j = requests.get(f"{API}/jobs/{jid}", headers=_auth(admin_tok), timeout=15).json()
            assert j["status"] == "cancelled", j
            assert j.get("cancellation_reason") == "Customer marked inactive"
            assert j.get("cancelled_at") is not None
            assert j.get("cancelled_by_user_id") is not None
    finally:
        _cleanup_customer(admin_tok, cid, jobs)


def test_past_completed_jobs_untouched(admin_tok):
    """Historical + in-progress jobs must NOT be touched by the cascade."""
    cid, jobs = _seed(admin_tok, future=1, past=2)
    future_id = jobs[0]
    past_ids = jobs[1:]
    try:
        r = requests.put(f"{API}/customers/{cid}",
                          json={"name": "test", "is_active": False},
                          headers=_auth(admin_tok), timeout=15).json()
        assert r["cancelled_job_count"] == 1  # only the future job
        # Future job cancelled.
        fj = requests.get(f"{API}/jobs/{future_id}", headers=_auth(admin_tok), timeout=15).json()
        assert fj["status"] == "cancelled"
        # Past completed jobs still say "completed".
        for jid in past_ids:
            pj = requests.get(f"{API}/jobs/{jid}", headers=_auth(admin_tok), timeout=15).json()
            assert pj["status"] == "completed", pj
    finally:
        _cleanup_customer(admin_tok, cid, jobs)


def test_reactivate_does_not_restore_cancelled(admin_tok):
    cid, jobs = _seed(admin_tok, future=2, past=0)
    try:
        requests.put(f"{API}/customers/{cid}",
                     json={"name": "test", "is_active": False},
                     headers=_auth(admin_tok), timeout=15)
        # Reactivate.
        r = requests.put(f"{API}/customers/{cid}",
                          json={"name": "test", "is_active": True},
                          headers=_auth(admin_tok), timeout=15).json()
        assert r["is_active"] is True
        assert "cancelled_job_count" not in r  # only present on the flip-off
        # Cancelled jobs remain cancelled.
        for jid in jobs:
            j = requests.get(f"{API}/jobs/{jid}", headers=_auth(admin_tok), timeout=15).json()
            assert j["status"] == "cancelled"
    finally:
        _cleanup_customer(admin_tok, cid, jobs)


def test_activation_events_logged(admin_tok):
    cid, jobs = _seed(admin_tok, future=1)
    try:
        requests.put(f"{API}/customers/{cid}",
                     json={"name": "test", "is_active": False},
                     headers=_auth(admin_tok), timeout=15)
        requests.put(f"{API}/customers/{cid}",
                     json={"name": "test", "is_active": True},
                     headers=_auth(admin_tok), timeout=15)
        # Two events should exist: active→inactive and inactive→active.
        # No public endpoint yet — verify via direct mongo through the
        # existing motor connection used by conftest fixtures. Fall back
        # to skipping if we can't reach the driver from the test process.
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from config import db
            import asyncio
            docs = asyncio.get_event_loop().run_until_complete(
                db.customer_activation_events.find({"customer_id": cid}).to_list(10)
            )
            assert len(docs) >= 2, docs
            transitions = {(d["from_status"], d["to_status"]) for d in docs}
            assert ("active", "inactive") in transitions
            assert ("inactive", "active") in transitions
            # The deactivation event should carry the counts.
            deact = [d for d in docs if d["to_status"] == "inactive"][0]
            assert deact["cancelled_job_count"] == 1
        except (ImportError, RuntimeError):
            pytest.skip("motor driver unreachable from test process")
    finally:
        _cleanup_customer(admin_tok, cid, jobs)


def test_deactivation_preview(admin_tok):
    cid, jobs = _seed(admin_tok, future=2, past=1)
    try:
        r = requests.get(f"{API}/customers/{cid}/deactivation-preview",
                          headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["future_job_count"] == 2
        assert "recurring_template_count" in p
    finally:
        _cleanup_customer(admin_tok, cid, jobs)


def test_preview_404_unknown_customer(admin_tok):
    r = requests.get(f"{API}/customers/nonexistent-abc/deactivation-preview",
                      headers=_auth(admin_tok), timeout=15)
    assert r.status_code == 404


def test_non_admin_forbidden(tech_tok, admin_tok):
    # Seed with admin, then attempt access with tech.
    cid, jobs = _seed(admin_tok, future=1)
    try:
        r1 = requests.get(f"{API}/customers/{cid}/deactivation-preview",
                           headers=_auth(tech_tok), timeout=15)
        assert r1.status_code == 403
        r2 = requests.put(f"{API}/customers/{cid}",
                           json={"name": "test", "is_active": False},
                           headers=_auth(tech_tok), timeout=15)
        assert r2.status_code == 403
    finally:
        _cleanup_customer(admin_tok, cid, jobs)
