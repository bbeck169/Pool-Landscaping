"""Feb-2026 · Phase F2 · idempotency coverage.

A second ``POST /admin/data-repair/jobs/apply`` with the same
``confirm_token`` must be a no-op — no new writes, no new audit
rows, no error. Guaranteed by the unique index
``(run_id, target_id)`` on ``data_integrity_repairs`` (the fake
collection here enforces the check at the helper level via the
``find_one`` short-circuit inside ``_apply_orphan_*``).
"""
from __future__ import annotations

from routers import data_repair as dr

from tests.test_data_repair_dry_run import _DB, _run


def test_apply_twice_is_idempotent(monkeypatch):
    customers = [{"id": "c1", "tenant_id": "t1"}]
    techs = [{"id": "tech-a", "tenant_id": "t1"}]
    jobs = [
        {"id": "j-oc", "tenant_id": "t1", "customer_id": "GHOST",
         "customer_name": "TestX", "status": "scheduled"},
        {"id": "j-ot", "tenant_id": "t1", "customer_id": "c1",
         "technician_id": "GHOST", "technician_name": "Sara",
         "status": "scheduled"},
    ]
    fake = _DB(jobs=jobs, customers=customers, technicians=techs)
    monkeypatch.setattr(dr, "db", fake)
    monkeypatch.setattr(dr, "_dry_run_cache",
                        {"expires_at": 0.0, "payload": None})

    user = {"id": "sa-1", "role": "super_admin"}
    payload = _run(dr.data_repair_dry_run(user=user))
    body = dr.ApplyIn(
        confirm_token=payload["confirm_token"],
        dry_run_scan_timestamp=payload["scan_timestamp"],
    )

    first = _run(dr.data_repair_apply(body, user=user))
    assert first["changes_applied"] == 2
    audit_rows_after_first = list(fake.data_integrity_repairs.inserts)

    # Second call — must be a no-op.
    second = _run(dr.data_repair_apply(body, user=user))
    assert second["changes_applied"] == 0
    assert second["no_op"] is True

    # No new audit rows written on the second call.
    assert fake.data_integrity_repairs.inserts == audit_rows_after_first

    # And no new update rows on the jobs collection either.
    # First call recorded 2 updates (one per orphan); second call
    # short-circuited before hitting update_one.
    assert len(fake.jobs.updates) == 2
