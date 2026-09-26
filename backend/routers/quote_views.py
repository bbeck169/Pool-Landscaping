"""QV-service · Feb-2026 — Admin quote-view history endpoint.

Serves the aggregated view history for a single quote. Reads
straight from the ``quote_views`` collection (feed) plus the
denormalised aggregates on the quote document (
``first_viewed_at``, ``last_viewed_at``, ``view_count``) so a
single roundtrip fully hydrates the admin "View History" card and
the quotes-list "Viewed Nd ago" indicator.

Path: ``GET /api/quotes/{qid}/views``

RBAC:
    admin / super_admin / manager → full read
    dispatcher / office           → full read
    technician                    → 403 (billing surface)
    customer                      → 403 (internal engagement
                                            signal, not a
                                            customer-facing view)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from utils import get_current_user
from routers.tenants import get_current_tenant
from services.quote_view_tracker import fetch_quote_views_summary

router = APIRouter()


@router.get("/quotes/{qid}/views")
async def get_quote_views(qid: str,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    role = (user.get("role") or "").lower()
    if role in ("technician", "customer"):
        raise HTTPException(403, "Not allowed")

    return await fetch_quote_views_summary(
        quote_id=qid, tenant_id=tenant["id"], limit=100,
    )
