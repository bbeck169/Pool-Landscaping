"""Feb-2026 · Widget Embed extension · auto-enqueue contract."""
from __future__ import annotations

import asyncio

from services import public_checkin_enqueue as pce
from tests._notif_pipeline_fakes import _DB, _Coll


def _db(**kwargs):
    """_DB from notification-bundle fakes lacks the public_checkins /
    audit_logs collections we need here. Return a _DB with those
    stubs attached."""
    fake = _DB(**kwargs)
    fake.public_checkins = _Coll()
    fake.audit_logs = _Coll()
    return fake


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_auto_enqueue_on_completed_job_inserts_row(monkeypatch):
    fake = _db(
        customers=[{"id": "c1", "tenant_id": "t1",
                     "latitude": 33.5722, "longitude": -112.3237,
                     "city": "Peoria", "state": "AZ"}],
        tenants=[{"id": "t1", "settings": {}}],
    )
    monkeypatch.setattr(pce, "db", fake)

    result = _run(pce.enqueue_public_checkin_for_completed_job(
        {"id": "j1", "tenant_id": "t1", "customer_id": "c1",
         "service_type": "Pool Cleaning",
         "completed_at": "2026-08-01T10:00:00Z"},
        actor_user_id="admin",
    ))
    assert result["enqueued"] is True
    assert len(fake.public_checkins.rows) == 1
    row = fake.public_checkins.rows[0]
    assert row["state"] == "pending_review"
    assert row["source"] == "auto"
    assert row["source_job_id"] == "j1"
    assert row["service_name"] == "Pool Cleaning"
    # Obfuscated coords stamped.
    assert row["lat_public"] is not None
    assert abs(row["lat_public"] - 33.5722) <= 0.001
    assert row["lng_public"] is not None
    assert abs(row["lng_public"] - (-112.3237)) <= 0.001
    # Raw coords ALSO stamped (admin view only).
    assert row["lat_raw"] == 33.5722
    assert row["lng_raw"] == -112.3237
    assert row["area_label"] == "Peoria, AZ"
    assert row["completed_at_month_year"] == "August 2026"


def test_second_completion_of_same_job_is_no_op(monkeypatch):
    """Re-flip on the same job → idempotent. Even if a customer or
    tech re-completes, only one moderation row exists."""
    fake = _db(
        customers=[{"id": "c1", "tenant_id": "t1",
                     "latitude": 33.5, "longitude": -112.0}],
        tenants=[{"id": "t1", "settings": {}}],
    )
    monkeypatch.setattr(pce, "db", fake)

    r1 = _run(pce.enqueue_public_checkin_for_completed_job(
        {"id": "j1", "tenant_id": "t1", "customer_id": "c1"},
    ))
    r2 = _run(pce.enqueue_public_checkin_for_completed_job(
        {"id": "j1", "tenant_id": "t1", "customer_id": "c1"},
    ))
    assert r1["enqueued"] is True
    assert r2["enqueued"] is False
    assert r2["reason"] == "already_enqueued"
    assert len(fake.public_checkins.rows) == 1


def test_tenant_setting_off_skips_enqueue(monkeypatch):
    fake = _db(
        customers=[{"id": "c1", "tenant_id": "t1",
                     "latitude": 33.0, "longitude": -112.0}],
        tenants=[{"id": "t1",
                    "settings": {"auto_enqueue_public_checkins": False}}],
    )
    monkeypatch.setattr(pce, "db", fake)

    result = _run(pce.enqueue_public_checkin_for_completed_job(
        {"id": "j1", "tenant_id": "t1", "customer_id": "c1"},
    ))
    assert result["enqueued"] is False
    assert result["reason"] == "tenant_setting_off"
    assert fake.public_checkins.rows == []


def test_setting_unset_defaults_to_enabled(monkeypatch):
    """Missing ``auto_enqueue_public_checkins`` key → treat as
    True. Backwards-compat with the existing MR0/MR1/MR2 tenant
    corpus."""
    fake = _db(
        customers=[{"id": "c1", "tenant_id": "t1",
                     "latitude": 33.0, "longitude": -112.0}],
        tenants=[{"id": "t1", "settings": {"other": "value"}}],
    )
    monkeypatch.setattr(pce, "db", fake)

    result = _run(pce.enqueue_public_checkin_for_completed_job(
        {"id": "j1", "tenant_id": "t1", "customer_id": "c1"},
    ))
    assert result["enqueued"] is True


def test_customer_missing_geocode_skips_without_error(monkeypatch):
    """No lat/lng on the customer → skip enqueue, don't crash the
    PATCH request. Phase-17 geocoding will backfill eventually
    and a subsequent completion (rare) or manual submit-public
    can populate the row."""
    fake = _db(
        customers=[{"id": "c1", "tenant_id": "t1",
                     "city": "Peoria", "state": "AZ"}],
        tenants=[{"id": "t1", "settings": {}}],
    )
    monkeypatch.setattr(pce, "db", fake)

    result = _run(pce.enqueue_public_checkin_for_completed_job(
        {"id": "j1", "tenant_id": "t1", "customer_id": "c1"},
    ))
    assert result["enqueued"] is False
    assert result["reason"] == "no_customer_coords"
    assert fake.public_checkins.rows == []


def test_no_tenant_id_short_circuits(monkeypatch):
    fake = _db(customers=[], tenants=[])
    monkeypatch.setattr(pce, "db", fake)
    result = _run(pce.enqueue_public_checkin_for_completed_job(
        {"id": "j1"},
    ))
    assert result["enqueued"] is False
    assert result["reason"] == "missing_ids"
