"""Feb-2026 · MARCO Proactive Alerts — Phase B tests.

Covers:
  (a) Each of the 5 detectors fires correctly against seeded data.
  (b) ``upsert_alert`` dedup — second sweep bumps ``last_seen_at``
      and does NOT insert a duplicate row.
  (c) ``upsert_alert`` severity escalation — warn → error upgrade
      clears any prior ack so the admin re-sees the row.
  (d) ``auto_resolve_alert`` dismisses matching active rows.
  (e) HTTP: ``GET /ai/marco/alerts`` + ``/count`` return the right
      shape; role gate honours admin / manager; technician 403.
  (f) HTTP: ``POST /acknowledge`` sets ack fields; dismiss removes
      the row from the active list.
  (g) Tenant isolation — tenant A cannot see / modify tenant B
      alerts (dismiss 404s cross-tenant).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

from tests._shared_mongo import shared_db
from tests._phase34_asyncio import batch_safe_run as _run


def _async_db():
    """Return the motor async db bound to the batch-safe loop so our
    detector/service calls that use ``await db.<coll>.find_one(...)``
    actually succeed.  ``shared_db()`` returns a *sync* pymongo
    handle used only for pre-seeding + post-cleanup rows the HTTP
    layer never sees."""
    from config import db as _d
    return _d


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _resolve_tenant_id() -> str:
    """Pull the live tenant_id for the admin seed via the manual
    sweep endpoint (which echoes ``tenant_id`` on success)."""
    tok = _login("admin@aquaterra.com")
    r = requests.post(
        f"{API}/ai/marco/alerts/sweep",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    tid = r.json().get("tenant_id")
    assert tid, "sweep did not return tenant_id"
    return tid


TENANT = _resolve_tenant_id()


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def manager_headers():
    try:
        tok = _login("manager@aquaterra.com")
    except AssertionError:
        pytest.skip("manager@aquaterra.com not seeded")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def tech_headers():
    for em in ("mike@aquaterra.com", "landscaper@aquaterra.com"):
        try:
            return {"Authorization": f"Bearer {_login(em)}"}
        except AssertionError:
            continue
    pytest.skip("no technician seed available")


# Fresh tenant_id per module run — prevents residual rows from
# leaking into other tests (and the module cleans up its own
# rows in the fixture teardown).
_TEST_SCOPE = f"TEST_MARCO_ALERTS_{uuid.uuid4().hex[:8]}"


def _cleanup():
    db = shared_db()
    db.marco_alerts.delete_many({"tenant_id": TENANT,
                                   "body": {"$regex": _TEST_SCOPE}})
    db.marco_alerts.delete_many({"tenant_id": TENANT,
                                   "title": {"$regex": _TEST_SCOPE}})
    db.quotes.delete_many({"tenant_id": TENANT,
                            "invoice_number": {"$regex": _TEST_SCOPE}})
    db.jobs.delete_many({"tenant_id": TENANT,
                          "title": {"$regex": _TEST_SCOPE}})
    db.time_entries.delete_many({"tenant_id": TENANT,
                                   "notes": {"$regex": _TEST_SCOPE}})
    db.payment_events.delete_many({"tenant_id": TENANT,
                                     "reason": {"$regex": _TEST_SCOPE}})
    db.comms_send_log.delete_many({"tenant_id": TENANT,
                                     "error": {"$regex": _TEST_SCOPE}})


@pytest.fixture(scope="module", autouse=True)
def _seed_and_cleanup():
    _cleanup()
    yield
    _cleanup()


def _past_iso(days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    t = datetime.now(timezone.utc) - timedelta(days=days, hours=hours, minutes=minutes)
    return t.isoformat().replace("+00:00", "Z")


# ══════════════════════════════════════════════════════════════════
# (a)-(d) Direct service tests.
# ══════════════════════════════════════════════════════════════════


def test_detect_overdue_invoices_severity_warn_vs_error():
    """1-7d overdue → warn, >7d overdue → error."""
    db = shared_db()
    inv_warn = f"TEST_INV_WARN_{uuid.uuid4().hex[:8]}"
    inv_error = f"TEST_INV_ERROR_{uuid.uuid4().hex[:8]}"
    db.quotes.insert_many([
        {
            "id": inv_warn, "tenant_id": TENANT, "doc_type": "invoice",
            "invoice_number": f"{_TEST_SCOPE}-W",
            "payment_status": "unpaid", "total": 100, "amount_paid": 0,
            "due_date": _past_iso(days=3),
            "customer_name": "Warn Customer",
            "created_at": _past_iso(days=5),
        },
        {
            "id": inv_error, "tenant_id": TENANT, "doc_type": "invoice",
            "invoice_number": f"{_TEST_SCOPE}-E",
            "payment_status": "unpaid", "total": 500, "amount_paid": 0,
            "due_date": _past_iso(days=14),
            "customer_name": "Error Customer",
            "created_at": _past_iso(days=20),
        },
    ])
    try:
        from services.marco_alerts import detect_overdue_invoices
        alerts = _run(detect_overdue_invoices(_async_db(), TENANT))
        found = {a["entity_ref"]["id"]: a for a in alerts
                 if a["entity_ref"]["id"] in (inv_warn, inv_error)}
        assert set(found.keys()) == {inv_warn, inv_error}, found
        assert found[inv_warn]["severity"] == "warn"
        assert found[inv_error]["severity"] == "error"
    finally:
        db.quotes.delete_many({"id": {"$in": [inv_warn, inv_error]}})


def test_detect_unassigned_jobs_today_vs_tomorrow():
    db = shared_db()
    today_iso = datetime.now(timezone.utc).date().isoformat()
    tomorrow_iso = (datetime.now(timezone.utc).date()
                     + timedelta(days=1)).isoformat()
    job_today = f"TEST_JOB_TODAY_{uuid.uuid4().hex[:8]}"
    job_tomorrow = f"TEST_JOB_TOMORROW_{uuid.uuid4().hex[:8]}"
    db.jobs.insert_many([
        {"id": job_today, "tenant_id": TENANT,
         "title": f"{_TEST_SCOPE} today job", "status": "scheduled",
         "scheduled_start": f"{today_iso}T14:00:00+00:00",
         "crew_id": None, "technician_id": None,
         "customer_name": "C1"},
        {"id": job_tomorrow, "tenant_id": TENANT,
         "title": f"{_TEST_SCOPE} tomorrow job", "status": "scheduled",
         "scheduled_start": f"{tomorrow_iso}T09:00:00+00:00",
         "crew_id": None, "technician_id": None,
         "customer_name": "C2"},
    ])
    try:
        from services.marco_alerts import detect_unassigned_jobs
        alerts = _run(detect_unassigned_jobs(_async_db(), TENANT))
        by_id = {a["entity_ref"]["id"]: a for a in alerts}
        assert job_today in by_id and job_tomorrow in by_id
        assert by_id[job_today]["severity"] == "error"
        assert by_id[job_tomorrow]["severity"] == "warn"
    finally:
        db.jobs.delete_many({"id": {"$in": [job_today, job_tomorrow]}})


def test_detect_missing_clock_ins():
    """A job scheduled 20 min ago with an assigned tech but no
    ``time_entries.clock_in_at`` row fires."""
    db = shared_db()
    today = datetime.now(timezone.utc).date().isoformat()
    past = _past_iso(minutes=25)
    job_id = f"TEST_JOB_NOCLOCK_{uuid.uuid4().hex[:8]}"
    db.jobs.insert_one({
        "id": job_id, "tenant_id": TENANT,
        "title": f"{_TEST_SCOPE} no-clock-in job",
        "status": "scheduled",
        "scheduled_start": past,
        "scheduled_date": today,
        "technician_id": "tech-1", "crew_id": None,
        "customer_name": "Clock Customer",
    })
    try:
        from services.marco_alerts import detect_missing_clock_ins
        alerts = _run(detect_missing_clock_ins(_async_db(), TENANT))
        assert any(a["entity_ref"]["id"] == job_id for a in alerts), alerts
    finally:
        db.jobs.delete_one({"id": job_id})


def test_detect_payment_failures():
    db = shared_db()
    inv_id = f"TEST_INV_FAIL_{uuid.uuid4().hex[:8]}"
    db.payment_events.insert_one({
        "id": uuid.uuid4().hex,
        "tenant_id": TENANT,
        "event": "payment_failed",
        "entity_id": inv_id,
        "invoice_id": inv_id,
        "reason": f"{_TEST_SCOPE} card_declined",
        "amount_cents": 25000,
        "created_at": _past_iso(hours=2),
    })
    try:
        from services.marco_alerts import detect_payment_failures
        alerts = _run(detect_payment_failures(_async_db(), TENANT))
        assert any(a["entity_ref"]["id"] == inv_id for a in alerts), alerts
    finally:
        db.payment_events.delete_many({"tenant_id": TENANT,
                                         "entity_id": inv_id})


def test_detect_sms_failures_collapses_to_single_tenant_alert():
    db = shared_db()
    # Seed 3 failed sms rows → should collapse to 1 alert.
    for _i in range(3):
        db.comms_send_log.insert_one({
            "id": uuid.uuid4().hex, "tenant_id": TENANT,
            "channel": "sms", "ok": False,
            "was_mock": False,
            "provider_status": "failed",
            "error": f"{_TEST_SCOPE} network_timeout",
            "at": _past_iso(hours=1),
        })
    try:
        from services.marco_alerts import detect_sms_failures
        alerts = _run(detect_sms_failures(_async_db(), TENANT))
        assert len(alerts) == 1, alerts
        assert "3" in alerts[0]["title"] or alerts[0]["title"].startswith("3 ")
    finally:
        db.comms_send_log.delete_many({"tenant_id": TENANT,
                                         "error": {"$regex": _TEST_SCOPE}})


def test_upsert_dedup_and_severity_escalation():
    db = shared_db()
    inv_id = f"TEST_INV_UPSERT_{uuid.uuid4().hex[:8]}"
    from services.marco_alerts import (
        upsert_alert, auto_resolve_alert,
        MARCO_ALERT_KIND_OVERDUE_INVOICE,
    )
    entity = {"type": "invoice", "id": inv_id}
    try:
        # First call — warn.  Insert.
        r1 = _run(upsert_alert(
            _async_db(), tenant_id=TENANT,
            kind=MARCO_ALERT_KIND_OVERDUE_INVOICE,
            severity="warn", title=f"{_TEST_SCOPE} invoice overdue",
            body="$100", entity_ref=entity,
        ))
        aid = r1["id"]
        # Admin acks it.
        db.marco_alerts.update_one(
            {"id": aid, "tenant_id": TENANT},
            {"$set": {"acknowledged_at": _past_iso(hours=1),
                       "acknowledged_by": "u1"}},
        )

        # Second call — same severity → bumps last_seen_at only, no dup.
        r2 = _run(upsert_alert(
            _async_db(), tenant_id=TENANT,
            kind=MARCO_ALERT_KIND_OVERDUE_INVOICE,
            severity="warn", title=f"{_TEST_SCOPE} invoice overdue",
            body="$100", entity_ref=entity,
        ))
        assert r2["id"] == aid
        count = db.marco_alerts.count_documents(
            {"tenant_id": TENANT, "dedup_key":
             f"{MARCO_ALERT_KIND_OVERDUE_INVOICE}:invoice:{inv_id}",
             "dismissed_at": None},
        )
        assert count == 1

        # Third call — escalate warn → error → ack is cleared.
        _run(upsert_alert(
            _async_db(), tenant_id=TENANT,
            kind=MARCO_ALERT_KIND_OVERDUE_INVOICE,
            severity="error", title=f"{_TEST_SCOPE} invoice overdue",
            body="$100 (14d)", entity_ref=entity,
        ))
        row = db.marco_alerts.find_one({"id": aid})
        assert row["severity"] == "error"
        assert row.get("acknowledged_at") is None
        assert row.get("acknowledged_by") is None

        # auto_resolve clears it.
        modified = _run(auto_resolve_alert(
            _async_db(), tenant_id=TENANT,
            kind=MARCO_ALERT_KIND_OVERDUE_INVOICE,
            entity_ref=entity, reason="paid",
        ))
        assert modified == 1
        row2 = db.marco_alerts.find_one({"id": aid})
        assert row2.get("dismissed_at")
        assert row2.get("dismissed_by", "").startswith("system:")
    finally:
        db.marco_alerts.delete_many({"tenant_id": TENANT,
                                       "entity_ref.id": inv_id})


# ══════════════════════════════════════════════════════════════════
# (e)-(g) HTTP tests.
# ══════════════════════════════════════════════════════════════════


def test_role_gate_tech_forbidden(tech_headers):
    r = requests.get(f"{API}/ai/marco/alerts",
                     headers=tech_headers, timeout=15)
    assert r.status_code in (401, 403), r.text
    r = requests.get(f"{API}/ai/marco/alerts/count",
                     headers=tech_headers, timeout=15)
    assert r.status_code in (401, 403), r.text


def test_manager_can_list_and_count(manager_headers):
    r = requests.get(f"{API}/ai/marco/alerts",
                     headers=manager_headers, timeout=15)
    assert r.status_code == 200, r.text
    r = requests.get(f"{API}/ai/marco/alerts/count",
                     headers=manager_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {"total", "by_severity", "by_kind"}


def test_acknowledge_and_dismiss_lifecycle(admin_headers):
    db = shared_db()
    aid = uuid.uuid4().hex[:24]
    db.marco_alerts.insert_one({
        "id": aid, "tenant_id": TENANT,
        "kind": "overdue_invoice", "severity": "warn",
        "title": f"{_TEST_SCOPE} lifecycle alert",
        "body": "test body",
        "entity_ref": {"type": "invoice", "id": "x"},
        "dedup_key": f"overdue_invoice:invoice:x-{aid}",
        "acknowledged_at": None, "acknowledged_by": None,
        "dismissed_at": None, "dismissed_by": None,
        "created_at": _past_iso(), "last_seen_at": _past_iso(),
    })
    try:
        # Ack.
        r = requests.post(
            f"{API}/ai/marco/alerts/{aid}/acknowledge",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["acknowledged_at"]
        assert body["acknowledged_by"]
        assert body["dismissed_at"] is None

        # Dismiss.
        r = requests.post(
            f"{API}/ai/marco/alerts/{aid}/dismiss",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["dismissed_at"]
        assert body["dismissed_by"]

        # No longer in active list.
        r = requests.get(f"{API}/ai/marco/alerts",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200
        active_ids = [a["id"] for a in r.json()]
        assert aid not in active_ids
    finally:
        db.marco_alerts.delete_one({"id": aid})


def test_tenant_isolation_dismiss_404(admin_headers):
    """A row that belongs to another tenant must 404."""
    db = shared_db()
    aid = uuid.uuid4().hex[:24]
    other_tenant = f"test-other-{uuid.uuid4().hex[:6]}"
    db.marco_alerts.insert_one({
        "id": aid, "tenant_id": other_tenant,
        "kind": "overdue_invoice", "severity": "warn",
        "title": f"{_TEST_SCOPE} other-tenant",
        "body": "x",
        "entity_ref": {"type": "invoice", "id": "x"},
        "dedup_key": f"overdue_invoice:invoice:x-{aid}",
        "acknowledged_at": None, "acknowledged_by": None,
        "dismissed_at": None, "dismissed_by": None,
        "created_at": _past_iso(), "last_seen_at": _past_iso(),
    })
    try:
        r = requests.post(
            f"{API}/ai/marco/alerts/{aid}/dismiss",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 404
    finally:
        db.marco_alerts.delete_one({"id": aid})


def test_manual_sweep_admin_only(admin_headers, manager_headers):
    r = requests.post(f"{API}/ai/marco/alerts/sweep",
                       headers=manager_headers, timeout=20)
    assert r.status_code in (401, 403), r.text
    r = requests.post(f"{API}/ai/marco/alerts/sweep",
                       headers=admin_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {"tenant_id", "inserted", "updated", "by_kind"}
