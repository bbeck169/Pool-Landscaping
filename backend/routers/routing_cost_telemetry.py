"""Feb-2026 · UX Polish Batch B — Routing cost telemetry endpoint.

Reads the in-memory ring buffer maintained by
:mod:`services.routing.telemetry` and returns a per-tenant rolling
aggregation. Admin-only. Zero writes, zero external IO.

See /app/memory/FEATURE_SEND_TO_CUSTOMER_AND_COST_TELEMETRY.md § 2.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from utils import require_admin
from routers.tenants import get_current_tenant
from services.routing.telemetry import summarize


router = APIRouter()


@router.get("/reports/routing-cost-telemetry")
async def get_routing_cost_telemetry(
    window_days: int = Query(30, ge=1, le=365),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Aggregated routing telemetry for the caller's tenant.

    ``window_days`` is clamped to ``[1, 365]``; default is 30 to
    match the dashboard tile's default window.
    """
    if not tenant.get("id"):
        raise HTTPException(400, "Tenant context is required.")
    return summarize(tenant["id"], window_days=window_days)
