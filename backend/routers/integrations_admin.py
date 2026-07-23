"""Feb-2026 · Integrations owner audit + on-demand transfer.

Read-side visibility endpoint for the tenant's 3rd-party integrations
owner mapping. Super_admin only — the answer identifies which admin
account owns each integration credential set (Stripe/RingCentral/
Resend/etc). Actual credentials never leave the DB via this route.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from utils import get_current_user
from routers.tenants import get_current_tenant

router = APIRouter(tags=["Integrations"])


@router.get("/admin/integrations/owner-report",
             operation_id="integrations.ownerReport")
async def owner_report(
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
):
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super-admin only")
    from migrations.transfer_integrations_to_brian import _owner_report_for_tenant
    rows = await _owner_report_for_tenant(tenant["id"])
    return {"tenant_id": tenant["id"], "integrations": rows,
             "total": len(rows)}


@router.post("/admin/integrations/transfer-to-brian",
              operation_id="integrations.transferToBrian")
async def transfer_to_brian(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Re-run the migration on demand. Idempotent — second calls are
    no-ops. Only super_admin can trigger."""
    if user.get("role") != "super_admin":
        raise HTTPException(403, "Super-admin only")
    from migrations.transfer_integrations_to_brian import run
    result = await run()
    return result
