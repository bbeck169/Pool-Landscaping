"""Feb-2026 · Widget Embed extension · source discriminator on
public_checkins rows.

Contract:
  * Auto-enqueued rows carry ``source='auto'``.
  * Existing tech-initiated submit-public rows still work — a new
    row inserted through the tech path carries ``source='tech'``
    (or ``None``, back-compat for pre-Feb-2026 rows) but MUST
    never be flipped to ``auto`` by any code path.
"""
from __future__ import annotations

import asyncio

from services import public_checkin_enqueue as pce
from tests._notif_pipeline_fakes import _DB, _Coll


def _db(**kwargs):
    fake = _DB(**kwargs)
    fake.public_checkins = _Coll()
    fake.audit_logs = _Coll()
    return fake


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_auto_enqueue_sets_source_auto(monkeypatch):
    fake = _db(
        customers=[{"id": "c1", "tenant_id": "t1",
                     "latitude": 33.0, "longitude": -112.0}],
        tenants=[{"id": "t1", "settings": {}}],
    )
    monkeypatch.setattr(pce, "db", fake)

    _run(pce.enqueue_public_checkin_for_completed_job(
        {"id": "j-auto", "tenant_id": "t1", "customer_id": "c1"},
    ))
    row = fake.public_checkins.rows[0]
    assert row["source"] == "auto"
    assert row["photo_license_ack"] is False   # no photos in auto path
    assert row["photos"] == []


def test_auto_enqueue_does_not_overwrite_existing_tech_row(monkeypatch):
    """If the tech has already submitted the check-in for this
    job, auto-enqueue MUST NOT re-flip the row or change its
    ``source`` field. Idempotency + preservation of the tech
    submission wins."""
    tech_row = {
        "id": "existing-1", "tenant_id": "t1",
        "source_job_id": "j1", "source": "tech",
        "state": "approved", "photos": [{"url": "x"}],
    }
    fake = _db(
        customers=[{"id": "c1", "tenant_id": "t1",
                     "latitude": 33.0, "longitude": -112.0}],
        tenants=[{"id": "t1", "settings": {}}],
    )
    fake.public_checkins.rows.append(tech_row)
    monkeypatch.setattr(pce, "db", fake)

    result = _run(pce.enqueue_public_checkin_for_completed_job(
        {"id": "j1", "tenant_id": "t1", "customer_id": "c1"},
    ))
    assert result["enqueued"] is False
    assert result["reason"] == "already_enqueued"
    assert result["existing_source"] == "tech"
    # Row is unchanged — same photo, still tech source.
    row = fake.public_checkins.rows[0]
    assert row["source"] == "tech"
    assert row["photos"] == [{"url": "x"}]


def test_area_label_falls_back_gracefully(monkeypatch):
    """Customer with only ``property.city`` (older schema) still
    produces a usable area label."""
    fake = _db(
        customers=[{"id": "c1", "tenant_id": "t1",
                     "latitude": 33.0, "longitude": -112.0,
                     "property": {"city": "Surprise", "state": "AZ"}}],
        tenants=[{"id": "t1", "settings": {}}],
    )
    monkeypatch.setattr(pce, "db", fake)

    _run(pce.enqueue_public_checkin_for_completed_job(
        {"id": "j2", "tenant_id": "t1", "customer_id": "c1"},
    ))
    assert fake.public_checkins.rows[0]["area_label"] == "Surprise, AZ"


def test_month_year_helper_handles_missing_dates(monkeypatch):
    """Job without ``completed_at`` still enqueues — we stamp
    ``now()`` and derive the month-year from that."""
    fake = _db(
        customers=[{"id": "c1", "tenant_id": "t1",
                     "latitude": 33.0, "longitude": -112.0}],
        tenants=[{"id": "t1", "settings": {}}],
    )
    monkeypatch.setattr(pce, "db", fake)

    _run(pce.enqueue_public_checkin_for_completed_job(
        {"id": "j3", "tenant_id": "t1", "customer_id": "c1"},
    ))
    row = fake.public_checkins.rows[0]
    assert row["completed_at"]
    assert row["completed_at_month_year"]
    # "Month YYYY" format — sanity check.
    assert " " in row["completed_at_month_year"]
