"""Phase L2 · Feb-2026 — Historical lead backfill endpoint.

Super-Admin-only trigger for
``services.migrations.leads_backfill_label_resolution_v1``.

Mirrors the pattern of ``routers/admin_customer_geocode_backfill.py``
— synchronous execution with per-lead audit logging.  On tenants
whose lead-with-submission-id count exceeds 500 we still run inline
(the loop is I/O-bound Mongo + no external calls) — mirror the
customer-geocode endpoint's inline mode, and if throughput ever
needs to grow, add a background-task variant then.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from config import db
from services.migrations.leads_backfill_label_resolution_v1 import (
    backfill_leads_label_resolution,
)
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter(prefix="/api", tags=["admin"])


@router.post("/admin/leads/backfill-label-resolution")
async def leads_backfill_label_resolution(
    dry_run: bool = False,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Super-Admin only.  Re-runs the L2 label-aware extractor
    against every lead that carries a linked ``form_submissions``
    row and $sets the newly-resolved canonical fields IF the
    lead's current value is empty.

    Query param ``dry_run=true`` returns the summary without
    writing to Mongo — safe to pre-flight on a new tenant.
    """
    role = (user or {}).get("role") or ""
    if role != "super_admin":
        raise HTTPException(403, "Super Admin access required")
    return await backfill_leads_label_resolution(
        db, tenant_id=tenant["id"], actor=user, dry_run=dry_run,
    )
