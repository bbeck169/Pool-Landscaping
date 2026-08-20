"""Phase 32 · Feb 2026 — Mobile offline capability backend foundation.

Two public endpoints under ``/api/mobile/``:

* ``POST /api/mobile/sync``            — batch-apply operations that a
  tech recorded while offline. Idempotent per ``client_op_id`` — the
  same op replayed produces the same result and never double-applies.
  Conflict policy: mobile wins on ALL entities; the pre-mobile server
  snapshot is captured in ``sync_conflict_log`` so nothing is truly
  lost.
* ``GET  /api/mobile/offline-bundle``  — returns the data slice a tech
  needs to work offline for the next 7 days (their assigned jobs,
  the tiny customer contact fields those jobs reference, any
  in-progress service reports, and the chemistry/chemicals catalogs).
  Response size is capped so mobile can cache safely.

New Mongo collections created lazily (via ``db_indexes.py`` on
startup):

  * ``mobile_devices``          — one row per device that has synced.
  * ``sync_conflict_log``       — mobile-wins audit trail.
  * ``pending_sync_receipts``   — ``client_op_id`` → dedupe receipt,
    60-day TTL.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user, new_id, now_iso

logger = logging.getLogger(__name__)
router = APIRouter()

OFFLINE_BUNDLE_WINDOW_DAYS = 7
BUNDLE_MAX_JOBS = 200
SYNC_RECEIPT_TTL_DAYS = 60

# op_types accepted by /mobile/sync — routed via ``_HANDLERS`` below.
SUPPORTED_OP_TYPES = {
    "job.update", "job.close", "service_report.upsert",
    "photo.upload", "chemistry.record", "chemical.add",
    "checklist.tick", "note.add",
}


# ═══════════ Wire models ═══════════════════════════════════════════════
class _SyncOp(BaseModel):
    client_op_id: str
    op_type: str
    entity_id: str
    payload: Dict[str, Any] = {}
    client_ts: Optional[str] = None


class _SyncBatchIn(BaseModel):
    device_id: str
    operations: List[_SyncOp]
    os: Optional[str] = None
    app_version: Optional[str] = None


# ═══════════ Dedupe / receipt persistence ══════════════════════════════
async def _get_receipt(client_op_id: str, tenant_id: str) -> Optional[dict]:
    return await db.pending_sync_receipts.find_one(
        {"client_op_id": client_op_id, "tenant_id": tenant_id},
        {"_id": 0},
    )


async def _save_receipt(op: _SyncOp, tenant_id: str, user_id: str,
                          result: dict) -> None:
    await db.pending_sync_receipts.insert_one({
        "client_op_id": op.client_op_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "op_type": op.op_type,
        "entity_id": op.entity_id,
        "result": result,
        "created_at": datetime.now(timezone.utc),
    })


async def _log_conflict(op: _SyncOp, tenant_id: str,
                           server_snapshot_before: Any) -> None:
    await db.sync_conflict_log.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "client_op_id": op.client_op_id,
        "op_type": op.op_type,
        "entity_id": op.entity_id,
        "server_snapshot_before": server_snapshot_before,
        "mobile_payload": op.payload,
        "resolution": "mobile_wins",
        "resolved_at": now_iso(),
    })


# ═══════════ Op handlers ═══════════════════════════════════════════════
async def _handle_job_update(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    job = await db.jobs.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"_id": 0})
    if not job:
        raise ValueError("job not found")
    if job:
        await _log_conflict(op, tenant_id, job)
    updates = {k: v for k, v in (op.payload or {}).items()
                if k not in ("id", "tenant_id", "created_at")}
    updates.update({"updated_at": now_iso(),
                      "last_synced_at": now_iso(),
                      "client_op_id": op.client_op_id})
    await db.jobs.update_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"$set": updates})
    return {"server_id": op.entity_id, "server_ts": now_iso()}


async def _handle_job_close(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    job = await db.jobs.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"_id": 0})
    if not job:
        raise ValueError("job not found")
    _prev_status = (job.get("status") or "").lower()
    # Feb-2026 · Chemistry required-readings gate — applied ONLY
    # when this replay actually flips a pool job to ``completed``.
    # A 422 propagates back to the mobile client so the offline
    # replay row stays in the local SQLite queue until the tech
    # fills the missing readings and re-syncs.
    if _prev_status != "completed":
        from services.chemistry_gate import (
            assert_core_readings_present, gather_readings_for_job, is_pool_job,
        )
        if is_pool_job(job):
            rep = await db.service_reports.find_one(
                {"tenant_id": tenant_id, "job_id": op.entity_id},
                {"_id": 0},
            )
            assert_core_readings_present(
                gather_readings_for_job(job, rep),
            )
    await _log_conflict(op, tenant_id, {"status": job.get("status"),
                                            "completed_at": job.get("completed_at")})
    await db.jobs.update_one(
        {"id": op.entity_id, "tenant_id": tenant_id},
        {"$set": {"status": "completed",
                    "completed_at": op.payload.get("completed_at") or now_iso(),
                    "last_synced_at": now_iso(),
                    "client_op_id": op.client_op_id,
                    "updated_at": now_iso()}},
    )
    # Feb-2026 · Door-hanger auto-send on completion transition.
    # Fires only on the pending→completed transition; mobile sync
    # replays of an already-completed job (idempotent close) are
    # silently skipped by the helper too, but this guard keeps
    # semantics identical across write paths.
    if _prev_status != "completed":
        try:
            from routers.workstream_service_log import (
                schedule_auto_send_door_hanger,
            )
            schedule_auto_send_door_hanger(op.entity_id, tenant_id)
        except Exception:
            pass
    return {"server_id": op.entity_id, "server_ts": now_iso()}


async def _handle_service_report_upsert(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    existing = await db.service_reports.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"_id": 0})
    if existing:
        await _log_conflict(op, tenant_id, existing)
        payload = {k: v for k, v in (op.payload or {}).items()
                    if k not in ("id", "tenant_id", "created_at")}
        payload.update({"updated_at": now_iso(),
                         "last_synced_at": now_iso(),
                         "client_op_id": op.client_op_id})
        await db.service_reports.update_one(
            {"id": op.entity_id, "tenant_id": tenant_id},
            {"$set": payload},
        )
    else:
        # Insert fresh — mobile-generated id becomes canonical.
        doc = dict(op.payload or {})
        doc.update({"id": op.entity_id, "tenant_id": tenant_id,
                     "created_at": now_iso(), "updated_at": now_iso(),
                     "last_synced_at": now_iso(),
                     "client_op_id": op.client_op_id,
                     "public_uuid": doc.get("public_uuid") or new_id()})
        await db.service_reports.insert_one(doc)
    return {"server_id": op.entity_id, "server_ts": now_iso()}


async def _handle_photo_upload(op: _SyncOp, tenant_id: str, user_id: str) -> dict:
    """Mobile-side photo upload is 2-step: (a) client uploads the file
    bytes via ``POST /service-reports/{id}/media`` while online-ish,
    (b) records the sync op for bookkeeping. This handler is the
    bookkeeping path — the media row is already in
    ``service_reports.photos`` when it arrives here."""
    return {"server_id": op.entity_id, "server_ts": now_iso(),
              "note": "photo bytes must be uploaded via /service-reports/{id}/media"}


async def _handle_generic_report_field_append(op: _SyncOp, tenant_id: str,
                                                    user_id: str, field: str) -> dict:
    """Common path for chemistry / chemical / checklist / note ops —
    each appends a row into a field on the service_report."""
    report = await db.service_reports.find_one(
        {"id": op.entity_id, "tenant_id": tenant_id}, {"_id": 0, field: 1})
    if not report:
        raise ValueError(f"service_report {op.entity_id} not found")
    # Mobile-wins snapshot log (only when the entry with the same
    # ``client_op_id`` doesn't already exist — otherwise it's just an
    # idempotent replay).
    existing_rows = list(report.get(field) or [])
    if any(isinstance(r, dict) and r.get("client_op_id") == op.client_op_id
             for r in existing_rows):
        return {"server_id": op.entity_id, "server_ts": now_iso(),
                  "note": "idempotent replay"}
    row = dict(op.payload or {})
    row["client_op_id"] = op.client_op_id
    row["synced_at"] = now_iso()
    await db.service_reports.update_one(
        {"id": op.entity_id, "tenant_id": tenant_id},
        {"$push": {field: row},
          "$set": {"last_synced_at": now_iso(), "updated_at": now_iso()}},
    )
    return {"server_id": op.entity_id, "server_ts": now_iso()}


_HANDLERS = {
    "job.update":              _handle_job_update,
    "job.close":               _handle_job_close,
    "service_report.upsert":   _handle_service_report_upsert,
    "photo.upload":            _handle_photo_upload,
    "chemistry.record":        lambda op, t, u: _handle_generic_report_field_append(
                                    op, t, u, "chemical_readings"),
    "chemical.add":            lambda op, t, u: _handle_generic_report_field_append(
                                    op, t, u, "chemicals_added"),
    "checklist.tick":          lambda op, t, u: _handle_generic_report_field_append(
                                    op, t, u, "checklist_events"),
    "note.add":                lambda op, t, u: _handle_generic_report_field_append(
                                    op, t, u, "notes_log"),
}


# ═══════════ POST /api/mobile/sync ═════════════════════════════════════
@router.post("/mobile/sync", operation_id="mobile.sync")
async def mobile_sync(body: _SyncBatchIn,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)) -> dict:
    """Batch-apply mobile offline operations. Idempotent per
    ``client_op_id`` — the same op replayed produces the same result
    each time; conflicts always resolve mobile-wins with a snapshot
    persisted to ``sync_conflict_log``."""
    tenant_id = tenant["id"]
    user_id = user.get("id")

    # Upsert device record for auditing.
    await db.mobile_devices.update_one(
        {"device_id": body.device_id, "tenant_id": tenant_id},
        {"$set": {"user_id": user_id, "last_seen_at": now_iso(),
                    "last_sync_at": now_iso(),
                    "os": body.os, "app_version": body.app_version},
          "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )

    accepted: List[Dict[str, Any]] = []
    failed:   List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []

    for op in body.operations:
        # Idempotency short-circuit.
        prior = await _get_receipt(op.client_op_id, tenant_id)
        if prior:
            accepted.append({
                "client_op_id": op.client_op_id,
                **(prior.get("result") or {}),
                "idempotent_replay": True,
            })
            continue

        if op.op_type not in SUPPORTED_OP_TYPES:
            failed.append({"client_op_id": op.client_op_id,
                             "reason": f"unsupported op_type {op.op_type!r}"})
            continue

        handler = _HANDLERS.get(op.op_type)
        if handler is None:
            failed.append({"client_op_id": op.client_op_id,
                             "reason": "no handler wired"})
            continue

        try:
            result = await handler(op, tenant_id, user_id)
        except ValueError as e:
            failed.append({"client_op_id": op.client_op_id,
                             "reason": str(e)})
            continue
        except Exception as e:                                    # noqa: BLE001
            logger.warning(f"mobile_sync op {op.client_op_id} failed: {e}")
            failed.append({"client_op_id": op.client_op_id,
                             "reason": str(e)[:200]})
            continue

        await _save_receipt(op, tenant_id, user_id, result)
        accepted.append({"client_op_id": op.client_op_id, **result})
        # Every accepted op that touched an entity is treated as
        # conflict-resolved (mobile wins). We echo the resolution back
        # so mobile can badge the timeline entry.
        if op.op_type in ("job.update", "job.close", "service_report.upsert"):
            conflicts.append({"client_op_id": op.client_op_id,
                                 "resolution": "mobile_wins"})

    return {"accepted": accepted, "failed": failed, "conflicts": conflicts}


# ═══════════ GET /api/mobile/offline-bundle ════════════════════════════
@router.get("/mobile/offline-bundle", operation_id="mobile.offlineBundle")
async def mobile_offline_bundle(tech_id: str = "me",
                                     user: dict = Depends(get_current_user),
                                     tenant: dict = Depends(get_current_tenant)) -> dict:
    tenant_id = tenant["id"]
    if tech_id == "me":
        target_tech = user.get("technician_id") or user.get("id")
    else:
        target_tech = tech_id
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=OFFLINE_BUNDLE_WINDOW_DAYS)

    # Jobs assigned to this tech within the 7-day window.
    from utils import not_deleted_filter as _nd
    jobs_cur = db.jobs.find(
        {"tenant_id": tenant_id,
         "$and": [
             {"$or": [{"technician_id": target_tech},
                       {"assigned_tech_id": target_tech}]},
             _nd(),
         ],
         "scheduled_at": {"$lte": horizon.isoformat()}},
        {"_id": 0, "id": 1, "customer_id": 1, "title": 1,
          "service_type": 1, "scheduled_at": 1, "scheduled_end": 1,
          "notes": 1, "status": 1, "checklist_template": 1,
          "address": 1, "customer_name": 1},
    ).sort("scheduled_at", 1).limit(BUNDLE_MAX_JOBS)
    jobs = [j async for j in jobs_cur]

    # Contact info — name + phone + service address only, no other PII.
    customer_ids = list({j.get("customer_id") for j in jobs if j.get("customer_id")})
    customers = []
    if customer_ids:
        async for c in db.customers.find(
                {"id": {"$in": customer_ids}, "tenant_id": tenant_id},
                {"_id": 0, "id": 1, "name": 1, "phone": 1,
                  "address": 1, "address_line_1": 1}):
            customers.append({
                "id": c.get("id"), "name": c.get("name"),
                "phone": c.get("phone"),
                "address": c.get("address_line_1") or c.get("address") or "",
            })

    # In-progress service reports for those jobs.
    job_ids = [j["id"] for j in jobs]
    reports = []
    if job_ids:
        async for r in db.service_reports.find(
                {"tenant_id": tenant_id, "job_id": {"$in": job_ids},
                  "submitted_at": None},
                {"_id": 0}):
            reports.append(r)

    # Chemistry test types + chemicals catalog (small — full copy).
    chemistry_types = []
    async for c in db.chemistry_test_types.find({"tenant_id": tenant_id}, {"_id": 0}):
        chemistry_types.append(c)
    chemicals_catalog = []
    async for c in db.chemicals_catalog.find({"tenant_id": tenant_id}, {"_id": 0}):
        chemicals_catalog.append(c)

    return {
        "jobs": jobs,
        "customers": customers,
        "service_reports_in_progress": reports,
        "chemistry_types": chemistry_types,
        "chemicals_catalog": chemicals_catalog,
        "offline_bundle_expires_at": horizon.isoformat(),
        "generated_at": now.isoformat(),
        "job_count": len(jobs),
        "cap_reached": len(jobs) >= BUNDLE_MAX_JOBS,
    }
