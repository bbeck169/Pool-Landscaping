"""Phase 34 · Task LL Phase 2 · Feb 2026 — CRM-wide bulk endpoints.

Backend implementation for the 6 approved P0 surfaces (frontend UI
polish shipped separately for the pricebook; the other 5 admin
frontends land in a small UI follow-up). Every endpoint follows the
canonical Task-BB contract:

* `POST /{entity}/bulk-delete`   — soft-delete
* `POST /{entity}/bulk-update`   — allow-listed field patch
* Both accept `{ids}` OR `{query_selector, exclude_ids}` (Task EE).
* Admin/super_admin/owner via `require_admin`.
* Tenant-scoped. 400-row cap (Task DD). Audit-logged. Idempotent
  (duplicate ids in payload de-duped). Never cascade.

Fields patchable per surface (server-side allow-list — never accepts
arbitrary keys):
* customers: `tag`, `assigned_owner_id`
* jobs: `technician_id`, `status`, `scheduled_date`
* tasks: `assignee_id`, `status`, `due_date`
* email_templates: `category`, `is_archived`
* sms_templates: `category`
* Communications: bulk-archive + bulk-mark-as-read only (NO delete).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()

_CAP = 400


class _BulkIdsIn(BaseModel):
    ids: Optional[List[str]] = None
    query_selector: Optional[Dict[str, Any]] = None
    exclude_ids: Optional[List[str]] = None


class _BulkUpdateIn(_BulkIdsIn):
    patch: Dict[str, Any]


async def _resolve_ids(coll: str, tenant_id: str, selector: Dict[str, Any],
                          exclude: List[str], allowed_keys: set) -> List[str]:
    q: Dict[str, Any] = {"tenant_id": tenant_id,
                            "$or": [{"deleted_at": None},
                                        {"deleted_at": {"$exists": False}}]}
    clean = {k: v for k, v in (selector or {}).items() if k in allowed_keys}
    if clean.get("search"):
        s = str(clean.pop("search")).strip()
        if s:
            q.setdefault("$and", []).append({"$or": [
                {"name": {"$regex": s, "$options": "i"}},
                {"title": {"$regex": s, "$options": "i"}},
                {"subject": {"$regex": s, "$options": "i"}},
            ]})
    q.update(clean)
    excl = set(exclude or [])
    ids: List[str] = []
    async for row in db[coll].find(q, {"_id": 0, "id": 1}).limit(_CAP + 1):
        rid = row.get("id")
        if rid and rid not in excl:
            ids.append(rid)
    return ids


async def _write_audit(action: str, actor: dict, tenant_id: str,
                         target_id: str, **extra) -> None:
    try:
        await db.audit_log.insert_one({
            "id": new_id(), "tenant_id": tenant_id,
            "actor_user_id": actor.get("id"),
            "actor_email": actor.get("email"),
            "action": action, "target_id": target_id,
            "at": now_iso(), **extra,
        })
    except Exception as e:                                       # noqa: BLE001
        logger.warning(f"[LL-P2] audit {action} failed: {e}")


async def _generic_bulk_delete(coll: str, action: str, ids: List[str],
                                 user: dict, tenant: dict,
                                 locked_check=None) -> dict:
    ids = list(dict.fromkeys(ids or []))
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _CAP:
        raise HTTPException(400, f"bulk-delete capped at {_CAP} rows per call")
    deleted: List[str] = []
    failed: List[dict] = []
    for _id in ids:
        row = await db[coll].find_one(
            {"id": _id, "tenant_id": tenant["id"]}, {"_id": 0},
        )
        if not row:
            failed.append({"id": _id, "reason": "Not found", "status_code": 404})
            continue
        if row.get("deleted_at"):
            deleted.append(_id); continue
        if locked_check:
            reason = await locked_check(row)
            if reason:
                failed.append({"id": _id, "reason": reason, "status_code": 409})
                continue
        await db[coll].update_one(
            {"id": _id, "tenant_id": tenant["id"]},
            {"$set": {"deleted_at": now_iso(),
                        "deleted_by_user_id": user.get("id")}},
        )
        await _write_audit(action, user, tenant["id"], _id)
        deleted.append(_id)
    return {"ok": True, "deleted_count": len(deleted),
              "deleted": deleted, "failed": failed}


async def _generic_bulk_update(coll: str, action: str, ids: List[str],
                                 patch: Dict[str, Any], allowed_fields: set,
                                 user: dict, tenant: dict) -> dict:
    ids = list(dict.fromkeys(ids or []))
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _CAP:
        raise HTTPException(400, f"bulk-update capped at {_CAP} rows per call")
    clean = {k: v for k, v in (patch or {}).items() if k in allowed_fields}
    if not clean:
        raise HTTPException(
            422,
            f"patch must include at least one of: {sorted(allowed_fields)}",
        )
    clean["updated_at"] = now_iso()
    clean["updated_by_user_id"] = user.get("id")
    updated: List[str] = []
    failed: List[dict] = []
    for _id in ids:
        res = await db[coll].update_one(
            {"id": _id, "tenant_id": tenant["id"]},
            {"$set": clean},
        )
        if res.matched_count == 0:
            failed.append({"id": _id, "reason": "Not found", "status_code": 404})
            continue
        await _write_audit(action, user, tenant["id"], _id,
                              patch_fields=sorted(clean.keys()))
        updated.append(_id)
    return {"ok": True, "updated_count": len(updated),
              "updated": updated, "failed": failed}


# ──── Customers ─────────────────────────────────────────────────────────
_CUSTOMER_SELECTOR = {"search", "tag", "assigned_owner_id"}
_CUSTOMER_PATCH_ALLOWED = {"tag", "assigned_owner_id"}


async def _customer_locked(row: dict) -> Optional[str]:
    # Never cascade — refuse if the customer has any active invoice.
    linked = await db.quotes.count_documents({
        "customer_id": row.get("id"), "tenant_id": row.get("tenant_id"),
        "doc_type": "invoice",
        "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
    })
    if linked:
        return f"Customer has {linked} active invoice(s) — archive them first"
    return None


@router.post("/customers/bulk-delete", operation_id="customers.bulkDelete")
async def customers_bulk_delete(body: _BulkIdsIn,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("customers", tenant["id"], body.query_selector or {},
                                    body.exclude_ids or [], _CUSTOMER_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_delete("customers", "customer.soft_delete",
                                          ids, user, tenant, _customer_locked)


@router.post("/customers/bulk-update", operation_id="customers.bulkUpdate")
async def customers_bulk_update(body: _BulkUpdateIn,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("customers", tenant["id"], body.query_selector or {},
                                    body.exclude_ids or [], _CUSTOMER_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_update("customers", "customer.bulk_update", ids,
                                          body.patch, _CUSTOMER_PATCH_ALLOWED,
                                          user, tenant)


# ──── Jobs ──────────────────────────────────────────────────────────────
_JOB_SELECTOR = {"search", "status", "technician_id", "customer_id"}
_JOB_PATCH_ALLOWED = {"technician_id", "status", "scheduled_date"}
# Special server-computed patch field (Feb 2026 · Task LL follow-up).
_JOB_SPECIAL_PATCH = {"scheduled_date_shift_days"}


async def _jobs_bulk_shift(ids: List[str], shift_days: int,
                              user: dict, tenant: dict,
                              anchor_unscheduled_from_today: bool = False) -> dict:
    """Per-row scheduled_date shift. Uses each job's existing
    ``scheduled_date`` as the anchor and adds/subtracts N days. Jobs
    without a ``scheduled_date`` land in ``failed[]`` unless
    ``anchor_unscheduled_from_today`` is True — in which case they get
    a fresh date of ``today + shift_days`` (tenant TZ if available)."""
    updated: List[str] = []
    failed: List[dict] = []
    stamp = now_iso()
    anchor_count = 0
    # Compute "today" once. Prefer tenant timezone if present.
    tz_name = (tenant or {}).get("timezone")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime as _dt
            today = _dt.now(ZoneInfo(tz_name)).date()
        except Exception:                                            # noqa: BLE001
            from datetime import datetime as _dt, timezone as _tz
            today = _dt.now(_tz.utc).date()
    else:
        from datetime import datetime as _dt, timezone as _tz
        today = _dt.now(_tz.utc).date()
    for _id in ids:
        row = await db.jobs.find_one(
            {"id": _id, "tenant_id": tenant["id"]},
            {"_id": 0, "scheduled_date": 1},
        )
        if row is None:
            failed.append({"id": _id, "reason": "Not found", "status_code": 404})
            continue
        cur = row.get("scheduled_date")
        if not cur:
            if not anchor_unscheduled_from_today:
                failed.append({"id": _id,
                                  "reason": "Job has no scheduled_date to shift",
                                  "status_code": 409})
                continue
            new_date = (today + timedelta(days=shift_days)).isoformat()
            anchor_count += 1
        else:
            try:
                base = date.fromisoformat(cur[:10])
            except ValueError:
                failed.append({"id": _id,
                                  "reason": "Existing scheduled_date is unparseable",
                                  "status_code": 409})
                continue
            new_date = (base + timedelta(days=shift_days)).isoformat()
        await db.jobs.update_one(
            {"id": _id, "tenant_id": tenant["id"]},
            {"$set": {"scheduled_date": new_date,
                        "updated_at": stamp,
                        "updated_by_user_id": user.get("id")}},
        )
        await _write_audit("job.bulk_update", user, tenant["id"], _id,
                              patch_fields=["scheduled_date"],
                              shift_days=shift_days,
                              anchored=(anchor_unscheduled_from_today and not cur))
        updated.append(_id)
    return {"ok": True, "updated_count": len(updated),
              "updated": updated, "failed": failed,
              "anchored_count": anchor_count}


async def _job_locked(row: dict) -> Optional[str]:
    if row.get("timer_started_at") and not row.get("timer_stopped_at"):
        return "Job has an active timer — stop the timer before deleting"
    if row.get("status") == "completed" and row.get("invoice_id"):
        return "Completed jobs with an invoice cannot be bulk-deleted"
    return None


@router.post("/jobs/bulk-delete", operation_id="jobs.bulkDelete")
async def jobs_bulk_delete(body: _BulkIdsIn,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("jobs", tenant["id"], body.query_selector or {},
                                    body.exclude_ids or [], _JOB_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_delete("jobs", "job.soft_delete", ids,
                                          user, tenant, _job_locked)


@router.post("/jobs/bulk-update", operation_id="jobs.bulkUpdate")
async def jobs_bulk_update(body: _BulkUpdateIn,
                             user: dict = Depends(require_admin),
                             tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("jobs", tenant["id"], body.query_selector or {},
                                    body.exclude_ids or [], _JOB_SELECTOR)
              if body.query_selector else list(body.ids or []))
    # Feb 2026 · Task LL follow-up — relative-shift branch. Mutually
    # exclusive with a static ``scheduled_date`` in the same patch.
    patch = body.patch or {}
    if "scheduled_date_shift_days" in patch:
        if "scheduled_date" in patch:
            raise HTTPException(
                422,
                "patch cannot contain both scheduled_date and "
                "scheduled_date_shift_days — pick one",
            )
        try:
            shift_days = int(patch["scheduled_date_shift_days"])
        except (TypeError, ValueError):
            raise HTTPException(422, "scheduled_date_shift_days must be an integer")
        # De-dup + cap parity with _generic_bulk_update.
        ids = list(dict.fromkeys(ids or []))
        if not ids:
            raise HTTPException(400, "ids is empty")
        if len(ids) > _CAP:
            raise HTTPException(400, f"bulk-update capped at {_CAP} rows per call")
        return await _jobs_bulk_shift(
            ids, shift_days, user, tenant,
            anchor_unscheduled_from_today=bool(patch.get("anchor_unscheduled_from_today")),
        )
    return await _generic_bulk_update("jobs", "job.bulk_update", ids,
                                          patch, _JOB_PATCH_ALLOWED,
                                          user, tenant)


# ──── Tasks / Follow-ups ────────────────────────────────────────────────
_TASK_SELECTOR = {"search", "status", "assignee_id"}
_TASK_PATCH_ALLOWED = {"assignee_id", "status", "due_date"}


@router.post("/tasks/bulk-delete", operation_id="tasks.bulkDelete")
async def tasks_bulk_delete(body: _BulkIdsIn,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("tasks", tenant["id"], body.query_selector or {},
                                    body.exclude_ids or [], _TASK_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_delete("tasks", "task.soft_delete", ids,
                                          user, tenant)


@router.post("/tasks/bulk-update", operation_id="tasks.bulkUpdate")
async def tasks_bulk_update(body: _BulkUpdateIn,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("tasks", tenant["id"], body.query_selector or {},
                                    body.exclude_ids or [], _TASK_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_update("tasks", "task.bulk_update", ids,
                                          body.patch, _TASK_PATCH_ALLOWED,
                                          user, tenant)


# ──── Communications — archive + mark-as-read (NO hard delete) ─────────
class _CommsBulkIn(_BulkIdsIn):
    """Communications endpoints intentionally omit the ``patch`` field —
    the only two mass operations are ``archive`` and ``mark_read``."""


@router.post("/communications/bulk-archive",
              operation_id="comms.bulkArchive")
async def comms_bulk_archive(body: _CommsBulkIn,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    ids = list(dict.fromkeys(body.ids or []))
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _CAP:
        raise HTTPException(400, f"bulk-archive capped at {_CAP} rows per call")
    archived: List[str] = []
    failed: List[dict] = []
    for cid in ids:
        res = await db.communication_sends.update_one(
            {"id": cid, "tenant_id": tenant["id"]},
            {"$set": {"archived_at": now_iso(),
                        "archived_by_user_id": user.get("id")}},
        )
        if res.matched_count == 0:
            failed.append({"id": cid, "reason": "Not found",
                              "status_code": 404})
            continue
        await _write_audit("comm.archive", user, tenant["id"], cid)
        archived.append(cid)
    return {"ok": True, "archived_count": len(archived),
              "archived": archived, "failed": failed}


@router.post("/communications/bulk-mark-read",
              operation_id="comms.bulkMarkRead")
async def comms_bulk_mark_read(body: _CommsBulkIn,
                                    user: dict = Depends(require_admin),
                                    tenant: dict = Depends(get_current_tenant)):
    ids = list(dict.fromkeys(body.ids or []))
    if not ids:
        raise HTTPException(400, "ids is empty")
    if len(ids) > _CAP:
        raise HTTPException(400, f"bulk-mark-read capped at {_CAP} rows per call")
    updated: List[str] = []
    failed: List[dict] = []
    for cid in ids:
        res = await db.communication_sends.update_one(
            {"id": cid, "tenant_id": tenant["id"]},
            {"$set": {"read_at": now_iso(),
                        "read_by_user_id": user.get("id")}},
        )
        if res.matched_count == 0:
            failed.append({"id": cid, "reason": "Not found",
                              "status_code": 404})
            continue
        await _write_audit("comm.mark_read", user, tenant["id"], cid)
        updated.append(cid)
    return {"ok": True, "updated_count": len(updated),
              "updated": updated, "failed": failed}


# ──── Email + SMS Templates ─────────────────────────────────────────────
_TEMPLATE_SELECTOR = {"search", "category"}
_EMAIL_TPL_PATCH_ALLOWED = {"category", "is_archived"}
_SMS_TPL_PATCH_ALLOWED = {"category"}


@router.post("/email-templates/bulk-delete",
              operation_id="emailTemplates.bulkDelete")
async def email_templates_bulk_delete(body: _BulkIdsIn,
                                            user: dict = Depends(require_admin),
                                            tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("email_templates", tenant["id"],
                                    body.query_selector or {},
                                    body.exclude_ids or [], _TEMPLATE_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_delete("email_templates",
                                          "email_template.soft_delete",
                                          ids, user, tenant,
                                          locked_check=_email_tpl_locked)


async def _email_tpl_locked(row: dict) -> Optional[str]:
    """Task LL follow-up · Feb 2026 — refuse hard delete of any template
    referenced by an active (non-archived) drip sequence. Preserves
    the audit trail on live campaigns and keeps drips from breaking
    when a step target vanishes."""
    tid = row.get("id")
    n = await db.sequences.count_documents({
        "steps.email_template_id": tid,
        "$or": [{"is_archived": {"$ne": True}}, {"is_archived": {"$exists": False}}],
    })
    if n:
        return f"Template used by {n} active drip sequence(s) — archive instead"
    return None


@router.post("/email-templates/bulk-update",
              operation_id="emailTemplates.bulkUpdate")
async def email_templates_bulk_update(body: _BulkUpdateIn,
                                            user: dict = Depends(require_admin),
                                            tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("email_templates", tenant["id"],
                                    body.query_selector or {},
                                    body.exclude_ids or [], _TEMPLATE_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_update("email_templates",
                                          "email_template.bulk_update",
                                          ids, body.patch,
                                          _EMAIL_TPL_PATCH_ALLOWED,
                                          user, tenant)


@router.post("/sms-templates/bulk-delete",
              operation_id="smsTemplates.bulkDelete")
async def sms_templates_bulk_delete(body: _BulkIdsIn,
                                          user: dict = Depends(require_admin),
                                          tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("sms_templates", tenant["id"],
                                    body.query_selector or {},
                                    body.exclude_ids or [], _TEMPLATE_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_delete("sms_templates",
                                          "sms_template.soft_delete",
                                          ids, user, tenant,
                                          locked_check=_sms_tpl_locked)


async def _sms_tpl_locked(row: dict) -> Optional[str]:
    """Task LL follow-up · Feb 2026 — SMS template live-drip lock."""
    tid = row.get("id")
    n = await db.sequences.count_documents({
        "steps.sms_template_id": tid,
        "$or": [{"is_archived": {"$ne": True}}, {"is_archived": {"$exists": False}}],
    })
    if n:
        return f"Template used by {n} active drip sequence(s) — archive instead"
    return None


@router.post("/sms-templates/bulk-update",
              operation_id="smsTemplates.bulkUpdate")
async def sms_templates_bulk_update(body: _BulkUpdateIn,
                                          user: dict = Depends(require_admin),
                                          tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("sms_templates", tenant["id"],
                                    body.query_selector or {},
                                    body.exclude_ids or [], _TEMPLATE_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_update("sms_templates",
                                          "sms_template.bulk_update",
                                          ids, body.patch,
                                          _SMS_TPL_PATCH_ALLOWED,
                                          user, tenant)
