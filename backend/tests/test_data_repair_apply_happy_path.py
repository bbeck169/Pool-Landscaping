"""Feb-2026 · Phase F2 · apply happy-path coverage.

After a dry-run, apply must:
  * soft-delete orphan-customer jobs with
    ``deleted_reason='data_repair_orphaned_customer'``,
  * null out ``technician_id`` on orphan-tech jobs (preserve
    ``technician_name``),
  * write one row per repair into ``db.data_integrity_repairs`` with
    the full before/after snapshot,
  * never touch the six/nine flagged unassigned-pending jobs.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from routers import data_repair as dr

# Reuse the fake stubs from the dry-run test module.
from tests.test_data_repair_dry_run import _DB, _run


def _seed_and_scan(monkeypatch):
    """Seed a mixed dataset, wire the fake db, run dry-run, return
    (fake_db, payload)."""
    customers = [
        {"id": "c1", "tenant_id": "t1"},
        {"id": "c2", "tenant_id": "t1"},
    ]
    techs = [{"id": "tech-a", "tenant_id": "t1"}]
    users: List[Dict[str, Any]] = []
    jobs = [
        # Two orphan-customer jobs.
        {"id": "j-oc1", "tenant_id": "t1", "customer_id": "GHOST",
         "customer_name": "Water Bodies Test", "status": "scheduled",
         "scheduled_date": "2026-08-01"},
        {"id": "j-oc2", "tenant_id": "t1", "customer_id": "GHOST",
         "customer_name": "Confirm Case", "status": "requested",
         "scheduled_date": "2026-08-02"},
        # Two orphan-tech jobs.
        {"id": "j-ot1", "tenant_id": "t1", "customer_id": "c1",
         "technician_id": "GHOST", "technician_name": "Sara Nguyen",
         "status": "scheduled", "scheduled_date": "2026-08-03"},
        {"id": "j-ot2", "tenant_id": "t1", "customer_id": "c2",
         "technician_id": "GHOST", "technician_name": "Sara Nguyen",
         "status": "pending", "scheduled_date": "2026-08-04"},
        # One unassigned-pending — must be flag-only, never mutated.
        {"id": "j-up", "tenant_id": "t1", "customer_id": "c1",
         "technician_id": None, "status": "requested",
         "scheduled_date": "2026-08-05"},
    ]
    fake = _DB(jobs=jobs, customers=customers, technicians=techs, users=users)
    monkeypatch.setattr(dr, "db", fake)
    monkeypatch.setattr(dr, "_dry_run_cache", {})

    user = {"id": "sa-1", "role": "super_admin", "tenant_id": "t1"}
    payload = _run(dr.data_repair_dry_run(user=user))
    return fake, payload, user


def test_apply_soft_deletes_orphan_customer_jobs(monkeypatch):
    fake, payload, user = _seed_and_scan(monkeypatch)

    body = dr.ApplyIn(
        confirm_token=payload["confirm_token"],
        dry_run_scan_timestamp=payload["scan_timestamp"],
    )
    result = _run(dr.data_repair_apply(body, user=user))

    assert result["no_op"] is False
    # Two orphan customers + two orphan techs = 4 changes.
    assert result["changes_applied"] == 4
    assert len(result["audit_log_ids"]) == 4

    # ── The soft-delete columns must be stamped on both orphan-cust jobs.
    for jid in ("j-oc1", "j-oc2"):
        row = next(r for r in fake.jobs.rows if r["id"] == jid)
        assert row["deleted_at"], f"{jid} missing deleted_at"
        assert row["status"] == "deleted"
        assert row["deleted_reason"] == "data_repair_orphaned_customer"
        assert row["deleted_by_user_id"] == "sa-1"

    # ── Orphan-tech jobs — technician_id nulled, name preserved.
    for jid in ("j-ot1", "j-ot2"):
        row = next(r for r in fake.jobs.rows if r["id"] == jid)
        assert row["technician_id"] is None, f"{jid} still has technician_id"
        assert row["technician_name"] == "Sara Nguyen"
        # Never soft-deleted.
        assert "deleted_at" not in row or row.get("deleted_at") is None

    # ── Unassigned-pending row is untouched.
    up_row = next(r for r in fake.jobs.rows if r["id"] == "j-up")
    assert up_row.get("technician_id") is None
    assert up_row.get("status") == "requested"


def test_apply_persists_audit_rows_with_before_after(monkeypatch):
    fake, payload, user = _seed_and_scan(monkeypatch)

    body = dr.ApplyIn(
        confirm_token=payload["confirm_token"],
        dry_run_scan_timestamp=payload["scan_timestamp"],
    )
    _run(dr.data_repair_apply(body, user=user))

    audit_rows = fake.data_integrity_repairs.inserts
    assert len(audit_rows) == 4
    for row in audit_rows:
        assert row["run_id"] == payload["confirm_token"]
        assert row["actor_user_id"] == "sa-1"
        assert row["target_collection"] == "jobs"
        assert row["class"] in {"orphaned_customer_ref",
                                "orphaned_technician_ref"}
        assert row["action"] in {"soft_delete", "null_technician_id"}
        assert "before" in row and "after" in row
        # ``before`` snapshot must contain the pre-repair identifying
        # keys so a rollback tool can reconstruct state.
        assert row["before"]["id"] == row["target_id"]

    # ── Class → action correspondence pinned.
    for row in audit_rows:
        if row["class"] == "orphaned_customer_ref":
            assert row["action"] == "soft_delete"
            assert row["after"]["status"] == "deleted"
            assert row["after"]["deleted_reason"] == \
                "data_repair_orphaned_customer"
        else:
            assert row["action"] == "null_technician_id"
            assert row["after"]["technician_id"] is None


def test_apply_no_op_when_scan_had_only_flags(monkeypatch):
    """A scan whose only findings are unassigned-pending returns
    ``no_op=True`` on apply — nothing to change."""
    fake = _DB(
        jobs=[{"id": "j-up", "tenant_id": "t1", "customer_id": "c1",
               "technician_id": None, "status": "requested"}],
        customers=[{"id": "c1", "tenant_id": "t1"}],
    )
    monkeypatch.setattr(dr, "db", fake)
    monkeypatch.setattr(dr, "_dry_run_cache", {})

    user = {"id": "sa-1", "role": "super_admin", "tenant_id": "t1"}
    payload = _run(dr.data_repair_dry_run(user=user))
    assert payload["summary"]["total_would_change"] == 0
    assert payload["summary"]["total_flagged_no_action"] == 1

    body = dr.ApplyIn(
        confirm_token=payload["confirm_token"],
        dry_run_scan_timestamp=payload["scan_timestamp"],
    )
    result = _run(dr.data_repair_apply(body, user=user))
    assert result["no_op"] is True
    assert result["changes_applied"] == 0
