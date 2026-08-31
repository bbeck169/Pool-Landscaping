"""Feb-2026 · Phase F2 addendum — BSON naive-datetime coercion.

Root cause the testing agent found live: MongoDB / BSON stores UTC
datetimes WITHOUT tzinfo. When Motor reads them back the value is
offset-NAIVE. ``_load_scan`` compares that against
``datetime.now(timezone.utc)`` (offset-AWARE) — which raises
``TypeError`` and surfaces as HTTP 500 on every apply call.

Fixed by coercing a naive ``expires_at`` to UTC before the
comparison. This regression suite pins that fix by feeding
``_load_scan`` a scan record whose ``expires_at`` is offset-naive,
mimicking real BSON round-trip. Without the coercion the test
would raise TypeError; with it, ``_load_scan`` returns the scan
cleanly.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from routers import data_repair as dr

from tests.test_data_repair_dry_run import _DB, _run


def _bson_naive_scan(**overrides):
    """Return a scan record whose ``expires_at`` is offset-naive UTC
    — the shape Motor returns after a BSON round-trip."""
    naive_utc_now = datetime.utcnow()   # naive by construction
    scan = {
        "confirm_token": "bson-naive-token",
        "scan_timestamp": "2026-08-01T00:00:00+00:00",
        "created_at": naive_utc_now - timedelta(minutes=1),
        "expires_at": naive_utc_now + timedelta(minutes=14),
        "actor_user_id": "sa-1",
        "classes": {"orphaned_customer_refs": [],
                    "orphaned_technician_refs": [],
                    "unassigned_pending_jobs": []},
    }
    scan.update(overrides)
    return scan


def test_load_scan_accepts_naive_expires_at(monkeypatch):
    """The tester's live-repro scenario, pinned. Without the naive→
    aware coercion this raises TypeError."""
    fake = _DB(jobs=[], customers=[])
    monkeypatch.setattr(dr, "db", fake)

    scan_doc = _bson_naive_scan()
    _run(fake.data_integrity_scans.insert_one(scan_doc))

    result = _run(dr._load_scan(
        scan_doc["confirm_token"], scan_doc["scan_timestamp"],
    ))
    assert result["confirm_token"] == scan_doc["confirm_token"]


def test_load_scan_rejects_expired_naive_expires_at(monkeypatch):
    """Same naive-datetime shape but expired — must be rejected
    (not raise TypeError)."""
    fake = _DB(jobs=[], customers=[])
    monkeypatch.setattr(dr, "db", fake)

    # Expired 1 hour ago, still naive.
    scan_doc = _bson_naive_scan(
        expires_at=datetime.utcnow() - timedelta(hours=1),
    )
    _run(fake.data_integrity_scans.insert_one(scan_doc))

    with pytest.raises(HTTPException) as exc:
        _run(dr._load_scan(
            scan_doc["confirm_token"], scan_doc["scan_timestamp"],
        ))
    assert exc.value.status_code == 400
    assert "expired" in str(exc.value.detail).lower()


def test_apply_endpoint_survives_bson_naive_roundtrip(monkeypatch):
    """End-to-end at the apply layer: seed a fresh scan record with
    a naive ``expires_at``, call ``data_repair_apply`` — must not
    500."""
    fake = _DB(jobs=[], customers=[])
    monkeypatch.setattr(dr, "db", fake)

    scan_doc = _bson_naive_scan()
    _run(fake.data_integrity_scans.insert_one(scan_doc))

    body = dr.ApplyIn(
        confirm_token=scan_doc["confirm_token"],
        dry_run_scan_timestamp=scan_doc["scan_timestamp"],
    )
    result = _run(dr.data_repair_apply(
        body, user={"id": "sa-1", "role": "super_admin"},
    ))
    # Scan captured 0 classes, so apply is a no-op — but critically
    # it did NOT 500 on the naive-datetime comparison.
    assert result["no_op"] is True
    assert result["changes_applied"] == 0
