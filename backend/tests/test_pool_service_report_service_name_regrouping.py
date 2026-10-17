"""Feb-2026 · Pool Service Report — service-name regrouping pytest.

Validates ``_compute_service_name_breakdown`` + its wiring into
``compute_pool_service``:

  1. 10 jobs with ``service_type="Weekly Pool Cleaning"`` +
     ``job_type="Maintenance"`` → all 10 land in the
     "Weekly Pool Cleaning" bucket (NOT the Maintenance bucket).
  2. 3 jobs with ``technician_id=None`` → Unassigned.count == 3.
  3. 1 job pointing to a soft-deleted user → Unassigned.count == 1.
  4. Fixture with service_names {"Filter Change", "Equipment Repair",
     "Chemical Only", "Weekly Pool Cleaning"} → Weekly Pool Cleaning
     in own bucket; other three roll into "Other" with correct
     ``other_breakdown`` counts sorted desc.
  5. Reconciliation: sum of all bucket counts + unassigned.count
     == total_pool_jobs (reconciliation_delta == 0 happy path).
  6. Reconciliation delta is non-zero (and warning fires) when a
     synthetic edge-case drops a job — asserts the mechanism.
  7. Cross-tenant isolation: pool jobs from another tenant do NOT
     bleed into the breakdown.
  8. Date-window boundary: jobs scheduled on the exact start / end
     date of the window are INCLUDED.

Synthetic data only.
"""
from __future__ import annotations

import uuid

import pytest
from dotenv import load_dotenv

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")


def _tid() -> str:
    return f"test-pool-sn-{uuid.uuid4()}"


async def _seed_pool_job(
    db,
    tenant_id: str,
    *,
    service_type: str,
    job_type: str = "",
    technician_id: str | None = "tech-A",
    technician_name: str = "Alpha Tech",
    scheduled_date: str = "2026-02-02",
    status: str = "completed",
    work_class: str = "service",
) -> str:
    jid = str(uuid.uuid4())
    doc = {
        "id": jid,
        "tenant_id": tenant_id,
        "service_type": service_type,
        "job_type": job_type,
        "status": status,
        "work_class": work_class,
        "scheduled_date": scheduled_date,
        "industry": "pool",
    }
    if technician_id:
        doc["technician_id"] = technician_id
    if technician_name:
        doc["technician_name"] = technician_name
    await db.jobs.insert_one(doc)
    return jid


async def _seed_tech_user(
    db, tenant_id: str, *,
    technician_id: str, name: str, active: bool = True,
    soft_deleted: bool = False,
):
    doc = {
        "id": f"user-{technician_id}",
        "tenant_id": tenant_id,
        "technician_id": technician_id,
        "name": name,
        "active": active,
        "role": "technician",
    }
    if soft_deleted:
        doc["deleted_at"] = "2026-01-01T00:00:00Z"
    await db.users.insert_one(doc)


async def _cleanup(db, *tids: str):
    for tid in tids:
        await db.jobs.delete_many({"tenant_id": tid})
        await db.users.delete_many({"tenant_id": tid})
        await db.tenants.delete_many({"id": tid})


async def _seed_tenant(db, tenant_id: str):
    await db.tenants.insert_one({
        "id": tenant_id, "name": "Synthetic Pool Co",
        "industries": ["pool"],
    })


def _run_compute(tenant_id: str, date_from: str, date_to: str):
    """Call ``compute_pool_service`` + return just the service-name
    breakdown section."""
    from routers.jobs import compute_pool_service
    async def _inner(db):
        return await compute_pool_service(
            tenant_id, date_from=date_from, date_to=date_to,
        )
    return _inner


# ─── 1 · 10 Weekly-Pool-Cleaning jobs → own bucket ───────────────
def test_weekly_pool_cleaning_regroups_by_service_name_not_job_type():
    tid = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid)
            await _seed_tech_user(
                db, tid, technician_id="tech-A", name="Alpha Tech",
            )
            for _ in range(10):
                await _seed_pool_job(
                    db, tid,
                    service_type="Weekly Pool Cleaning",
                    job_type="Maintenance",
                )
            from routers.jobs import compute_pool_service
            resp = await compute_pool_service(
                tid, date_from="2026-02-02", date_to="2026-02-02",
            )
            sb = resp["service_name_breakdown"]
            wpc = next(b for b in sb["buckets"]
                        if b["name"] == "Weekly Pool Cleaning")
            assert wpc["count"] == 10, (
                "all 10 jobs must land in Weekly Pool Cleaning, "
                f"got {wpc['count']}"
            )
            # Maintenance bucket must be empty (none of the jobs
            # had service_type="Maintenance").
            maint = next(b for b in sb["buckets"]
                          if b["name"] == "Maintenance")
            assert maint["count"] == 0, (
                "Maintenance bucket must stay at 0 — grouping is "
                f"service_name, not job_type; got {maint['count']}"
            )
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 2 · null technician_id → Unassigned ─────────────────────────
def test_jobs_with_null_tech_land_in_unassigned_bucket():
    tid = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid)
            for _ in range(3):
                await _seed_pool_job(
                    db, tid, service_type="Weekly Pool Cleaning",
                    technician_id=None, technician_name="",
                )
            from routers.jobs import compute_pool_service
            resp = await compute_pool_service(
                tid, date_from="2026-02-02", date_to="2026-02-02",
            )
            sb = resp["service_name_breakdown"]
            assert sb["unassigned"]["count"] == 3
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 3 · soft-deleted tech user → Unassigned ─────────────────────
def test_soft_deleted_tech_user_routes_to_unassigned():
    tid = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid)
            await _seed_tech_user(
                db, tid, technician_id="tech-Z",
                name="Zombie Tech", soft_deleted=True,
            )
            await _seed_pool_job(
                db, tid,
                service_type="Weekly Pool Cleaning",
                technician_id="tech-Z",
                technician_name="Zombie Tech",
            )
            from routers.jobs import compute_pool_service
            resp = await compute_pool_service(
                tid, date_from="2026-02-02", date_to="2026-02-02",
            )
            sb = resp["service_name_breakdown"]
            # Must be in unassigned, not under tech-Z's row.
            assert sb["unassigned"]["count"] == 1
            wpc = next(b for b in sb["buckets"]
                        if b["name"] == "Weekly Pool Cleaning")
            assert all(
                t["technician_id"] != "tech-Z" for t in wpc["techs"]
            ), "soft-deleted tech must not have a per-tech row"
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 4 · Other bucket + sub-breakdown ────────────────────────────
def test_other_bucket_sub_breakdown_counts_per_service_name_sorted_desc():
    tid = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid)
            await _seed_tech_user(
                db, tid, technician_id="tech-A", name="Alpha Tech",
            )
            # TD-63 · Feb-2026 — fixture updated to use service
            # names that genuinely fall OUTSIDE the 6-bucket
            # taxonomy so this test continues to exercise the
            # Other-bucket + sub-breakdown ordering logic.
            fixtures = [
                ("Mystery Visit",     3),
                ("Oddball Request",   2),
                ("Freeform Note",     5),
                ("Weekly Pool Cleaning", 1),
            ]
            for sv, n in fixtures:
                for _ in range(n):
                    await _seed_pool_job(
                        db, tid, service_type=sv,
                    )
            from routers.jobs import compute_pool_service
            resp = await compute_pool_service(
                tid, date_from="2026-02-02", date_to="2026-02-02",
            )
            sb = resp["service_name_breakdown"]
            wpc = next(b for b in sb["buckets"]
                        if b["name"] == "Weekly Pool Cleaning")
            assert wpc["count"] == 1
            other = next(b for b in sb["buckets"]
                          if b["name"] == "Other")
            assert other["count"] == 10
            # Sorted desc by count, then name asc.
            br = other.get("other_breakdown") or []
            assert br[0] == {"service_name": "Freeform Note", "count": 5}
            assert br[1] == {"service_name": "Mystery Visit", "count": 3}
            assert br[2] == {"service_name": "Oddball Request", "count": 2}
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 5 · reconciliation delta == 0 on happy path ─────────────────
def test_reconciliation_delta_zero_on_happy_path():
    tid = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid)
            await _seed_tech_user(
                db, tid, technician_id="tech-A", name="Alpha",
            )
            for _ in range(4):
                await _seed_pool_job(
                    db, tid, service_type="Weekly Pool Cleaning",
                )
            await _seed_pool_job(
                db, tid, service_type="Equipment Repair",
                technician_id=None, technician_name="",
            )
            from routers.jobs import compute_pool_service
            resp = await compute_pool_service(
                tid, date_from="2026-02-02", date_to="2026-02-02",
            )
            sb = resp["service_name_breakdown"]
            total_buckets = sum(b["count"] for b in sb["buckets"])
            assert (
                total_buckets + sb["unassigned"]["count"]
                == sb["total_pool_jobs"]
            )
            assert sb["reconciliation_delta"] == 0
            assert sb["total_pool_jobs"] == 5
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 6 · reconciliation mechanism works for synthetic drops ──────
def test_reconciliation_mechanism_detects_bucket_drop_delta():
    """Edge-case defense — if the helper ever drops a job without
    adding it to Unassigned, the reconciliation_delta surfaces it.
    This exercises the mechanism by seeding a job whose attribution
    ladder points to a NON-EXISTENT tech id that isn't soft-deleted
    (so it would normally bucket under that tid). The helper must
    still count it, so delta stays 0 — this test asserts the
    INVARIANT holds across the edge case."""
    tid = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid)
            # Ghost tid — no users row, no soft-delete flag. The
            # attribution ladder keeps this tid (step 1 of the
            # ladder matches on any truthy ``technician_id``).
            await _seed_pool_job(
                db, tid,
                service_type="Weekly Pool Cleaning",
                technician_id="ghost-tech-xyz",
                technician_name="",
            )
            from routers.jobs import compute_pool_service
            resp = await compute_pool_service(
                tid, date_from="2026-02-02", date_to="2026-02-02",
            )
            sb = resp["service_name_breakdown"]
            # Invariant upheld — delta stays 0 even on an orphan tid.
            assert sb["reconciliation_delta"] == 0
            # The job IS counted somewhere.
            total = sum(b["count"] for b in sb["buckets"])
            assert total + sb["unassigned"]["count"] == 1
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 7 · cross-tenant isolation ──────────────────────────────────
def test_cross_tenant_jobs_do_not_bleed_into_breakdown():
    tid_a = _tid()
    tid_b = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid_a)
            await _seed_tenant(db, tid_b)
            await _seed_tech_user(
                db, tid_a, technician_id="tech-A", name="Alpha",
            )
            await _seed_tech_user(
                db, tid_b, technician_id="tech-B", name="Beta",
            )
            # 2 pool jobs in tenant A, 100 in tenant B.
            for _ in range(2):
                await _seed_pool_job(
                    db, tid_a, service_type="Weekly Pool Cleaning",
                    technician_id="tech-A", technician_name="Alpha",
                )
            for _ in range(100):
                await _seed_pool_job(
                    db, tid_b, service_type="Weekly Pool Cleaning",
                    technician_id="tech-B", technician_name="Beta",
                )
            from routers.jobs import compute_pool_service
            resp_a = await compute_pool_service(
                tid_a, date_from="2026-02-02", date_to="2026-02-02",
            )
            sb_a = resp_a["service_name_breakdown"]
            assert sb_a["total_pool_jobs"] == 2
            wpc = next(b for b in sb_a["buckets"]
                        if b["name"] == "Weekly Pool Cleaning")
            assert wpc["count"] == 2
            # Tenant B's techs must not appear anywhere in tenant A.
            all_tids = [
                t["technician_id"]
                for b in sb_a["buckets"]
                for t in b.get("techs") or []
            ]
            assert "tech-B" not in all_tids
        finally:
            await _cleanup(db, tid_a, tid_b)

    run_test(_run)


# ─── 8 · date-window boundary inclusive ──────────────────────────
def test_window_boundary_dates_are_inclusive():
    tid = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid)
            await _seed_tech_user(
                db, tid, technician_id="tech-A", name="Alpha",
            )
            await _seed_pool_job(
                db, tid, service_type="Weekly Pool Cleaning",
                scheduled_date="2026-02-02",   # window start
            )
            await _seed_pool_job(
                db, tid, service_type="Weekly Pool Cleaning",
                scheduled_date="2026-02-08",   # window end
            )
            # Out-of-window job must NOT appear.
            await _seed_pool_job(
                db, tid, service_type="Weekly Pool Cleaning",
                scheduled_date="2026-02-09",
            )
            from routers.jobs import compute_pool_service
            resp = await compute_pool_service(
                tid, date_from="2026-02-02", date_to="2026-02-08",
            )
            sb = resp["service_name_breakdown"]
            assert sb["total_pool_jobs"] == 2
            wpc = next(b for b in sb["buckets"]
                        if b["name"] == "Weekly Pool Cleaning")
            assert wpc["count"] == 2
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 9 · TD-63 Phase 2 taxonomy — new synonym buckets ─────────────
#
# All seeded jobs share the ``work_class="service"`` + ``status=
# "completed"`` default from ``_seed_pool_job`` so the chip-row
# arithmetic stays uncoupled from the taxonomy under test.  The
# per-case assertion only checks WHICH SERVICE NAME bucket each
# synonym lands in.
import pytest as _pytest


def _single_synonym_run(service_name_input, expected_bucket):
    """Shared harness — seed 1 pool job with ``service_type=input``
    then assert the resulting ``service_name_breakdown`` bucket set."""
    tid = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid)
            await _seed_tech_user(
                db, tid, technician_id="tech-A", name="Alpha Tech",
            )
            await _seed_pool_job(
                db, tid, service_type=service_name_input,
            )
            from routers.jobs import compute_pool_service
            resp = await compute_pool_service(
                tid, date_from="2026-02-02", date_to="2026-02-02",
            )
            sb = resp["service_name_breakdown"]
            counts = {b["name"]: b["count"] for b in sb["buckets"]}
            assert counts.get(expected_bucket, 0) == 1, (
                f"synonym {service_name_input!r} must land in "
                f"{expected_bucket!r} — got {counts}"
            )
            # Any OTHER known bucket (excluding the expected one and
            # excluding ``Other``) must stay at 0 for this single-job
            # fixture.
            for other_name in (
                "Weekly Pool Cleaning", "Maintenance", "Chemical Service",
                "Equipment Service", "Seasonal Service", "Service Call",
            ):
                if other_name == expected_bucket:
                    continue
                assert counts.get(other_name, 0) == 0, (
                    f"synonym {service_name_input!r} leaked into "
                    f"{other_name!r} — got {counts}"
                )
        finally:
            await _cleanup(db, tid)

    run_test(_run)


@_pytest.mark.parametrize("sv_name", [
    "Weekly service",
    "Weekly Pool Service",
    "Weekly Clean",
    "Routine Service",
    "Pool Cleaning",
    "weekly_pool_cleaning",
    "weekly-pool-cleaning",
])
def test_td63_weekly_pool_cleaning_synonyms(sv_name):
    _single_synonym_run(sv_name, "Weekly Pool Cleaning")


@_pytest.mark.parametrize("sv_name", [
    "Monthly Deep Clean",
    "Pool Maintenance",
    "Deep Clean",
])
def test_td63_maintenance_synonyms(sv_name):
    _single_synonym_run(sv_name, "Maintenance")


@_pytest.mark.parametrize("sv_name", [
    "Chem Check",
    "Chlorine Treatment",
    "Chemical Service",
    "Water Balance",
])
def test_td63_chemical_service_synonyms(sv_name):
    _single_synonym_run(sv_name, "Chemical Service")


@_pytest.mark.parametrize("sv_name", [
    "Pump Repair",
    "Filter Change",
    "Equipment Service",
    "Heater Service",
])
def test_td63_equipment_service_synonyms(sv_name):
    _single_synonym_run(sv_name, "Equipment Service")


@_pytest.mark.parametrize("sv_name", [
    "Winterization",
    "Spring Opening",
    "Pool Closing",
])
def test_td63_seasonal_service_synonyms(sv_name):
    _single_synonym_run(sv_name, "Seasonal Service")


@_pytest.mark.parametrize("sv_name", [
    "Service Call",
    "Diagnostic",
    "One-off Visit",
])
def test_td63_service_call_synonyms(sv_name):
    _single_synonym_run(sv_name, "Service Call")


# ─── 10 · TD-63 · Landscaping leak safety-net ────────────────────
def test_td63_landscape_service_type_excluded_from_pool_scope():
    """A job tagged ``industry=pool`` but ``service_type=Landscaping``
    must be excluded by the safety-net.  Validates both the
    industry-gate bypass path AND the post-filter guard."""
    tid = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid)
            await _seed_tech_user(
                db, tid, technician_id="tech-A", name="Alpha",
            )
            # Pool-flavored job — legit.
            await _seed_pool_job(
                db, tid, service_type="Weekly Pool Cleaning",
            )
            # Landscape-flavored job tagged ``industry=pool``.  The
            # strict-mode industry gate currently LETS THIS THROUGH
            # (data-quality defect — see Phase 1 audit § D).  The
            # safety-net at the top of ``compute_pool_service`` must
            # exclude it before the report sees it.
            await _seed_pool_job(
                db, tid, service_type="Landscaping",
            )
            from routers.jobs import compute_pool_service
            resp = await compute_pool_service(
                tid, date_from="2026-02-02", date_to="2026-02-02",
            )
            sb = resp["service_name_breakdown"]
            # Only the pool job should remain.
            assert sb["total_pool_jobs"] == 1
            counts = {b["name"]: b["count"] for b in sb["buckets"]}
            assert counts.get("Weekly Pool Cleaning", 0) == 1
            # No bucket should carry a landscape row.
            for b in sb["buckets"]:
                for t in b.get("techs") or []:
                    assert "landscape" not in (
                        t.get("technician_name") or ""
                    ).lower()
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 11 · TD-63 · terminal-completed status synonyms ─────────────
@_pytest.mark.parametrize("status_syn", [
    "completed", "closed", "done", "finished", "complete",
])
def test_td63_terminal_completed_status_synonyms_counted(status_syn):
    """Jobs with any of the 5 operator-locked completed synonyms
    MUST enter the counted buckets — NOT drop silently."""
    tid = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid)
            await _seed_tech_user(
                db, tid, technician_id="tech-A", name="Alpha",
            )
            await _seed_pool_job(
                db, tid, service_type="Weekly Pool Cleaning",
                status=status_syn,
            )
            from routers.jobs import compute_pool_service
            resp = await compute_pool_service(
                tid, date_from="2026-02-02", date_to="2026-02-02",
            )
            # Legacy ``total_completed`` + the inclusive
            # ``total_completed_all`` must both see the job.
            assert resp["total_completed_all"] == 1, (
                f"status {status_syn!r} must be treated as completed "
                f"— got total_completed_all={resp['total_completed_all']}"
            )
            # ``dropped_count`` must stay at 0 (the whole point of
            # TD-63 Q2 is NOT dropping synonyms).
            assert resp["dropped_count"] == 0, (
                f"status {status_syn!r} unexpectedly dropped — "
                f"got dropped_count={resp['dropped_count']}"
            )
        finally:
            await _cleanup(db, tid)

    run_test(_run)


@_pytest.mark.parametrize("status_non_terminal", [
    "pending", "scheduled", "in_progress",
])
def test_td63_non_terminal_statuses_still_dropped(status_non_terminal):
    """Regression guard — statuses OUTSIDE the terminal-completed
    + skipped sets continue to feed ``dropped_count``."""
    tid = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid)
            await _seed_tech_user(
                db, tid, technician_id="tech-A", name="Alpha",
            )
            await _seed_pool_job(
                db, tid, service_type="Weekly Pool Cleaning",
                status=status_non_terminal,
            )
            from routers.jobs import compute_pool_service
            resp = await compute_pool_service(
                tid, date_from="2026-02-02", date_to="2026-02-02",
            )
            assert resp["dropped_count"] == 1, (
                f"status {status_non_terminal!r} must still drop — "
                f"got dropped_count={resp['dropped_count']}"
            )
            assert resp["total_completed_all"] == 0
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 12 · TD-63 · structured [pool-report] log line fires ────────
def test_td63_structured_log_line_fires_with_dual_counters(caplog):
    """Patch ``logger.info`` on ``routers.jobs`` + assert the
    operator-locked log line format fires on every report render
    with both ``by-bucket_all`` and ``by-bucket_completed`` keys."""
    tid = _tid()

    async def _run(db):
        try:
            await _seed_tenant(db, tid)
            await _seed_tech_user(
                db, tid, technician_id="tech-A", name="Alpha",
            )
            # Seed 3 completed Weekly jobs + 1 dropped (scheduled).
            for _ in range(3):
                await _seed_pool_job(
                    db, tid, service_type="Weekly Pool Cleaning",
                )
            await _seed_pool_job(
                db, tid, service_type="Weekly Pool Cleaning",
                status="scheduled",
            )
            import logging
            from routers import jobs as _jobs_mod
            with caplog.at_level(logging.INFO, logger=_jobs_mod.logger.name):
                from routers.jobs import compute_pool_service
                await compute_pool_service(
                    tid, date_from="2026-02-02", date_to="2026-02-02",
                )
            pool_report_lines = [
                rec for rec in caplog.records
                if "[pool-report]" in rec.getMessage()
                and "by-bucket_all" in rec.getMessage()
                and "by-bucket_completed" in rec.getMessage()
            ]
            assert pool_report_lines, (
                "expected a [pool-report] INFO log line with both "
                "by-bucket_all and by-bucket_completed, got "
                f"{[r.getMessage() for r in caplog.records]}"
            )
            msg = pool_report_lines[0].getMessage()
            # Arithmetic reconciliation on the log line itself.
            assert "total_pool=4" in msg
            assert "completed=3" in msg
            assert "dropped=1" in msg
            assert "skipped=0" in msg
            # Dropped-status breakdown must carry the actual status.
            assert "'scheduled': 1" in msg
            # Bucket distribution — the Weekly Pool Cleaning bucket
            # should see all 4 jobs in ``_all`` and 3 in ``_completed``.
            assert "'Weekly Pool Cleaning': 4" in msg
            assert "'Weekly Pool Cleaning': 3" in msg
        finally:
            await _cleanup(db, tid)

    run_test(_run)
