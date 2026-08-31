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

── Phase F6 · Feb-2026 — diagnostic dump + log-only nag ──
Even when ``enforce=False`` unblocks the deploy, the operator now
gets:
  * A machine-readable JSON blob on stderr (grep target
    ``INTEGRITY_DUMP:``) — one line, log-shipper friendly.
  * A durable dump file at
    ``/app/backend/logs/integrity_dump_{utc_iso}.json`` with the
    FULL orphan list per class (no 20-row cap) + a per-tenant
    breakdown.
  * A human-readable summary line pointing at the runbook and the
    dump path.
  * A recurring 60-min CRITICAL nag while log-only mode is active
    with dangling refs > 0 (see ``start_log_only_reminder_task``).

The dump path lives at the module boundary, so ``enforce=True``
callers ALSO benefit — repair playbooks now have machine-readable
input on any fail-fast boot, no scraping needed.

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

import asyncio
import json
import logging
import os
import pathlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("services.startup.integrity_check")

# Filesystem sink for the JSON diagnostic dump.  Overridable at
# import time via ``INTEGRITY_DUMP_DIR`` if the pod's writable
# volume differs from ``/app/backend/logs``.
_DEFAULT_DUMP_DIR = pathlib.Path(
    os.environ.get("INTEGRITY_DUMP_DIR", "/app/backend/logs"),
)
_LOG_ONLY_REMINDER_INTERVAL_SEC = int(
    os.environ.get("INTEGRITY_LOG_ONLY_REMINDER_SEC", "3600"),
)


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

    # Phase F6 · Feb-2026 — per-tenant breakdown so operators can
    # see WHICH tenant is corrupt at a glance instead of grepping
    # the sample lines.  Sorted descending so the loudest tenant
    # is first.
    tenant_counts: Dict[str, int] = {}
    for row in orphan_customer + orphan_technician + orphan_crew:
        tid = row.get("tenant_id") or "(no tenant_id)"
        tenant_counts[tid] = tenant_counts.get(tid, 0) + 1
    tenant_breakdown = dict(
        sorted(tenant_counts.items(), key=lambda kv: -kv[1])
    )

    return {
        # Backwards-compat: samples capped at 20 for the on-console
        # sample lines.  Older test fixtures assert against these.
        "orphan_customer": orphan_customer[:20],
        "orphan_customer_total": len(orphan_customer),
        "orphan_technician": orphan_technician[:20],
        "orphan_technician_total": len(orphan_technician),
        "orphan_crew": orphan_crew[:20],
        "orphan_crew_total": len(orphan_crew),
        # Phase F6 · Feb-2026 — FULL lists retained on the report
        # so ``write_diagnostic_dump`` can emit every row.  Prefixed
        # ``_all_*`` so callers grepping the older keys still get
        # the sample-capped view.
        "_all_orphans_customer": orphan_customer,
        "_all_orphans_technician": orphan_technician,
        "_all_orphans_crew": orphan_crew,
        "tenant_breakdown": tenant_breakdown,
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

    # ── Phase F6 · Feb-2026 — always write the diagnostic dump when
    #    dangling refs are found, regardless of enforce mode.  The
    #    dump is what the operator actually needs to fix state.
    dump_path = write_diagnostic_dump(report, enforce_mode=enforce)

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

    # Phase F6 · human-readable per-tenant summary + dump-path
    # pointer so on-call ops don't have to grep the sample lines.
    _emit_operator_summary(report, dump_path)

    # Phase F6 · loud reminder while log-only mode is active with
    # dangling refs > 0 — operators forget to flip enforce back on.
    if not enforce:
        logger.critical(
            "[integrity_check] [LOG-ONLY MODE ACTIVE] enforce=False "
            "— %d dangling refs detected but not blocking startup. "
            "This is a deployment workaround, NOT a stable operating "
            "mode. Run F2 data-repair immediately and restore "
            "INTEGRITY_CHECK_ENFORCE=true. Dump: %s",
            total, dump_path,
        )

    # Only ``customer`` and ``crew`` classes contribute to fail-fast
    # — see docstring for the rationale on softening
    # ``technician_ref``.
    if enforce and enforcing_total > 0:
        raise IntegrityCheckFailure(report)
    return report


# ═══════════════════════════════════════════════════════════════════
# Phase F6 · Feb-2026 — diagnostic dump + log-only reminder task
# ═══════════════════════════════════════════════════════════════════


def _dump_filename(now: Optional[datetime] = None) -> str:
    """Colon-free UTC timestamp so the filename is Windows-safe
    and shell-quoting-safe."""
    now = now or datetime.now(timezone.utc)
    return f"integrity_dump_{now.strftime('%Y-%m-%dT%H-%M-%SZ')}.json"


def _build_dump_payload(report: Dict[str, Any],
                          *, enforce_mode: bool,
                          now: Optional[datetime] = None) -> Dict[str, Any]:
    """Assemble the machine-readable dump.  Kept pure so tests can
    assert against the exact shape without touching disk."""
    now = now or datetime.now(timezone.utc)
    return {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "enforce_mode": bool(enforce_mode),
        "totals": {
            "customer": report["summary"]["customer_class"],
            "technician": report["summary"]["technician_class"],
            "crew": report["summary"]["crew_class"],
            "total": report["summary"]["total_dangling_refs"],
        },
        "tenant_breakdown": report.get("tenant_breakdown", {}),
        "orphans": {
            "customer_refs": report.get("_all_orphans_customer", []),
            "technician_refs": report.get("_all_orphans_technician", []),
            "crew_refs": report.get("_all_orphans_crew", []),
        },
    }


def write_diagnostic_dump(report: Dict[str, Any],
                             *, enforce_mode: bool,
                             dump_dir: Optional[pathlib.Path] = None,
                             now: Optional[datetime] = None,
                             ) -> Optional[str]:
    """Emit the F6 diagnostic dump — stderr line + JSON file.

    Returns the file path (as str) on success, None on any failure
    (never raises — a diagnostic emit MUST NOT itself brick boot).
    Called ONLY when ``total_dangling_refs > 0`` — clean scans
    write nothing.
    """
    payload = _build_dump_payload(report, enforce_mode=enforce_mode, now=now)
    # ── stderr JSON line for log-shippers.  Compact so a single
    #    grep on ``INTEGRITY_DUMP:`` yields a self-contained record.
    try:
        logger.critical(
            "INTEGRITY_DUMP: %s",
            json.dumps(payload, separators=(",", ":"), sort_keys=True,
                        default=str),
        )
    except Exception as exc:      # noqa: BLE001 — never brick boot
        logger.warning("[integrity_check] stderr dump failed: %s", exc)

    # ── Durable file dump.  Uses the module-level default dir
    #    unless the caller overrides (tests point at tmp).
    target_dir = dump_dir or _DEFAULT_DUMP_DIR
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / _dump_filename(now)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return str(path)
    except Exception as exc:      # noqa: BLE001
        logger.warning(
            "[integrity_check] file dump to %s failed: %s",
            target_dir, exc,
        )
        return None


def _emit_operator_summary(report: Dict[str, Any],
                             dump_path: Optional[str]) -> None:
    """Human-readable one-liner — total + per-tenant breakdown +
    runbook pointer + dump file path.  On-call reads this line
    ONLY and knows exactly which tenant to repair."""
    breakdown = report.get("tenant_breakdown") or {}
    top_lines: List[str] = []
    for tid, count in list(breakdown.items())[:5]:
        by_class = _tenant_class_breakdown(report, tid)
        top_lines.append(
            f"  Tenant {tid}: customer={by_class['customer']} "
            f"technician={by_class['technician']} "
            f"crew={by_class['crew']} (subtotal={count})"
        )
    logger.critical(
        "[integrity_check] %d dangling refs across %d tenant(s):\n%s\n"
        "Full dump: %s\n"
        "See DATA_INTEGRITY_RUNBOOK.md for recovery: "
        "run F2 dry-run+apply, then flip enforce back on.",
        report["summary"]["total_dangling_refs"],
        len(breakdown),
        "\n".join(top_lines) if top_lines else "  (no tenant tag)",
        dump_path or "(file dump unavailable)",
    )


def _tenant_class_breakdown(report: Dict[str, Any],
                              tenant_id: str) -> Dict[str, int]:
    def _count(rows: List[Dict[str, Any]]) -> int:
        return sum(1 for r in rows if r.get("tenant_id") == tenant_id)

    return {
        "customer":  _count(report.get("_all_orphans_customer", [])),
        "technician": _count(report.get("_all_orphans_technician", [])),
        "crew":      _count(report.get("_all_orphans_crew", [])),
    }


async def _log_only_reminder_loop(db: Any,
                                     interval_sec: int) -> None:
    """Recurring CRITICAL nag while log-only mode is active AND
    dangling refs remain.  Runs forever; operators kill it by
    either running F2 apply (drives dangling → 0 so next tick is a
    no-op) or restarting with ``INTEGRITY_CHECK_ENFORCE=true``
    (next boot fails fast, this task never gets scheduled)."""
    while True:
        try:
            await asyncio.sleep(interval_sec)
            report = await scan_dangling_refs(db)
            total = report["summary"]["total_dangling_refs"]
            if total == 0:
                logger.info(
                    "[integrity_check] [LOG-ONLY REMINDER] state is "
                    "now clean — 0 dangling refs. Consider setting "
                    "INTEGRITY_CHECK_ENFORCE=true on next deploy.",
                )
                return    # exit loop; operator flipped back to clean state
            logger.critical(
                "[integrity_check] [LOG-ONLY REMINDER · every %ds] "
                "%d dangling refs still present across %d tenant(s). "
                "This is NOT a stable operating mode. Run F2 "
                "data-repair and restore INTEGRITY_CHECK_ENFORCE=true.",
                interval_sec, total,
                len(report.get("tenant_breakdown") or {}),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:      # noqa: BLE001
            logger.warning(
                "[integrity_check] reminder tick crashed: %s", exc,
            )


def start_log_only_reminder_task(db: Any,
                                    *,
                                    interval_sec: Optional[int] = None,
                                    ) -> Optional[asyncio.Task]:
    """Schedule the log-only-mode reminder loop.  ONLY safe to call
    when ``enforce=False`` AND the boot scan surfaced dangling
    refs — server.py's startup wrapper enforces both.  Returns the
    ``Task`` handle so callers can cancel it in tests or on
    shutdown."""
    interval = interval_sec or _LOG_ONLY_REMINDER_INTERVAL_SEC
    try:
        loop = asyncio.get_event_loop()
        task = loop.create_task(_log_only_reminder_loop(db, interval))
        logger.info(
            "[integrity_check] log-only reminder scheduled — will "
            "nag every %ds until dangling refs reach 0.", interval,
        )
        return task
    except Exception as exc:      # noqa: BLE001
        logger.warning(
            "[integrity_check] failed to schedule reminder: %s", exc,
        )
        return None
