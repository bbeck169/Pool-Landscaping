"""
Feb-2026 · Diag-Timeout Task 1 — admin maintenance endpoints.

Currently exposes:

  * ``POST /api/admin/maintenance/rebuild-customers-haystack``
      super_admin only, rate-limited to 1 rebuild / hour / tenant.
      Runs :func:`services.customers_search_haystack
      .backfill_tenant_haystack` for the caller's tenant.  Emits
      ``started`` / progress / ``completed`` log lines tagged with
      ``tenant_id`` (progress lives inside the service module).

Separated from ``routers/maintenance.py`` (chemical maintenance
domain) so its ``/api/admin/maintenance/*`` URL space is not
overloaded and RBAC / rate-limit posture is obvious at a glance.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException

from config import db
from utils import get_current_user
from routers.tenants import get_current_tenant

logger = logging.getLogger("routers.admin_maintenance")
router = APIRouter(tags=["admin-maintenance"])


_RATE_LIMIT_WINDOW_SECONDS = 60 * 60  # 1 hour per tenant


def _require_super_admin(user: dict) -> None:
    role = (user or {}).get("role")
    if role != "super_admin":
        raise HTTPException(403, "super_admin only")


async def _tenant_rate_limited(tenant_id: str) -> tuple[bool, str | None]:
    """Return ``(is_limited, retry_after_iso)``. Uses the same
    ``system_meta`` collection the version marker lives in so we
    don't add another Mongo collection just for a per-tenant clock."""
    key = f"customers_haystack_rebuild_last_run:{tenant_id}"
    row = await db.system_meta.find_one({"key": key})
    if not row:
        return False, None
    last_iso = row.get("last_run_at") or ""
    try:
        last = datetime.fromisoformat(last_iso.replace("Z", "+00:00"))
    except Exception:
        return False, None
    delta = datetime.now(tz=timezone.utc) - last
    if delta.total_seconds() < _RATE_LIMIT_WINDOW_SECONDS:
        retry = last + timedelta(seconds=_RATE_LIMIT_WINDOW_SECONDS)
        return True, retry.isoformat()
    return False, None


async def _stamp_tenant_rebuild(tenant_id: str, summary: dict) -> None:
    await db.system_meta.update_one(
        {"key": f"customers_haystack_rebuild_last_run:{tenant_id}"},
        {"$set": {
            "key": f"customers_haystack_rebuild_last_run:{tenant_id}",
            "tenant_id": tenant_id,
            "last_run_at": datetime.now(tz=timezone.utc).isoformat(),
            "scanned": int(summary.get("scanned", 0)),
            "updated": int(summary.get("updated", 0)),
            "duration_seconds": summary.get("duration_seconds", 0.0),
        }},
        upsert=True,
    )


@router.post("/admin/maintenance/rebuild-customers-haystack")
async def rebuild_customers_haystack(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Rebuild the ``search_haystack`` field on every customer doc
    in the caller's tenant. Idempotent — safe to re-run.

    * ``super_admin`` role required.
    * Rate-limited to 1 rebuild per hour per tenant. Subsequent
      calls within the window return 429 with ``retry_after``.
    """
    _require_super_admin(user)
    tenant_id = tenant.get("id") or ""
    if not tenant_id:
        raise HTTPException(400, "tenant not resolved")

    limited, retry_after = await _tenant_rate_limited(tenant_id)
    if limited:
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "rate_limited",
                "message": (
                    "customers-haystack rebuild is rate-limited to 1 per hour "
                    "per tenant"
                ),
                "retry_after": retry_after,
            },
        )

    from services.customers_search_haystack import backfill_tenant_haystack
    logger.info(
        "[admin_maintenance] rebuild-customers-haystack invoked "
        "actor=%s tenant=%s",
        user.get("id"), tenant_id,
    )
    summary = await backfill_tenant_haystack(db, tenant_id,
                                                full_rebuild=True)
    await _stamp_tenant_rebuild(tenant_id, summary)
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "scanned": summary["scanned"],
        "updated": summary["updated"],
        "duration_seconds": summary["duration_seconds"],
    }
