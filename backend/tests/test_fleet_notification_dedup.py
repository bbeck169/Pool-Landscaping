"""FLEET-A · Notification pipeline dedup tests.

``services.fleet.notifications.maybe_send_on_the_way`` fires the
"tech is on the way" SYSTEM-context email + SMS. Dedup window is
4 h per ``(tech_user_id, job_id)``. Coverage:

  * Second send inside the 4 h window is skipped as
    ``dedup_within_window``; no comms adapter fired.
  * Missing job / customer returns ``missing_context`` without
    invoking the adapters.
  * Missing coordinates (job or tech) returns ``missing_coordinates``.
  * ETA > 15 min → skip with ``eta_too_far``.
  * Successful send calls ``send_email`` + ``send_sms`` with
    ``context=CommsContext.SYSTEM`` — the SAFE-SEND guarantee.
  * Opt-outs honoured — ``sms_opt_in=False`` skips SMS, ``email``
    still fires.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest

from backend.tests._fleet_helpers import _DB, run


@pytest.fixture
def fake_db(monkeypatch):
    fake = _DB()
    fake.jobs.rows = [
        {"id": "job-1", "tenant_id": "t1", "customer_id": "cust-1",
         "title": "Weekly", "service_address": "123 Main",
         "latitude": 33.8, "longitude": -112.32},
        {"id": "job-far", "tenant_id": "t1", "customer_id": "cust-1",
         "title": "Far away", "service_address": "999 Far",
         "latitude": 40.0, "longitude": -120.0},                # ~1000 km
        {"id": "job-no-coords", "tenant_id": "t1",
         "customer_id": "cust-1", "title": "no coords"},
    ]
    fake.customers.rows = [
        {"id": "cust-1", "tenant_id": "t1", "name": "Jane H.",
         "email": "jane@example.com", "email_opt_in": True,
         "phone": "+16025551234", "sms_opt_in": True},
    ]
    fake.tenants.rows = [
        {"id": "t1", "name": "AquaTerra"},
    ]
    fake.users.rows = [
        {"id": "u-tech", "tenant_id": "t1", "name": "Tom Tech"},
    ]
    for mod_name in ["services.fleet.notifications"]:
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "db", fake, raising=False)
    return fake


@pytest.fixture
def stub_eta_close(monkeypatch):
    """Force ETA to ~5 min so the send is inside the 15-min gate."""
    from services.fleet import eta
    from services.fleet import notifications

    async def _fake(*a, **kw):
        return eta.ETAResult(
            provider="crowflies", distance_m=1000, duration_s=300,
        )

    monkeypatch.setattr(notifications, "compute_eta", _fake,
                        raising=True)


@pytest.fixture
def stub_adapters(monkeypatch):
    """Capture every call to send_email / send_sms."""
    from services.fleet import notifications
    from services.comms_env_guard import CommsContext

    calls = {"email": [], "sms": []}

    async def _email(**kwargs):
        calls["email"].append(kwargs)
        return {"status": "sent", "provider_id": "resend_x"}

    async def _sms(**kwargs):
        calls["sms"].append(kwargs)
        return {"status": "sent", "provider_id": "rc_x"}

    monkeypatch.setattr(notifications, "send_email", _email,
                        raising=True)
    monkeypatch.setattr(notifications, "send_sms", _sms,
                        raising=True)
    return calls, CommsContext


# ─── happy path ─────────────────────────────────────────────────────

def test_first_send_dispatches_email_and_sms(fake_db, stub_eta_close,
                                                stub_adapters):
    from services.fleet import notifications
    calls, CommsContext = stub_adapters

    outcome = run(notifications.maybe_send_on_the_way(
        tenant_id="t1", tech_user_id="u-tech", job_id="job-1",
        tech_lat=33.7897, tech_lng=-112.3226,
    ))
    assert outcome.sent is True
    assert outcome.reason == "sent"
    assert outcome.provider == "crowflies"
    assert outcome.eta_minutes == 5
    # Both channels fired.
    assert len(calls["email"]) == 1
    assert len(calls["sms"]) == 1
    # ****Critical**** — every send is context=SYSTEM.
    assert calls["email"][0]["context"] == CommsContext.SYSTEM
    assert calls["sms"][0]["context"] == CommsContext.SYSTEM
    # Recipients wired correctly.
    assert calls["email"][0]["to_email"] == "jane@example.com"
    assert calls["sms"][0]["to_phone"] == "+16025551234"
    # Dedup row written.
    assert len(fake_db.fleet_notification_dedup.rows) == 1


# ─── Dedup window ──────────────────────────────────────────────────

def test_second_send_within_4h_is_deduped(fake_db, stub_eta_close,
                                             stub_adapters):
    from services.fleet import notifications
    calls, _ = stub_adapters

    run(notifications.maybe_send_on_the_way(
        tenant_id="t1", tech_user_id="u-tech", job_id="job-1",
        tech_lat=33.7897, tech_lng=-112.3226,
    ))
    outcome = run(notifications.maybe_send_on_the_way(
        tenant_id="t1", tech_user_id="u-tech", job_id="job-1",
        tech_lat=33.7897, tech_lng=-112.3226,
    ))
    assert outcome.sent is False
    assert outcome.reason == "dedup_within_window"
    # Adapters called only once — the second attempt was skipped.
    assert len(calls["email"]) == 1
    assert len(calls["sms"]) == 1
    # No extra dedup row inserted on the second attempt.
    assert len(fake_db.fleet_notification_dedup.rows) == 1


def test_dedup_expires_after_window(fake_db, stub_eta_close,
                                      stub_adapters):
    from services.fleet import notifications
    calls, _ = stub_adapters

    # Seed a stale dedup row from >4h ago.
    stale = datetime.now(timezone.utc) - timedelta(hours=5)
    fake_db.fleet_notification_dedup.rows = [{
        "id": "dedup-old", "tenant_id": "t1", "tech_user_id": "u-tech",
        "job_id": "job-1",
        "sent_at": stale.isoformat().replace("+00:00", "Z"),
        "sent_at_dt": stale,
    }]
    outcome = run(notifications.maybe_send_on_the_way(
        tenant_id="t1", tech_user_id="u-tech", job_id="job-1",
        tech_lat=33.7897, tech_lng=-112.3226,
    ))
    assert outcome.sent is True
    assert len(calls["email"]) == 1


def test_dedup_scoped_per_job(fake_db, stub_eta_close, stub_adapters):
    """Two different job_ids do NOT share the dedup slot."""
    from services.fleet import notifications
    calls, _ = stub_adapters

    run(notifications.maybe_send_on_the_way(
        tenant_id="t1", tech_user_id="u-tech", job_id="job-1",
        tech_lat=33.7897, tech_lng=-112.3226,
    ))
    fake_db.jobs.rows.append({
        "id": "job-2", "tenant_id": "t1", "customer_id": "cust-1",
        "title": "Second stop", "service_address": "125 Main",
        "latitude": 33.81, "longitude": -112.32,
    })
    outcome = run(notifications.maybe_send_on_the_way(
        tenant_id="t1", tech_user_id="u-tech", job_id="job-2",
        tech_lat=33.7897, tech_lng=-112.3226,
    ))
    assert outcome.sent is True
    assert len(calls["email"]) == 2


# ─── Gates ──────────────────────────────────────────────────────────

def test_missing_job_short_circuits(fake_db, stub_eta_close, stub_adapters):
    from services.fleet import notifications
    calls, _ = stub_adapters
    outcome = run(notifications.maybe_send_on_the_way(
        tenant_id="t1", tech_user_id="u-tech", job_id="no-such",
        tech_lat=33.7897, tech_lng=-112.3226,
    ))
    assert outcome.sent is False
    assert outcome.reason == "missing_context"
    assert calls["email"] == []
    assert calls["sms"] == []


def test_missing_customer_short_circuits(fake_db, stub_eta_close,
                                           stub_adapters):
    from services.fleet import notifications
    calls, _ = stub_adapters
    # Wipe customer.
    fake_db.customers.rows = []
    outcome = run(notifications.maybe_send_on_the_way(
        tenant_id="t1", tech_user_id="u-tech", job_id="job-1",
        tech_lat=33.7897, tech_lng=-112.3226,
    ))
    assert outcome.reason == "missing_context"
    assert calls["email"] == []


def test_missing_coordinates(fake_db, stub_eta_close, stub_adapters):
    from services.fleet import notifications
    calls, _ = stub_adapters
    # Job has no coords.
    outcome = run(notifications.maybe_send_on_the_way(
        tenant_id="t1", tech_user_id="u-tech", job_id="job-no-coords",
        tech_lat=33.7897, tech_lng=-112.3226,
    ))
    assert outcome.reason == "missing_coordinates"
    assert calls["email"] == []


def test_eta_too_far_skips(fake_db, monkeypatch, stub_adapters):
    """Simulate ETA of 42 minutes — must skip."""
    from services.fleet import eta
    from services.fleet import notifications

    async def _fake(*a, **kw):
        return eta.ETAResult(
            provider="crowflies", distance_m=100000, duration_s=42 * 60,
        )

    monkeypatch.setattr(notifications, "compute_eta", _fake,
                        raising=True)
    calls, _ = stub_adapters
    outcome = run(notifications.maybe_send_on_the_way(
        tenant_id="t1", tech_user_id="u-tech", job_id="job-far",
        tech_lat=33.7897, tech_lng=-112.3226,
    ))
    assert outcome.sent is False
    assert outcome.reason == "eta_too_far"
    assert outcome.eta_minutes == 42
    assert calls["email"] == []
    assert calls["sms"] == []


# ─── Opt-outs ───────────────────────────────────────────────────────

def test_sms_opt_out_skips_only_sms(fake_db, stub_eta_close,
                                       stub_adapters):
    from services.fleet import notifications
    calls, _ = stub_adapters
    fake_db.customers.rows[0]["sms_opt_in"] = False
    outcome = run(notifications.maybe_send_on_the_way(
        tenant_id="t1", tech_user_id="u-tech", job_id="job-1",
        tech_lat=33.7897, tech_lng=-112.3226,
    ))
    assert outcome.sent is True
    # Email fired, SMS didn't.
    assert len(calls["email"]) == 1
    assert calls["sms"] == []
    assert outcome.channels["sms"]["status"] == "skipped_opt_out_or_missing"


def test_email_opt_out_skips_only_email(fake_db, stub_eta_close,
                                          stub_adapters):
    from services.fleet import notifications
    calls, _ = stub_adapters
    fake_db.customers.rows[0]["email_opt_in"] = False
    outcome = run(notifications.maybe_send_on_the_way(
        tenant_id="t1", tech_user_id="u-tech", job_id="job-1",
        tech_lat=33.7897, tech_lng=-112.3226,
    ))
    assert outcome.sent is True
    assert calls["email"] == []
    assert len(calls["sms"]) == 1
