"""Phase K47 · Feb-2026 — Admin invoice-view history endpoint.

Serves the aggregated view history for a single invoice. Reads
straight from the ``invoice_views`` collection (feed) plus the
denormalised aggregates on the invoice document (
``first_viewed_at``, ``last_viewed_at``, ``view_count``) so a
single roundtrip fully hydrates the admin "View History" card and
the invoices-list "Viewed Nd ago" indicator.

Path: ``GET /api/invoices/{iid}/views``

RBAC:
    admin / office / dispatcher → full read
    technician → 403 (billing surface)
    customer   → 403 (customers can't see their own view log by
                        design — this is an internal collections
                        signal, not customer-facing)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from utils import get_current_user
from routers.tenants import get_current_tenant
from services.invoice_view_tracker import fetch_invoice_views_summary

router = APIRouter()


@router.get("/invoices/{iid}/views")
async def get_invoice_views(iid: str,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    role = (user.get("role") or "").lower()
    if role in ("technician", "customer"):
        raise HTTPException(403, "Not allowed")

    return await fetch_invoice_views_summary(
        invoice_id=iid, tenant_id=tenant["id"], limit=100,
    )
