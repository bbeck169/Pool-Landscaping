"""Feb-2026 · Phase F3 · Startup data-integrity boot-check.

Root cause the audit surfaced (F2 shipped repairs for this state):
customers / crews were hard-deleted without cascading their
referencing ``jobs`` rows, so ``jobs.customer_id`` and
``jobs.technician_id`` accumulated dangling pointers over time.
F2 built the manual repair endpoints; F3 makes the app REFUSE TO
BOOT when the same state exists in the future — so silent
corruption never accumulates again.

Enforcement policy:

* ``INTEGRITY_CHECK_ENFORCE=true``  → CRITICAL log + raise
  ``IntegrityCheckFailure`` (which propagates up through the
  FastAPI startup event and prevents the API from accepting
  traffic). Operator must run F2's data-repair before the pod
  will boot again.
* ``INTEGRITY_CHECK_ENFORCE=false`` → CRITICAL log only. Boot
  continues.

Default:

* Production (``APP_ENV=production``) → ``true`` (fail-fast).
* Everywhere else → ``false`` (don't block local dev when a
  dev DB has stale test fixtures).

Env var precedence: if ``INTEGRITY_CHECK_ENFORCE`` is set to
either ``true`` or ``false`` explicitly, that value wins. If unset
or set to any other value, the APP_ENV default applies.

Detection classes:

1. ``customer_ref`` — ``jobs.customer_id`` points at a customer
   that doesn't exist in ``db.customers`` (excluding rows already
   soft-deleted, which we treat as intentionally removed).
2. ``technician_ref`` — ``jobs.technician_id`` set but points at
   neither a live ``db.users`` row with ``role='technician'`` nor
   a live ``db.technicians`` row. (Matches the id-space
   ``services/authz.is_tech_authorized_on_job`` accepts.)
3. ``crew_ref`` — ``jobs.crew_id`` set but points at nothing in
   ``db.crews``.

Only ACTIVE jobs are inspected — soft-deleted jobs are irrelevant
to authorization / dispatch and the F2 apply endpoint moves
orphans there deliberately.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("services.startup.integrity_check")


class IntegrityCheckFailure(RuntimeError):
    """Raised when enforcement is on AND dangling refs are found."""

    def __init__(self, report: Dict[str, Any]):
        super().__init__(
            f"data integrity check failed: "
            f"{report['summary']['total_dangling_refs']} dangling refs"
        )
        self.report = report


def _enforce_flag_from_env() -> bool:
    raw = (os.environ.get("INTEGRITY_CHECK_ENFORCE") or "").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    # Default: enforce ONLY in production. Everywhere else the
    # check runs but doesn't block boot — dev DBs routinely carry
    # test fixtures the operator doesn't want to firefight on
    # every reload.
    return (os.environ.get("APP_ENV") or "preview").lower() == "production"


async def _live_customer_ids(db: Any) -> set:
    ids: set = set()
    async for row in db.customers.find(
        {"$or": [
            {"deleted_at": None},
            {"deleted_at": {"$exists": False}},
        ]},
        {"_id": 0, "id": 1},
    ):
        cid = row.get("id")
        if cid:
            ids.add(cid)
    return ids


async def _live_technician_ids(db: Any) -> set:
    """Same id-space accepted by
    ``services.authz.is_tech_authorized_on_job``:
    ``technicians.id`` OR ``users.id`` where ``role='technician'``.

    Note: intentionally does NOT filter ``db.users`` by
    ``deleted_at`` — a soft-deleted technician user still counts
    as "live" for this scan. Rationale: an admin who soft-deletes
    a tech to offboard them shouldn't brick prod boot on the next
    restart; the tech's historical jobs are archival data.
    """
    tech_ids: set = set()
    async for row in db.technicians.find(
        {"$or": [
            {"deleted_at": None},
            {"deleted_at": {"$exists": False}},
        ]},
        {"_id": 0, "id": 1},
    ):
        tid = row.get("id")
        if tid:
            tech_ids.add(tid)
    async for row in db.users.find(
        {"role": "technician"}, {"_id": 0, "id": 1},
    ):
        uid = row.get("id")
        if uid:
            tech_ids.add(uid)
    return tech_ids


async def _live_crew_ids(db: Any) -> set:
    ids: set = set()
    async for row in db.crews.find({}, {"_id": 0, "id": 1}):
        cid = row.get("id")
        if cid:
            ids.add(cid)
    return ids


async def scan_dangling_refs(db: Any) -> Dict[str, Any]:
    """Read-only scan. Returns a structured report with sample
    dangling rows (capped at 20 per class) plus total counts."""
    live_customers = await _live_customer_ids(db)
    live_techs = await _live_technician_ids(db)
    live_crews = await _live_crew_ids(db)

    orphan_customer: List[Dict[str, Any]] = []
    orphan_technician: List[Dict[str, Any]] = []
    orphan_crew: List[Dict[str, Any]] = []

    active_filter = {"$or": [
        {"deleted_at": None},
        {"deleted_at": {"$exists": False}},
    ]}
    cursor = db.jobs.find(
        active_filter,
        {
            "_id": 0, "id": 1, "tenant_id": 1, "customer_id": 1,
            "customer_name": 1, "technician_id": 1,
            "technician_name": 1, "crew_id": 1, "status": 1,
        },
    )
    async for job in cursor:
        cid = job.get("customer_id")
        tid = job.get("technician_id")
        crid = job.get("crew_id")
        if cid and cid not in live_customers:
            orphan_customer.append({
                "job_id": job["id"],
                "tenant_id": job.get("tenant_id"),
                "customer_id": cid,
                "customer_name_denorm": job.get("customer_name") or "",
            })
        if tid and tid not in live_techs:
            orphan_technician.append({
                "job_id": job["id"],
                "tenant_id": job.get("tenant_id"),
                "technician_id": tid,
                "technician_name_denorm": job.get("technician_name") or "",
            })
        if crid and crid not in live_crews:
            orphan_crew.append({
                "job_id": job["id"],
                "tenant_id": job.get("tenant_id"),
                "crew_id": crid,
            })

    total = (len(orphan_customer) + len(orphan_technician)
             + len(orphan_crew))
    return {
        "orphan_customer": orphan_customer[:20],
        "orphan_customer_total": len(orphan_customer),
        "orphan_technician": orphan_technician[:20],
        "orphan_technician_total": len(orphan_technician),
        "orphan_crew": orphan_crew[:20],
        "orphan_crew_total": len(orphan_crew),
        "summary": {
            "total_dangling_refs": total,
            "customer_class": len(orphan_customer),
            "technician_class": len(orphan_technician),
            "crew_class": len(orphan_crew),
        },
    }


async def run_startup_integrity_check(db: Any) -> Dict[str, Any]:
    """Called from ``server.py`` startup. Returns the scan report
    even on the happy path so callers can log a "clean" tag.

    Raises ``IntegrityCheckFailure`` iff the enforcement flag is on
    AND at least one **enforced class** has dangling refs.

    Enforced classes:
      * ``customer`` — F3 hard-delete block now prevents new
        orphans; boot MUST fail-fast if any pre-existing state
        slips through.
      * ``crew``     — same rationale as customer.
      * ``technician`` is CRITICAL-LOGGED only. A tech user
        promoted/demoted out of the ``technician`` role removes
        their id from the live tech id-space silently — that's a
        legitimate admin action, not corruption, and it should not
        brick prod boot on the next restart. F2's data-repair
        endpoints still surface these rows so ops can fix them
        on their own schedule.
    """
    report = await scan_dangling_refs(db)
    summary = report["summary"]
    enforcing_total = summary["customer_class"] + summary["crew_class"]
    total = summary["total_dangling_refs"]
    enforce = _enforce_flag_from_env()

    if total == 0:
        logger.info(
            "[integrity_check] clean — 0 dangling refs "
            "(enforce=%s)", enforce,
        )
        return report

    # ── Log the samples so the operator has an actionable path.
    logger.critical(
        "[integrity_check] DANGLING REFS DETECTED — "
        "customer=%d technician=%d crew=%d total=%d "
        "enforce=%s enforcing_total=%d. "
        "Run POST /api/admin/data-repair/jobs/apply with a fresh "
        "dry-run scan to repair.",
        summary["customer_class"], summary["technician_class"],
        summary["crew_class"], total, enforce, enforcing_total,
    )
    for cls_name in ("orphan_customer", "orphan_technician", "orphan_crew"):
        for sample in report[cls_name][:5]:
            logger.critical("[integrity_check] %s sample: %s",
                             cls_name, sample)

    # Only ``customer`` and ``crew`` classes contribute to fail-fast
    # — see docstring for the rationale on softening
    # ``technician_ref``.
    if enforce and enforcing_total > 0:
        raise IntegrityCheckFailure(report)
    return report
