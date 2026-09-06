"""Phase R0 · Feb-2026 — Reporting suite router.

Exposes ONE endpoint end-to-end so R1–R7 phases can drop new
metrics into ``services.reporting.metrics`` without ever
touching this file again:

    GET /api/reports/kpi/{metric_key}
        ?period=mtd|qtd|ytd|last_30d|custom
        &start=YYYY-MM-DD
        &end=YYYY-MM-DD

Response body::

    {
        "key": "revenue_total",
        "label": "Total Revenue",
        "format": "currency",
        "direction": "up_is_good",
        "period": { "key": "mtd", "label": "...", "start": ..., "end": ..., ...},
        "value": 12345.67,
        "prior_value": 9876.54,
        "delta_pct": 25.0,
        "sparkline": [{"t": "2026-02-01", "v": 1200}, ...],
        "cached": false
    }

RBAC:
    * ``super_admin`` / ``admin`` / ``owner`` / ``manager`` may read.
    * Technicians + customers 403.

Cache:
    * Compound key = ``tenant_id | metric_key | period.key | start | end``.
    * 60-second TTL (in-memory).  Cache hits set ``cached=true`` on
      the response so the FE can annotate its debug overlay.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user
from services.reporting import (
    AggregationEngine,
    Metric,
    REGISTRY,
    get_metric,
    report_cache,
    resolve_period,
)


router = APIRouter()


_READER_ROLES = ("super_admin", "admin", "owner", "manager")


def require_report_reader(user: dict = Depends(get_current_user)) -> dict:
    """Allow reporting reads for admin/owner/manager tiers; deny
    technicians + customers. Deliberately widened past
    ``require_admin`` because ``owner`` and ``manager`` need
    the KPI wall too."""
    role = (user or {}).get("role") or ""
    if role not in _READER_ROLES:
        raise HTTPException(403, "Reporting is restricted to admin roles")
    return user


@router.get("/reports/kpi/{metric_key}")
async def kpi(
    metric_key: str,
    period: Optional[str] = Query("mtd"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    # R0.1 · grouped-metric filters (ignored by scalar metrics).
    lens: Optional[str] = Query("invoiced"),
    service_type: Optional[str] = Query(None),
    tech_id: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=1000),
    offset: Optional[int] = Query(0, ge=0),
    user: dict = Depends(require_report_reader),
    tenant: dict = Depends(get_current_tenant),
):
    metric: Metric = get_metric(metric_key)   # 404 for unknown key
    p = resolve_period(period, start, end)
    tenant_id = tenant["id"]

    if metric.is_grouped:
        # Normalized filter set — becomes part of the cache key so
        # a lens flip / filter change misses the cache correctly.
        if lens not in ("invoiced", "collected"):
            raise HTTPException(400, "lens must be 'invoiced' or 'collected'")
        filters = {
            "lens": lens,
            "service_type": (service_type or "").strip() or None,
            "tech_id": (tech_id or "").strip() or None,
            "limit": limit,
            "offset": offset or 0,
        }
        cache_key = report_cache.make_key(
            tenant_id, "kpi", metric.key, p.key, p.start, p.end,
            filters["lens"], filters.get("service_type") or "-",
            filters.get("tech_id") or "-",
            str(filters.get("limit") or "-"),
            str(filters.get("offset") or 0),
        )
        hit = report_cache.get(cache_key)
        if hit is not None:
            return {**hit, "cached": True}
        engine = AggregationEngine(db, tenant_id)
        try:
            grouped = await metric.compute_grouped(engine, p, filters)
        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("[reports] grouped metric %s failed: %s", metric.key, exc)
            raise HTTPException(500, f"metric compute failed: {metric.key}") from exc
        payload = {
            "key": metric.key,
            "label": metric.label,
            "format": metric.format,
            "direction": metric.direction,
            "description": metric.description,
            "is_grouped": True,
            "period": p.as_dict(),
            "lens": filters["lens"],
            "filters_applied": {
                "service_type": filters.get("service_type"),
                "tech_id": filters.get("tech_id"),
                "limit": filters.get("limit"),
                "offset": filters.get("offset") or 0,
            },
            "total": float(grouped.get("total") or 0.0),
            "row_count": int(grouped.get("row_count") or len(grouped.get("rows") or [])),
            "rows": grouped.get("rows") or [],
        }
        report_cache.set(cache_key, payload)
        return {**payload, "cached": False}

    cache_key = report_cache.make_key(
        tenant_id, "kpi", metric.key, p.key, p.start, p.end,
    )
    hit = report_cache.get(cache_key)
    if hit is not None:
        return {**hit, "cached": True}

    engine = AggregationEngine(db, tenant_id)
    try:
        raw = await metric.compute(engine, p)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("[reports] metric %s failed: %s", metric.key, exc)
        raise HTTPException(500, f"metric compute failed: {metric.key}") from exc

    payload = {
        "key": metric.key,
        "label": metric.label,
        "format": metric.format,
        "direction": metric.direction,
        "description": metric.description,
        "is_grouped": False,
        "period": p.as_dict(),
        "value": float(raw.get("value") or 0.0),
        "prior_value": float(raw.get("prior_value") or 0.0),
        "delta_pct": raw.get("delta_pct"),
        "sparkline": raw.get("sparkline") or [],
    }
    report_cache.set(cache_key, payload)
    return {**payload, "cached": False}


@router.get("/reports/kpi")
async def kpi_registry_list(user: dict = Depends(require_report_reader)):
    """List of registered metric definitions — used by the FE to
    render the KPI grid without hard-coding metric metadata.
    R1+ metrics will surface here automatically on registration."""
    return {"metrics": [m.to_public() for m in REGISTRY.values()]}
