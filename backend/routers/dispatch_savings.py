"""Phase 10 · Feb-2026 — Sub-item F: Dispatch weekly savings KPI router.

`GET /api/dispatch/route/savings/weekly` returns aggregated savings from
the `route_optimize_events` append-only log written by Phase 3
`/dispatch/route/apply` and Phase 4 `/dispatch/route/insert`.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from services.route_events import weekly_summary
from utils import get_current_user


router = APIRouter()


@router.get("/dispatch/route/savings/weekly",
             operation_id="dispatchRoute.savingsWeekly",
             tags=["dispatch-route"])
async def api_savings_weekly(range: str = "7d",
                                caller: Dict[str, Any] = Depends(get_current_user)):
    tenant_id = caller.get("tenant_id") or ""
    r = await weekly_summary(tenant_id=tenant_id,
                                range_=range if range in ("7d", "30d") else "7d")
    return r
