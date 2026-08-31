"""Feb-2026 · Phase F2 — Data integrity repair (admin-only).

Two separate endpoints for a strict READ-THEN-WRITE workflow:

* ``GET  /admin/data-repair/jobs/dry-run`` — read-only scan. Returns
  every job with a dangling ``customer_id`` (parent customer row was
  hard-deleted), every job with a dangling ``technician_id`` (tech
  row hard-deleted), and every scheduled job with no tech AND no
  crew (flagged for admin visibility only, no repair action). The
  scan mints a ``confirm_token`` and a ``scan_timestamp`` — both
  must be echoed back to the apply endpoint. Reports are persisted
  in ``db.data_integrity_scans`` with a 15-minute expiry so a stale
  admin tab cannot apply an out-of-date report.

* ``POST /admin/data-repair/jobs/apply`` — write step. Requires the
  caller to echo ``confirm_token`` and ``dry_run_scan_timestamp``.
  Re-validates the scan record, then executes the repairs the
  scan captured. Every repair is inserted into
  ``db.data_integrity_repairs`` with a full before/after snapshot.
  Idempotent — a second apply of the same ``run_id`` returns
  ``no-op`` because the ``(run_id, target_id)`` unique index
  rejects duplicate writes.

* ``GET /admin/data-repair/history`` — returns the last 100 repair
  runs, grouped by ``run_id``, for post-hoc audit.

Repair strategy:

* ``orphaned_customer_ref``  → soft-delete the job
  (``status='deleted'``, ``deleted_at=now``,
  ``deleted_reason='data_repair_orphaned_customer'``,
  ``deleted_by_user_id=<super_admin_id>``). Removes the row from
  active schedule/lists while preserving history for audit.
* ``orphaned_technician_ref`` → null out ``technician_id`` (preserve
  ``technician_name`` denorm so historical UI still labels it).
  The job then surfaces in the "unassigned pending" bucket, which
  is the normal state for jobs awaiting dispatch.
* ``unassigned_pending``     → flag only. No write action; these
  jobs are pending-assignment and are surfaced in the report so
  the operator can act on them via the Dispatch board.

Cross-cutting rules:

* super_admin only — enforced by ``require_super_admin``.
* Tenant scope: the scan and apply both run globally (across every
  tenant). Cross-tenant repair is inherent to this cleanup, and
  the super_admin role is the only surface with that authority.
* No transaction. Each repair is idempotent on its own via the
  unique index on ``data_integrity_repairs.(run_id, target_id)``.
  A crash mid-apply leaves a partial audit trail — re-running is
  safe because the unique index skips already-recorded targets.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, new_id, now_iso, require_super_admin

logger = logging.getLogger("data_repair")
router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════
SCAN_TTL_SECONDS = 15 * 60           # 15-minute expiry on scan reports
DRY_RUN_CACHE_TTL_SECONDS = 60       # 60-second in-memory cache
_UNASSIGNED_STATUSES = {"requested", "pending", "scheduled", "active"}

# In-memory dry-run cache — per-process. Not a security control (the
# scan is idempotent by design); just prevents dashboard hammering.
_dry_run_cache: Dict[str, Any] = {"expires_at": 0.0, "payload": None}
_dry_run_cache_lock = asyncio.Lock()


# ═══════════════════════════════════════════════════════════════════
# Index bootstrap — run once at import so re-runs of the apply
# endpoint are strictly idempotent. Cheap: create_index dedupes.
# ═══════════════════════════════════════════════════════════════════
async def ensure_indexes() -> None:
    """Called from server.py boot. Idempotent."""
    try:
        await db.data_integrity_repairs.create_index(
            [("run_id", 1), ("target_id", 1)],
            unique=True,
            name="data_repair_run_target_unique",
            background=True,
        )
    except Exception as exc:  # noqa: BLE001 — never block boot
        logger.warning("data_integrity_repairs index create failed: %s", exc)
    try:
        await db.data_integrity_scans.create_index(
            [("confirm_token", 1)],
            unique=True,
            name="data_repair_scan_token_unique",
            background=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("data_integrity_scans index create failed: %s", exc)
    # Feb-2026 · Phase F2 addendum (testing agent action item) — TTL
    # index on ``expires_at`` so expired scan records are reaped by
    # Mongo instead of accumulating forever. expireAfterSeconds=0 →
    # Mongo evicts as soon as ``expires_at`` is in the past.
    try:
        await db.data_integrity_scans.create_index(
            [("expires_at", 1)],
            name="data_repair_scan_expires_ttl",
            expireAfterSeconds=0,
            background=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("data_integrity_scans TTL index create failed: %s", exc)


# ═══════════════════════════════════════════════════════════════════
# Scan primitives — plain awaits, easy to unit-test.
# ═══════════════════════════════════════════════════════════════════
async def _live_customer_ids() -> set:
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


async def _live_technician_ids() -> set:
    """Union of ``technicians.id`` and the user_id space used by
    older seeds — the same id-space accepted by
    ``services/authz.is_tech_authorized_on_job``."""
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


def _active_job_filter() -> Dict[str, Any]:
    return {"$or": [
        {"deleted_at": None},
        {"deleted_at": {"$exists": False}},
    ]}


async def _scan_dangling_refs() -> Dict[str, List[Dict[str, Any]]]:
    """Walk every active job, classify by dangling-ref class.

    Returns three lists (orphan customer, orphan tech, unassigned).
    """
    live_customers = await _live_customer_ids()
    live_techs = await _live_technician_ids()

    orphaned_customer: List[Dict[str, Any]] = []
    orphaned_technician: List[Dict[str, Any]] = []
    unassigned: List[Dict[str, Any]] = []

    cursor = db.jobs.find(
        _active_job_filter(),
        {
            "_id": 0, "id": 1, "tenant_id": 1, "customer_id": 1,
            "customer_name": 1, "technician_id": 1, "technician_name": 1,
            "crew_id": 1, "scheduled_date": 1, "status": 1, "title": 1,
        },
    )
    async for job in cursor:
        cid = job.get("customer_id")
        tid = job.get("technician_id")

        # Class 1 — orphan customer.
        if cid and cid not in live_customers:
            orphaned_customer.append({
                "job_id": job["id"],
                "tenant_id": job.get("tenant_id"),
                "customer_id": cid,
                "customer_name_denorm": job.get("customer_name") or "",
                "scheduled_at": job.get("scheduled_date"),
                "would_action": "soft_delete",
            })
            # A job with an orphaned customer is de facto broken —
            # don't ALSO flag it under other classes.
            continue

        # Class 2 — orphan technician.
        if tid and tid not in live_techs:
            orphaned_technician.append({
                "job_id": job["id"],
                "tenant_id": job.get("tenant_id"),
                "technician_id": tid,
                "technician_name_denorm": job.get("technician_name") or "",
                "scheduled_at": job.get("scheduled_date"),
                "would_action": "null_technician_id",
            })
            continue

        # Class 3 — unassigned pending (flag only).
        status = (job.get("status") or "").lower()
        if (
            not tid
            and not job.get("crew_id")
            and status in _UNASSIGNED_STATUSES
        ):
            unassigned.append({
                "job_id": job["id"],
                "tenant_id": job.get("tenant_id"),
                "title": job.get("title") or "",
                "status": status,
                "scheduled_at": job.get("scheduled_date"),
                "would_action": "flag_only",
            })

    return {
        "orphaned_customer_refs": orphaned_customer,
        "orphaned_technician_refs": orphaned_technician,
        "unassigned_pending_jobs": unassigned,
    }


# ═══════════════════════════════════════════════════════════════════
# GET /admin/data-repair/jobs/dry-run
# ═══════════════════════════════════════════════════════════════════
@router.get("/admin/data-repair/jobs/dry-run")
async def data_repair_dry_run(
    user: Dict[str, Any] = Depends(require_super_admin),
) -> Dict[str, Any]:
    """Scan every active job for dangling refs. READ-ONLY."""
    now = time.monotonic()
    async with _dry_run_cache_lock:
        if _dry_run_cache["payload"] and _dry_run_cache["expires_at"] > now:
            # Serve the cached payload verbatim (same ``confirm_token``
            # + ``scan_timestamp``). The 60-s in-memory cache is only
            # about avoiding a re-scan; it deliberately keeps the
            # token identity stable so a dashboard poll doesn't churn
            # scan documents. Apply-side freshness is enforced by the
            # scan record's own 15-min ``expires_at`` (see
            # ``_load_scan``) — plenty of runway relative to a 60-s
            # cache window.
            return _dry_run_cache["payload"]

        classes = await _scan_dangling_refs()

    total_would_change = (
        len(classes["orphaned_customer_refs"])
        + len(classes["orphaned_technician_refs"])
    )
    total_flagged = len(classes["unassigned_pending_jobs"])

    confirm_token = new_id()
    scan_timestamp = now_iso()
    scan_doc = {
        "confirm_token": confirm_token,
        "scan_timestamp": scan_timestamp,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(
            seconds=SCAN_TTL_SECONDS,
        ),
        "actor_user_id": user.get("id"),
        "classes": classes,
        "summary": {
            "total_would_change": total_would_change,
            "total_flagged_no_action": total_flagged,
        },
    }
    try:
        await db.data_integrity_scans.insert_one(scan_doc)
    except Exception as exc:  # pragma: no cover — best-effort
        logger.warning("data_integrity_scans insert failed: %s", exc)

    payload = {
        "scan_timestamp": scan_timestamp,
        "confirm_token": confirm_token,
        **classes,
        "summary": scan_doc["summary"],
        "ttl_seconds": SCAN_TTL_SECONDS,
    }
    _dry_run_cache["payload"] = payload
    _dry_run_cache["expires_at"] = time.monotonic() + DRY_RUN_CACHE_TTL_SECONDS
    return payload


# ═══════════════════════════════════════════════════════════════════
# POST /admin/data-repair/jobs/apply
# ═══════════════════════════════════════════════════════════════════
class ApplyIn(BaseModel):
    confirm_token: str = Field(..., min_length=8, max_length=100)
    dry_run_scan_timestamp: str = Field(..., min_length=10)


async def _load_scan(confirm_token: str,
                      scan_timestamp: str) -> Dict[str, Any]:
    scan = await db.data_integrity_scans.find_one(
        {"confirm_token": confirm_token}, {"_id": 0},
    )
    if not scan:
        raise HTTPException(400, "unknown or expired confirm_token")
    if scan.get("scan_timestamp") != scan_timestamp:
        raise HTTPException(400, "scan_timestamp mismatch")
    expires_at = scan.get("expires_at")
    if isinstance(expires_at, datetime):
        # BSON has no tz — Motor hands back offset-naive UTC datetimes.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            raise HTTPException(400, "scan expired — please re-run dry-run")
    else:
        raise HTTPException(400, "malformed scan record")
    return scan


async def _apply_orphan_customer(
    job_row: Dict[str, Any],
    run_id: str,
    actor_user_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Soft-delete an orphaned-customer job. Idempotent — a repair
    audit row already present short-circuits."""
    jid = job_row["job_id"]
    tid = job_row.get("tenant_id")
    existing = await db.data_integrity_repairs.find_one(
        {"run_id": run_id, "target_id": jid}, {"_id": 0, "id": 1},
    )
    if existing:
        return None

    before = await db.jobs.find_one(
        {"id": jid, "tenant_id": tid},
        {"_id": 0, "id": 1, "tenant_id": 1, "customer_id": 1,
         "customer_name": 1, "status": 1, "deleted_at": 1},
    )
    if not before:
        return None
    if before.get("deleted_at"):
        # Already soft-deleted — still record the no-op so the audit
        # log is complete.
        after = before
    else:
        deleted_at = now_iso()
        await db.jobs.update_one(
            {"id": jid, "tenant_id": tid},
            {"$set": {
                "status": "deleted",
                "deleted_at": deleted_at,
                "deleted_by_user_id": actor_user_id,
                "deleted_reason": "data_repair_orphaned_customer",
                # F2 addendum — stamp ``updated_at`` for parity with
                # the orphan-technician path so both repair actions
                # touch the same audit metadata.
                "updated_at": deleted_at,
            }},
        )
        after = {
            **before,
            "status": "deleted",
            "deleted_at": deleted_at,
            "deleted_reason": "data_repair_orphaned_customer",
        }

    audit_id = new_id()
    audit_doc = {
        "id": audit_id,
        "run_id": run_id,
        "run_timestamp": now_iso(),
        "actor_user_id": actor_user_id,
        "target_collection": "jobs",
        "target_id": jid,
        "tenant_id": tid,
        "class": "orphaned_customer_ref",
        "action": "soft_delete",
        "before": before,
        "after": after,
    }
    try:
        await db.data_integrity_repairs.insert_one(audit_doc)
    except Exception as exc:  # pragma: no cover — unique-index race
        logger.info("data_integrity_repairs dedup on %s: %s", jid, exc)
        return None
    return audit_doc


async def _apply_orphan_technician(
    job_row: Dict[str, Any],
    run_id: str,
    actor_user_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Null out ``technician_id`` on an orphan-tech job. Preserves
    the ``technician_name`` denorm for historical display."""
    jid = job_row["job_id"]
    tid = job_row.get("tenant_id")
    existing = await db.data_integrity_repairs.find_one(
        {"run_id": run_id, "target_id": jid}, {"_id": 0, "id": 1},
    )
    if existing:
        return None

    before = await db.jobs.find_one(
        {"id": jid, "tenant_id": tid},
        {"_id": 0, "id": 1, "tenant_id": 1, "technician_id": 1,
         "technician_name": 1, "status": 1},
    )
    if not before:
        return None
    if before.get("technician_id") is None:
        after = before
    else:
        await db.jobs.update_one(
            {"id": jid, "tenant_id": tid},
            {"$set": {"technician_id": None,
                       "updated_at": now_iso()}},
        )
        after = {**before, "technician_id": None}

    audit_id = new_id()
    audit_doc = {
        "id": audit_id,
        "run_id": run_id,
        "run_timestamp": now_iso(),
        "actor_user_id": actor_user_id,
        "target_collection": "jobs",
        "target_id": jid,
        "tenant_id": tid,
        "class": "orphaned_technician_ref",
        "action": "null_technician_id",
        "before": before,
        "after": after,
    }
    try:
        await db.data_integrity_repairs.insert_one(audit_doc)
    except Exception as exc:  # pragma: no cover — unique-index race
        logger.info("data_integrity_repairs dedup on %s: %s", jid, exc)
        return None
    return audit_doc


@router.post("/admin/data-repair/jobs/apply")
async def data_repair_apply(
    body: ApplyIn,
    user: Dict[str, Any] = Depends(require_super_admin),
) -> Dict[str, Any]:
    """Apply the repairs captured by a previous dry-run scan."""
    scan = await _load_scan(body.confirm_token, body.dry_run_scan_timestamp)
    run_id = body.confirm_token   # confirm_token doubles as the run_id
    actor = user.get("id")

    classes = scan.get("classes") or {}
    orphan_customers = classes.get("orphaned_customer_refs") or []
    orphan_techs = classes.get("orphaned_technician_refs") or []

    applied: List[Dict[str, Any]] = []
    for row in orphan_customers:
        result = await _apply_orphan_customer(row, run_id, actor)
        if result:
            applied.append(result)
    for row in orphan_techs:
        result = await _apply_orphan_technician(row, run_id, actor)
        if result:
            applied.append(result)

    # Invalidate the in-memory dry-run cache so a subsequent GET
    # returns a fresh (post-repair) scan.
    async with _dry_run_cache_lock:
        _dry_run_cache["payload"] = None
        _dry_run_cache["expires_at"] = 0.0

    return {
        "run_id": run_id,
        "run_timestamp": now_iso(),
        "changes_applied": len(applied),
        "audit_log_ids": [row["id"] for row in applied],
        "no_op": len(applied) == 0,
    }


# ═══════════════════════════════════════════════════════════════════
# GET /admin/data-repair/history
# ═══════════════════════════════════════════════════════════════════
@router.get("/admin/data-repair/history")
async def data_repair_history(
    user: Dict[str, Any] = Depends(require_super_admin),  # noqa: ARG001
) -> Dict[str, Any]:
    """Return the last 100 repair rows grouped by ``run_id``."""
    rows = await db.data_integrity_repairs.find(
        {}, {"_id": 0},
    ).sort("run_timestamp", -1).to_list(100)

    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        run_id = row.get("run_id") or "unknown"
        bucket = grouped.setdefault(run_id, {
            "run_id": run_id,
            "run_timestamp": row.get("run_timestamp"),
            "actor_user_id": row.get("actor_user_id"),
            "changes": [],
        })
        bucket["changes"].append({
            "target_id": row.get("target_id"),
            "class": row.get("class"),
            "action": row.get("action"),
            "tenant_id": row.get("tenant_id"),
        })
    return {"runs": list(grouped.values()), "row_count": len(rows)}


# ═══════════════════════════════════════════════════════════════════
# Phase F9 · Feb-2026 — Data-repair status endpoint
# ═══════════════════════════════════════════════════════════════════
#
# Read-only rollup so super_admin can see F3/F6/F2 state at a glance
# without grepping logs.  Consolidates four independent sources:
#
#   1. current_state        — freshest snapshot from the most recent
#                              F6 diagnostic dump file on disk (F6
#                              only writes when refs > 0, so an
#                              absent file means "clean at last boot").
#   2. last_dry_run         — newest doc in ``data_integrity_scans``.
#   3. last_apply           — newest ``run_id`` in ``data_integrity_repairs``.
#   4. last_dump_file       — path + ctime + row count of the most
#                              recent integrity_dump JSON file.
#
# Every source is best-effort — missing data returns ``None`` in
# place, never 500.  Endpoint is super_admin only.
# ═══════════════════════════════════════════════════════════════════
import os as _os
import glob as _glob
import json as _json


def _integrity_dump_dir() -> str:
    """Where F6 writes the diagnostic JSON dumps.  Mirrors
    ``services/startup/integrity_check.py`` so a config change on
    one side automatically shows up here."""
    return _os.environ.get("INTEGRITY_DUMP_DIR", "/app/backend/logs")


def _read_latest_integrity_dump() -> Optional[Dict[str, Any]]:
    """Return the most-recent F6 diagnostic dump payload, or ``None``.
    Never raises — a corrupt dump file logs and returns ``None`` so
    the status endpoint stays green even if a dump is being written
    concurrently.

    "Most recent" is determined by **filename** — F6 dumps use ISO
    timestamps in the filename (``integrity_dump_YYYY-MM-DDTHH-MM-SSZ.json``)
    so lexicographic sort ≡ chronological sort.  Filename-based sort
    is more robust than ``getctime`` across filesystems that don't
    reliably distinguish sub-second file creations (docker overlays,
    tmpfs) and is what F6 already commits to.
    """
    try:
        pattern = _os.path.join(_integrity_dump_dir(), "integrity_dump_*.json")
        matches = _glob.glob(pattern)
        if not matches:
            return None
        latest = sorted(matches, key=_os.path.basename)[-1]
        with open(latest, "r") as fh:
            data = _json.load(fh)
        data["_source_path"] = latest
        data["_source_ctime"] = datetime.fromtimestamp(
            _os.path.getmtime(latest), tz=timezone.utc,
        ).isoformat().replace("+00:00", "Z")
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("[f9-status] failed to read latest dump: %s", exc)
        return None


def _current_enforce_mode() -> bool:
    """True when INTEGRITY_CHECK_ENFORCE is unset or truthy.  Mirrors
    ``services/startup/integrity_check.py::_enforce_flag_from_env``
    minus the APP_ENV fallback logic — deliberately conservative so
    the read is stable across restarts."""
    raw = _os.environ.get("INTEGRITY_CHECK_ENFORCE")
    if raw is None:
        # Fall back to APP_ENV=production → enforce=True default.
        return _os.environ.get("APP_ENV", "").lower() == "production"
    return raw.strip().lower() in ("1", "true", "yes", "on")


@router.get("/admin/data-repair/status")
async def data_repair_status(
    user: Dict[str, Any] = Depends(require_super_admin),  # noqa: ARG001
) -> Dict[str, Any]:
    """Read-only rollup of F3/F6/F2 state.  Super_admin only.

    See module docstring for source-of-truth mapping.  Every field
    can be ``None`` on a fresh workspace with no scan/repair history.
    """
    # ── 1. current_state (from latest F6 diagnostic dump) ─────────
    dump = _read_latest_integrity_dump()
    enforce_mode = _current_enforce_mode()
    if dump:
        totals = dump.get("totals") or {}
        current_state = {
            "dangling_refs_total": int(totals.get("total") or 0),
            "dangling_refs_by_class": {
                "customer":   int(totals.get("customer") or 0),
                "technician": int(totals.get("technician") or 0),
                "crew":       int(totals.get("crew") or 0),
            },
            "enforce_mode": enforce_mode,
            "log_only_mode_active": (
                not enforce_mode and int(totals.get("total") or 0) > 0
            ),
            "snapshot_source": "integrity_dump_file",
            "snapshot_at": dump.get("timestamp") or dump.get("_source_ctime"),
        }
    else:
        # No dump on disk → boot was clean OR no boot has run yet
        # under log-only mode.  Report zeros with a source hint so
        # the UI can distinguish "clean" from "unknown".
        current_state = {
            "dangling_refs_total": 0,
            "dangling_refs_by_class": {"customer": 0, "technician": 0,
                                        "crew": 0},
            "enforce_mode": enforce_mode,
            "log_only_mode_active": False,
            "snapshot_source": "no_dump_on_disk",
            "snapshot_at": None,
        }

    # ── 2. last_dry_run (newest data_integrity_scans doc) ─────────
    last_dry_run: Optional[Dict[str, Any]] = None
    try:
        scan = await db.data_integrity_scans.find_one(
            {}, {"_id": 0}, sort=[("scan_timestamp", -1)],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[f9-status] scan read failed: %s", exc)
        scan = None
    if scan:
        expires_at = scan.get("expires_at")
        if isinstance(expires_at, datetime):
            confirm_expires_iso = expires_at.replace(
                tzinfo=expires_at.tzinfo or timezone.utc,
            ).isoformat()
            expired = expires_at < datetime.now(timezone.utc).replace(
                tzinfo=expires_at.tzinfo or timezone.utc,
            )
        else:
            confirm_expires_iso = None
            expired = True
        summary = scan.get("summary") or {}
        last_dry_run = {
            "scan_timestamp": scan.get("scan_timestamp"),
            "actor_user_id": scan.get("actor_user_id"),
            "total_would_change": int(summary.get("total_would_change") or 0),
            "total_flagged_no_action": int(
                summary.get("total_flagged_no_action") or 0
            ),
            "confirm_token_expires_at": None if expired else confirm_expires_iso,
        }

    # ── 3. last_apply (newest run_id in data_integrity_repairs) ────
    last_apply: Optional[Dict[str, Any]] = None
    try:
        newest_repair = await db.data_integrity_repairs.find_one(
            {}, {"_id": 0}, sort=[("run_timestamp", -1)],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[f9-status] repair read failed: %s", exc)
        newest_repair = None
    if newest_repair and newest_repair.get("run_id"):
        run_id = newest_repair["run_id"]
        try:
            changes_count = await db.data_integrity_repairs.count_documents(
                {"run_id": run_id},
            )
        except Exception:  # noqa: BLE001
            changes_count = None
        last_apply = {
            "run_id": run_id,
            "run_timestamp": newest_repair.get("run_timestamp"),
            "actor_user_id": newest_repair.get("actor_user_id"),
            "changes_applied": changes_count,
        }

    # ── 4. last_dump_file (path + ctime + row count) ──────────────
    last_dump_file: Optional[Dict[str, Any]] = None
    if dump:
        # Derive row count from the dump's orphans arrays (F6 dumps
        # the FULL orphan list, not the 20-row sample cap).
        orphans = dump.get("orphans") or {}
        row_count = (
            len(orphans.get("customer_refs") or [])
            + len(orphans.get("technician_refs") or [])
            + len(orphans.get("crew_refs") or [])
        )
        last_dump_file = {
            "path": dump.get("_source_path"),
            "created_at": dump.get("_source_ctime"),
            "row_count": row_count,
        }

    return {
        "current_state": current_state,
        "last_dry_run": last_dry_run,
        "last_apply": last_apply,
        "last_dump_file": last_dump_file,
    }


# ═══════════════════════════════════════════════════════════════════
# Phase F5 · Feb-2026 — Leads backfill (Website Visitor → real fields)
# ═══════════════════════════════════════════════════════════════════
#
# Companion to F2 above.  Scans ``db.leads`` for empty rows produced
# by pre-F5 form submissions, matches them to their preserved
# ``form_submissions`` row, and re-projects the raw ``values`` dict
# through the shared ``services/lead_extraction`` module.
#
# Same confirm_token / scan_timestamp pattern as F2 above.
# ═══════════════════════════════════════════════════════════════════


@router.get("/admin/data-repair/leads/backfill/dry-run")
async def leads_backfill_dry_run(
    _user: dict = Depends(require_super_admin),
):
    """Read-only scan of ``Website Visitor`` / empty leads that
    could be repaired from their linked ``form_submissions`` row."""
    from services.migrations import leads_backfill_from_form_submissions_v1 as mig
    plan = await mig.plan(db)

    confirm_token = new_id()
    scan_timestamp = now_iso()
    await db.data_integrity_scans.insert_one({
        "confirm_token": confirm_token,
        "scan_timestamp": scan_timestamp,
        "scope": "leads_backfill_v1",
        "candidates_total": plan["candidates_total"],
        "would_change": plan["would_change"],
        "samples": plan["samples"],
        "created_at": scan_timestamp,
    })
    return {
        "scope": "leads_backfill_v1",
        "confirm_token": confirm_token,
        "scan_timestamp": scan_timestamp,
        "candidates_total": plan["candidates_total"],
        "would_change": plan["would_change"],
        "samples": plan["samples"],
    }


class LeadsBackfillApplyRequest(BaseModel):
    confirm_token: str = Field(..., min_length=8, max_length=100)
    dry_run_scan_timestamp: str = Field(..., min_length=10)


@router.post("/admin/data-repair/leads/backfill/apply")
async def leads_backfill_apply(
    body: LeadsBackfillApplyRequest = Body(...),
    user: dict = Depends(require_super_admin),
):
    scan = await db.data_integrity_scans.find_one(
        {"confirm_token": body.confirm_token,
         "scope": "leads_backfill_v1"},
        {"_id": 0},
    )
    if not scan:
        raise HTTPException(400, "unknown or expired confirm_token")
    if scan.get("scan_timestamp") != body.dry_run_scan_timestamp:
        raise HTTPException(400, "scan_timestamp mismatch")

    from services.migrations import leads_backfill_from_form_submissions_v1 as mig
    result = await mig.apply_backfill(db, actor_id=user.get("id"))
    return {
        "scope": "leads_backfill_v1",
        "run_id": body.confirm_token,
        **result,
    }
