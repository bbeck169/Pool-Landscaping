"""Feb-2026 · Admin migrations API — one-off backfill wrappers
super_admins can trigger from the deployed app without needing pod
shell access.

Currently exposes:
  * ``POST /admin/migrations/backfill-website-visitor-leads``
    — wraps ``migrations.task_p19_backfill_empty_website_visitor_leads
    .run_backfill_for_tenant`` behind the super_admin gate. Dry-run
    default; the caller MUST explicitly pass ``dry_run=false`` to
    write. Idempotent — safe to call twice.

Contract notes:
  * Tenant scoping strict. Default target = caller's own tenant.
  * When the caller passes ``tenant_slug`` different from their own,
    the endpoint logs a WARN before proceeding (cross-tenant admin
    action). Only super_admins can do this — the role gate already
    covers non-super callers.
  * The endpoint NEVER auto-runs on deploy — must be explicitly
    triggered.  There is no CRON, no lifespan hook.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user
from routers.tenants import get_current_tenant

from migrations.task_p19_backfill_empty_website_visitor_leads import (
    run_backfill_for_tenant,
)


logger = logging.getLogger("admin_migrations")

router = APIRouter()


def _require_super_admin(user: Dict[str, Any]) -> None:
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")


async def _resolve_target_tenant(
    caller_tenant: Dict[str, Any],
    tenant_slug: Optional[str],
) -> Dict[str, Any]:
    """Return the tenant doc to run the migration against.

    Default = caller's own tenant.  Super_admin may pass ``tenant_slug``
    to target a different tenant; if the slug doesn't resolve, raise
    404 rather than silently falling back — cross-tenant admin
    actions must never accidentally hit the wrong org.
    """
    if not tenant_slug:
        return caller_tenant
    target = await db.tenants.find_one(
        {"slug": tenant_slug}, {"_id": 0, "id": 1, "slug": 1, "name": 1},
    )
    if not target:
        raise HTTPException(404, f"tenant_not_found:{tenant_slug}")
    return target


# ─────────────────────────────────────────────────────────────────────
# POST /admin/migrations/backfill-website-visitor-leads
# ─────────────────────────────────────────────────────────────────────
@router.post(
    "/admin/migrations/backfill-website-visitor-leads",
    operation_id="admin.migrations.backfill_website_visitor_leads",
)
async def backfill_website_visitor_leads(
    dry_run: bool = Query(
        True,
        description=(
            "Safety-first default. Set to false to actually write "
            "the enrichments. Idempotent either way."
        ),
    ),
    tenant_slug: Optional[str] = Query(
        None,
        description=(
            "Target tenant slug. Defaults to the caller's own tenant. "
            "Only super_admins can target a different tenant, and every "
            "cross-tenant invocation is logged at WARN."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    _require_super_admin(user)
    target = await _resolve_target_tenant(tenant, tenant_slug)
    is_cross = target["id"] != tenant["id"]

    log_line = (
        f"[p19-api] user={user.get('id')} email={user.get('email')} "
        f"caller_tenant={tenant['id']} target_tenant={target['id']} "
        f"target_slug={target.get('slug')} dry_run={dry_run} "
        f"cross_tenant={is_cross}"
    )
    if is_cross:
        logger.warning("CROSS-TENANT admin migration invocation · " + log_line)
    else:
        logger.info(log_line)

    report = await run_backfill_for_tenant(
        tenant_id=target["id"], dry_run=dry_run,
    )
    # Wrap the migration's per-tenant report with the tenant envelope
    # the frontend renders on the diff table.
    return {
        "tenant_id": target["id"],
        "tenant_slug": target.get("slug"),
        "tenant_name": target.get("name"),
        "dry_run": report["dry_run"],
        "matched_leads": report["matched_leads"],
        "enriched_leads": report["enriched_leads"],
        "skipped_no_match": report["skipped_no_match"],
        "skipped_no_new_data": report["skipped_no_new_data"],
        "enrichments": report["enrichments"],
        "warnings": report["warnings"],
    }



# ─────────────────────────────────────────────────────────────────────
# Roster Cleanup — list tech-adjacent users + soft-deactivate flow.
# ─────────────────────────────────────────────────────────────────────
# Roles the roster surface exposes for management. Matches the
# ``ASSIGNABLE_ROLES`` set in ``routers/technicians.py`` — that's the
# universe of users the tech-filter dropdowns pull from, so this is
# where duplicate / seed / stale accounts need to be surfaced first.
_TECH_ADJACENT_ROLES = [
    "technician", "tech", "landscaper",
    "landscape_tech", "pool_tech", "tech_both",
]


@router.get(
    "/admin/migrations/roster",
    operation_id="admin.migrations.roster_list",
)
async def list_roster_for_cleanup(
    include_inactive: bool = Query(
        True,
        description=(
            "Include ``active=false`` users so super_admins can "
            "re-activate a wrongly-deactivated user or view the "
            "full history."
        ),
    ),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Tenant-scoped roster of tech-adjacent users, each row
    annotated with a live ``active_jobs`` count so super_admins can
    see who's safe to deactivate.

    Returns ``[{ id, email, name, role, active, created_at,
    active_jobs, is_deactivated }]``.
    """
    _require_super_admin(user)
    tid = tenant["id"]
    q: Dict[str, Any] = {
        "tenant_id": tid,
        "role": {"$in": _TECH_ADJACENT_ROLES},
        "$and": [
            {"$or": [{"deleted_at": None},
                       {"deleted_at": {"$exists": False}}]},
        ],
    }
    if not include_inactive:
        q["$and"].append(
            {"$or": [{"active": {"$ne": False}},
                       {"active": {"$exists": False}}]},
        )

    users = await db.users.find(
        q,
        {"_id": 0, "id": 1, "email": 1, "first_name": 1,
         "last_name": 1, "name": 1, "role": 1, "active": 1,
         "created_at": 1, "department": 1},
    ).sort("created_at", -1).to_list(1000)

    rows: list = []
    for u in users:
        active_flag = u.get("active")
        rows.append({
            "id": u.get("id"),
            "email": u.get("email"),
            "name": (u.get("name")
                      or " ".join([u.get("first_name") or "",
                                    u.get("last_name") or ""]).strip()
                      or u.get("email") or "Unnamed"),
            "role": u.get("role"),
            "department": u.get("department"),
            "created_at": u.get("created_at"),
            "active": True if active_flag is None else bool(active_flag),
            "is_deactivated": active_flag is False,
            # Active jobs count — used by the UI to disable the row's
            # checkbox when non-zero (deactivate would strand work).
            "active_jobs": await db.jobs.count_documents({
                "tenant_id": tid,
                "$or": [
                    {"technician_id": u.get("id")},
                    {"assigned_to": u.get("id")},
                    {"assigned_technician_id": u.get("id")},
                    {"tech_user_id": u.get("id")},
                ],
                "status": {"$in": ["scheduled", "pending", "active",
                                     "in_progress"]},
            }),
        })
    return rows


class _DeactivateBody(BaseModel):
    user_ids: list[str] = Field(default_factory=list)
    dry_run: bool = True


@router.post(
    "/admin/migrations/deactivate-users",
    operation_id="admin.migrations.deactivate_users",
)
async def deactivate_users(
    body: _DeactivateBody = Body(default=_DeactivateBody()),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    """Soft-deactivate a batch of tech-adjacent users.

    Contract:
      * super_admin only.
      * Tenant-scoped — the endpoint refuses to touch any user whose
        ``tenant_id`` doesn't match the caller's.
      * SOFT deactivation — writes ``active=false``. Does NOT
        hard-delete. History (jobs, invoices, service reports) is
        preserved and continues to render the (now-inactive) tech's
        name via the read-time cascade in
        ``services/tech_assignment.py``.
      * Refuses to deactivate users with ANY active job on the
        4-shape ``effective_tid`` union — returns them in
        ``skipped[]`` with reason ``"has_active_jobs"``. Caller
        must reassign first.
      * ``dry_run=true`` (default) reports what WOULD happen without
        writing.
      * Idempotent: deactivating an already-inactive user is a
        no-op (returned in ``skipped[]`` with reason ``"already_inactive"``).

    Response:
      ``{ dry_run, tenant_id, deactivated_count, skipped_count,
          deactivated: [user_id], skipped: [{user_id, reason}],
          errors: [] }``
    """
    _require_super_admin(user)
    tid = tenant["id"]
    dry = body.dry_run
    deactivated: list = []
    skipped: list = []
    errors: list = []

    logger.info(
        f"[roster-cleanup-api] user={user.get('id')} "
        f"email={user.get('email')} tenant={tid} "
        f"dry_run={dry} target_count={len(body.user_ids)}"
    )

    for uid in (body.user_ids or []):
        target = await db.users.find_one(
            {"id": uid, "tenant_id": tid},
            {"_id": 0, "id": 1, "role": 1, "active": 1},
        )
        if not target:
            # Wrong tenant OR user doesn't exist — collapse both into
            # ``not_found`` so we never leak whether a user exists in
            # a different tenant.
            skipped.append({"user_id": uid, "reason": "not_found"})
            continue
        if target.get("role") not in _TECH_ADJACENT_ROLES:
            skipped.append({"user_id": uid, "reason": "not_tech_adjacent"})
            continue
        if target.get("active") is False:
            skipped.append({"user_id": uid, "reason": "already_inactive"})
            continue
        # Active-jobs guard — same 4-shape union the tech filter uses.
        active_jobs = await db.jobs.count_documents({
            "tenant_id": tid,
            "$or": [
                {"technician_id": uid},
                {"assigned_to": uid},
                {"assigned_technician_id": uid},
                {"tech_user_id": uid},
            ],
            "status": {"$in": ["scheduled", "pending", "active",
                                 "in_progress"]},
        })
        if active_jobs > 0:
            skipped.append({
                "user_id": uid,
                "reason": "has_active_jobs",
                "active_jobs": active_jobs,
            })
            continue
        if not dry:
            try:
                await db.users.update_one(
                    {"id": uid, "tenant_id": tid},
                    {"$set": {
                        "active": False,
                        "deactivated_at": _now_iso(),
                        "deactivated_by": user.get("id"),
                    }},
                )
            except Exception as exc:                              # noqa: BLE001
                errors.append({"user_id": uid, "error": str(exc)})
                continue
        deactivated.append(uid)

    return {
        "dry_run": dry,
        "tenant_id": tid,
        "deactivated_count": len(deactivated),
        "skipped_count": len(skipped),
        "deactivated": deactivated,
        "skipped": skipped,
        "errors": errors,
    }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
