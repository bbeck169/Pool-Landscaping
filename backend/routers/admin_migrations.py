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

from fastapi import APIRouter, Depends, HTTPException, Query

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
