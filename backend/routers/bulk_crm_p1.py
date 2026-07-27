"""Task NN · Feb 2026 — P1 secondary admin bulk endpoints.

Extends Task LL Phase 2 (bulk_crm.py) to 5 additional admin surfaces
that were audited and confirmed to have live Mongo collections:

* Reviews         → ``customer_portal_reviews``
* Team / Users    → ``users``
* Tags (customer) → ``customer_tags``
* Service Reports → ``service_reports``
* Time Entries    → ``time_entries``

Per-surface allow-lists and locked-state guards follow the exact
Task-BB / Task-DD / Task-EE contract. See ``bulk_crm.py`` for the
canonical shared helpers (``_generic_bulk_delete``,
``_generic_bulk_update``, ``_resolve_ids``, ``_write_audit``).

Not shipped in this batch (audit gap — no live collection or the
mapping was ambiguous):
* Referrals — multiple candidate collections (``referral_invites``,
  ``referral_codes``); requires product alignment before shipping.
* Vendors — no ``db.vendors`` collection. Vendor concept currently
  lives under Check-Writer payees; would ship as ``payees``.
* Expenses — no ``db.expenses`` collection.
* Maintenance Schedules — ``maintenance_records`` exists but the
  "schedules" concept aligns more with ``recurring_jobs``. Needs a
  product decision on which entity is the canonical target.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import require_admin
from routers.tenants import get_current_tenant
from routers.bulk_crm import (
    _BulkIdsIn, _BulkUpdateIn, _resolve_ids,
    _generic_bulk_delete, _generic_bulk_update, _CAP,
)

router = APIRouter()


# ──── Reviews ──────────────────────────────────────────────────────────
_REVIEW_SELECTOR = {"search", "status", "is_public"}
_REVIEW_PATCH_ALLOWED = {"is_public", "admin_response", "status"}


async def _review_locked(row: dict) -> Optional[str]:
    """Reviews already clicked through to Google can be edited but
    not hard-deleted (they anchor real Google Reviews)."""
    if row.get("google_click_at"):
        return "Review already clicked through to Google — archive instead"
    return None


@router.post("/reviews/bulk-delete", operation_id="reviews.bulkDelete")
async def reviews_bulk_delete(body: _BulkIdsIn,
                                  user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("customer_portal_reviews", tenant["id"],
                                    body.query_selector or {},
                                    body.exclude_ids or [], _REVIEW_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_delete("customer_portal_reviews",
                                          "review.soft_delete", ids, user,
                                          tenant, _review_locked)


@router.post("/reviews/bulk-update", operation_id="reviews.bulkUpdate")
async def reviews_bulk_update(body: _BulkUpdateIn,
                                  user: dict = Depends(require_admin),
                                  tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("customer_portal_reviews", tenant["id"],
                                    body.query_selector or {},
                                    body.exclude_ids or [], _REVIEW_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_update("customer_portal_reviews",
                                          "review.bulk_update", ids,
                                          body.patch, _REVIEW_PATCH_ALLOWED,
                                          user, tenant)


# ──── Team / Users ─────────────────────────────────────────────────────
_USER_SELECTOR = {"search", "role", "is_active"}
_USER_PATCH_ALLOWED = {"role", "is_active", "assigned_regions"}


async def _user_locked_for_delete(row: dict, actor_id: str,
                                          tenant_id: str) -> Optional[str]:
    """Never bulk-delete: (a) the acting user themselves, (b) the last
    remaining owner-role user in the tenant."""
    if row.get("id") == actor_id:
        return "Cannot delete your own active session's user"
    if (row.get("role") or "").lower() == "owner":
        n_owners = await db.users.count_documents({
            "tenant_id": tenant_id, "role": "owner",
            "$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}],
        })
        if n_owners <= 1:
            return "Cannot delete the last owner in this tenant"
    return None


@router.post("/users/bulk-delete", operation_id="users.bulkDelete")
async def users_bulk_delete(body: _BulkIdsIn,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("users", tenant["id"], body.query_selector or {},
                                    body.exclude_ids or [], _USER_SELECTOR)
              if body.query_selector else list(body.ids or []))
    # Custom locked_check bound to actor + tenant.
    actor_id = user.get("id")
    tid = tenant["id"]
    async def _locked(row):
        return await _user_locked_for_delete(row, actor_id, tid)
    return await _generic_bulk_delete("users", "user.soft_delete", ids,
                                          user, tenant, _locked)


@router.post("/users/bulk-update", operation_id="users.bulkUpdate")
async def users_bulk_update(body: _BulkUpdateIn,
                                 user: dict = Depends(require_admin),
                                 tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("users", tenant["id"], body.query_selector or {},
                                    body.exclude_ids or [], _USER_SELECTOR)
              if body.query_selector else list(body.ids or []))
    # Never allow bulk-editing your own row (prevents lockouts).
    if user.get("id") in ids:
        raise HTTPException(400, "Cannot bulk-edit your own user row")
    return await _generic_bulk_update("users", "user.bulk_update", ids,
                                          body.patch, _USER_PATCH_ALLOWED,
                                          user, tenant)


# ──── Customer Tags ────────────────────────────────────────────────────
_TAG_SELECTOR = {"search", "parent_tag_id", "is_archived"}
_TAG_PATCH_ALLOWED = {"color", "parent_tag_id", "is_archived"}


@router.post("/customer-tags/bulk-delete",
              operation_id="customerTags.bulkDelete")
async def tags_bulk_delete(body: _BulkIdsIn,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("customer_tags", tenant["id"],
                                    body.query_selector or {},
                                    body.exclude_ids or [], _TAG_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_delete("customer_tags",
                                          "customer_tag.soft_delete",
                                          ids, user, tenant)


@router.post("/customer-tags/bulk-update",
              operation_id="customerTags.bulkUpdate")
async def tags_bulk_update(body: _BulkUpdateIn,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("customer_tags", tenant["id"],
                                    body.query_selector or {},
                                    body.exclude_ids or [], _TAG_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_update("customer_tags",
                                          "customer_tag.bulk_update",
                                          ids, body.patch,
                                          _TAG_PATCH_ALLOWED, user, tenant)


# ──── Service Reports ──────────────────────────────────────────────────
_SR_SELECTOR = {"search", "is_customer_visible", "job_id"}
_SR_PATCH_ALLOWED = {"is_customer_visible", "tags"}


async def _service_report_locked(row: dict) -> Optional[str]:
    """Service reports referenced by an invoice as evidence stay put
    (auditors need immutable evidence). Archive is fine, hard delete
    is not."""
    if row.get("evidence_invoice_id"):
        return "Report is invoice evidence — archive instead of deleting"
    return None


@router.post("/service-reports/bulk-delete",
              operation_id="serviceReports.bulkDelete")
async def service_reports_bulk_delete(body: _BulkIdsIn,
                                            user: dict = Depends(require_admin),
                                            tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("service_reports", tenant["id"],
                                    body.query_selector or {},
                                    body.exclude_ids or [], _SR_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_delete("service_reports",
                                          "service_report.soft_delete",
                                          ids, user, tenant,
                                          _service_report_locked)


@router.post("/service-reports/bulk-update",
              operation_id="serviceReports.bulkUpdate")
async def service_reports_bulk_update(body: _BulkUpdateIn,
                                            user: dict = Depends(require_admin),
                                            tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("service_reports", tenant["id"],
                                    body.query_selector or {},
                                    body.exclude_ids or [], _SR_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_update("service_reports",
                                          "service_report.bulk_update",
                                          ids, body.patch,
                                          _SR_PATCH_ALLOWED, user, tenant)


# ──── Time Entries ─────────────────────────────────────────────────────
_TE_SELECTOR = {"search", "is_approved", "assigned_job_id", "user_id"}
_TE_PATCH_ALLOWED = {"is_approved", "assigned_job_id", "hourly_rate_override"}


async def _time_entry_locked(row: dict) -> Optional[str]:
    """Time entries already included in a paid payroll cannot be
    hard-deleted (payroll audit trail)."""
    if row.get("payroll_run_id") and row.get("payroll_paid_at"):
        return "Time entry is on a paid payroll run — archive instead"
    return None


@router.get("/time-entries", operation_id="timeEntries.list")
async def list_time_entries(
    is_approved: Optional[bool] = Query(None),
    user_id: Optional[str] = Query(None),
    assigned_job_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(500, ge=1, le=2000),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Task NN follow-up · Feb 2026 — canonical admin list endpoint
    aligned with the bulk-delete + bulk-update namespace on
    ``/time-entries``. Tenant-scoped, admin-gated. Soft-delete filter
    on by default; super_admin can opt-in via ``?include_deleted=1``.

    NOTE: this is intentionally simpler than ``/workforce/timesheets``
    (no overtime computation, no daily grouping) — that endpoint
    remains the source of truth for payroll UX. This one exists so
    the admin bulk list can operate on the same collection the bulk
    endpoints target with Task-EE `{query_selector}` parity.
    """
    q: dict = {"tenant_id": tenant["id"]}
    if not include_deleted or user.get("role") != "super_admin":
        q["$or"] = [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]
    if is_approved is not None:
        q["is_approved"] = is_approved
    if user_id:
        q["user_id"] = user_id
    if assigned_job_id:
        q["assigned_job_id"] = assigned_job_id
    if search:
        q["$and"] = q.get("$and", []) + [{"$or": [
            {"user_name": {"$regex": search, "$options": "i"}},
            {"assigned_job_id": {"$regex": search, "$options": "i"}},
        ]}]
    rows = await db.time_entries.find(
        q, {"_id": 0},
    ).sort("date", -1).to_list(length=limit)
    return rows


@router.post("/time-entries/bulk-delete",
              operation_id="timeEntries.bulkDelete")
async def time_entries_bulk_delete(body: _BulkIdsIn,
                                          user: dict = Depends(require_admin),
                                          tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("time_entries", tenant["id"],
                                    body.query_selector or {},
                                    body.exclude_ids or [], _TE_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_delete("time_entries",
                                          "time_entry.soft_delete",
                                          ids, user, tenant,
                                          _time_entry_locked)


@router.post("/time-entries/bulk-update",
              operation_id="timeEntries.bulkUpdate")
async def time_entries_bulk_update(body: _BulkUpdateIn,
                                          user: dict = Depends(require_admin),
                                          tenant: dict = Depends(get_current_tenant)):
    ids = (await _resolve_ids("time_entries", tenant["id"],
                                    body.query_selector or {},
                                    body.exclude_ids or [], _TE_SELECTOR)
              if body.query_selector else list(body.ids or []))
    return await _generic_bulk_update("time_entries",
                                          "time_entry.bulk_update",
                                          ids, body.patch,
                                          _TE_PATCH_ALLOWED, user, tenant)
