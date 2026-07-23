"""Phase 12B · Feb 2026 — Admin endpoints for the Stripe ↔ Customers
cross-reference sync.

Three endpoints, all admin-only:

  * ``POST /api/admin/stripe-customer-sync/preview`` — dry-run.
  * ``POST /api/admin/stripe-customer-sync/run``     — real run.
  * ``POST /api/admin/stripe-customer-sync/link``    — resolve one
        ambiguous email-match by picking a specific
        ``stripe_customer_id``.

All three route through the same
:func:`services.stripe_customer_sync.run_stripe_customer_sync` /
:func:`link_customer_to_stripe` helpers so the semantics stay
identical whether triggered manually or on a future schedule.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from services.stripe_customer_sync import (
    run_stripe_customer_sync, link_customer_to_stripe,
)
from routers.tenants import get_current_tenant
from utils import get_current_user

router = APIRouter()


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class _LinkBody(BaseModel):
    customer_id: str = Field(..., min_length=1)
    stripe_customer_id: str = Field(..., min_length=1)


@router.post("/admin/stripe-customer-sync/preview")
async def stripe_customer_sync_preview(
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Dry-run sync — never writes. Returns what a real run WOULD do.
    Includes any ambiguous email matches so admins can resolve them
    via the ``/link`` endpoint before executing the real run."""
    return await run_stripe_customer_sync(tenant["id"], dry_run=True)


@router.post("/admin/stripe-customer-sync/run")
async def stripe_customer_sync_run(
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Real sync — writes to the customers collection. Idempotent —
    calling this on already-synced state is a full no-op (report
    fields will show ``linked=[] updated_card_flag=[] no_op=<count>``)."""
    return await run_stripe_customer_sync(tenant["id"], dry_run=False)


@router.post("/admin/stripe-customer-sync/link")
async def stripe_customer_sync_link(
    body: _LinkBody,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Manually resolve one ambiguous match. Verifies email match
    against Stripe before persisting."""
    return await link_customer_to_stripe(
        tenant_id=tenant["id"],
        customer_id=body.customer_id,
        stripe_customer_id=body.stripe_customer_id,
    )
