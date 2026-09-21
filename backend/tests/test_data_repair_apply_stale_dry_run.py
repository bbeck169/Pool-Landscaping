"""Feb-2026 · Phase F2 · freshness + confirm_token coverage.

Apply must refuse when:
  * ``confirm_token`` does not match any stored scan (unknown token),
  * ``dry_run_scan_timestamp`` does not match the record for the
    provided token (tampered payload),
  * the stored scan has expired (>15 minutes old).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from routers import data_repair as dr

from tests.test_data_repair_dry_run import _DB, _run


def test_apply_rejects_unknown_confirm_token(monkeypatch):
    fake = _DB(jobs=[], customers=[])
    monkeypatch.setattr(dr, "db", fake)

    body = dr.ApplyIn(
        confirm_token="not-a-real-token",
        dry_run_scan_timestamp="2026-08-01T00:00:00Z",
    )
    with pytest.raises(HTTPException) as exc:
        _run(dr.data_repair_apply(body, user={"id": "sa-1",
                                              "role": "super_admin",
                                              "tenant_id": "t1"}))
    assert exc.value.status_code == 400
    assert "confirm_token" in str(exc.value.detail).lower()


def test_apply_rejects_mismatched_scan_timestamp(monkeypatch):
    fake = _DB(jobs=[], customers=[])
    monkeypatch.setattr(dr, "db", fake)
    monkeypatch.setattr(dr, "_dry_run_cache", {})

    # Seed a valid scan.
    user = {"id": "sa-1", "role": "super_admin", "tenant_id": "t1"}
    payload = _run(dr.data_repair_dry_run(user=user))

    body = dr.ApplyIn(
        confirm_token=payload["confirm_token"],
        # WRONG scan_timestamp — attacker attempts to reuse the token
        # with a different report they crafted themselves.
        dry_run_scan_timestamp="2026-01-01T00:00:00Z",
    )
    with pytest.raises(HTTPException) as exc:
        _run(dr.data_repair_apply(body, user=user))
    assert exc.value.status_code == 400
    assert "scan_timestamp" in str(exc.value.detail).lower()


def test_apply_rejects_stale_scan(monkeypatch):
    """A scan whose ``expires_at`` is in the past must be rejected
    with a clear message. Freshness is enforced independently of the
    router's own cache."""
    fake = _DB(jobs=[], customers=[])
    monkeypatch.setattr(dr, "db", fake)

    # Directly insert an expired scan record — with a tenant_id so
    # ``_load_scan`` gets past the R1 tenant-scope gate and can
    # exercise the freshness rejection.
    expired = {
        "confirm_token": "stale-token",
        "scan_timestamp": "2026-08-01T00:00:00Z",
        "tenant_id": "t1",
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        "actor_user_id": "sa-1",
        "classes": {"orphaned_customer_refs": [],
                    "orphaned_technician_refs": [],
                    "unassigned_pending_jobs": []},
    }
    _run(fake.data_integrity_scans.insert_one(expired))

    body = dr.ApplyIn(
        confirm_token="stale-token",
        dry_run_scan_timestamp="2026-08-01T00:00:00Z",
    )
    with pytest.raises(HTTPException) as exc:
        _run(dr.data_repair_apply(body,
                                    user={"id": "sa-1",
                                          "role": "super_admin",
                                          "tenant_id": "t1"}))
    assert exc.value.status_code == 400
    assert "expired" in str(exc.value.detail).lower()
