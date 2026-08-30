"""Phase B4 · Feb-2026 — Subscription CRUD router.

Endpoints (all prefixed by ``/api`` via the main api_router):

    GET     /api/subscriptions/prices          — active Stripe prices
    GET     /api/subscriptions                 — list per-customer / per-tenant
    POST    /api/subscriptions                 — create (owner + admin + super)
    PATCH   /api/subscriptions/{stripe_sub_id} — update (owner + admin + super)
    DELETE  /api/subscriptions/{stripe_sub_id} — cancel  (owner + admin + super)

Role gate rationale: "owner" is the tenant owner (distinct role in
this codebase), "admin" is the operational tenant admin (matches
the existing gate pattern in ``stripe_router._ADMIN_ROLES``),
"super_admin" is the platform-level operator. Technicians and
customers are 403'd on every write endpoint — the spec explicitly
excludes them.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from utils import get_current_user
from services.payments import stripe_subscription as sub_svc


router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])
logger = logging.getLogger("subscriptions_router")


_WRITE_ROLES = ("owner", "admin", "super_admin")


def _require_write_role(user: Dict[str, Any]) -> None:
    role = (user or {}).get("role") or ""
    if role not in _WRITE_ROLES:
        raise HTTPException(403, "subscription_write_forbidden")


def _tenant_id(user: Dict[str, Any]) -> str:
    tid = (user or {}).get("tenant_id")
    if not tid:
        raise HTTPException(401, "tenant_missing")
    return tid


# ── Pydantic bodies ─────────────────────────────────────────────
class CreateSubBody(BaseModel):
    customer_id: str
    price_id: str
    quantity: int = Field(1, ge=1, le=1000)
    payment_method_id: Optional[str] = None
    trial_days: int = Field(0, ge=0, le=365)
    metadata: Optional[Dict[str, Any]] = None
    cancel_at_period_end: bool = False


class UpdateSubBody(BaseModel):
    price_id: Optional[str] = None
    quantity: Optional[int] = Field(None, ge=1, le=1000)
    cancel_at_period_end: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None


# ── Routes ──────────────────────────────────────────────────────
@router.get("/prices")
async def get_prices(user: Dict[str, Any] = Depends(get_current_user)):
    """Anyone with tenant access can see prices — no PII."""
    if not (user or {}).get("tenant_id"):
        raise HTTPException(401, "tenant_missing")
    rows = await sub_svc.list_prices()
    return {"count": len(rows), "rows": rows}


@router.get("")
async def get_subscriptions(
    customer_id: Optional[str] = Query(None),
    status: str = Query("all"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    user: Dict[str, Any] = Depends(get_current_user),
):
    tid = _tenant_id(user)
    return await sub_svc.list_subscriptions(
        tenant_id=tid, customer_id=customer_id, status=status,
        limit=limit, skip=skip,
    )


@router.post("")
async def post_subscription(
    body: CreateSubBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_write_role(user)
    tid = _tenant_id(user)
    try:
        row = await sub_svc.create_subscription(
            tenant_id=tid,
            customer_id=body.customer_id,
            price_id=body.price_id,
            quantity=body.quantity,
            payment_method_id=body.payment_method_id,
            trial_days=body.trial_days,
            cancel_at_period_end=body.cancel_at_period_end,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("[subscriptions] create failed: %s", exc)
        raise HTTPException(502, f"stripe_create_failed: {exc}")
    return row


@router.patch("/{stripe_sub_id}")
async def patch_subscription(
    stripe_sub_id: str,
    body: UpdateSubBody,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_write_role(user)
    tid = _tenant_id(user)
    try:
        row = await sub_svc.update_subscription(
            tenant_id=tid, sub_id=stripe_sub_id,
            price_id=body.price_id, quantity=body.quantity,
            cancel_at_period_end=body.cancel_at_period_end,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("[subscriptions] update failed: %s", exc)
        raise HTTPException(502, f"stripe_update_failed: {exc}")
    if row is None:
        # Cross-tenant or missing mirror — return 404 to avoid leaking.
        raise HTTPException(404, "subscription_not_found")
    return row


@router.delete("/{stripe_sub_id}")
async def delete_subscription(
    stripe_sub_id: str,
    mode: str = Query("at_period_end"),
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_write_role(user)
    tid = _tenant_id(user)
    if mode not in ("at_period_end", "immediate"):
        raise HTTPException(400, "mode must be 'at_period_end' or 'immediate'")
    try:
        row = await sub_svc.cancel_subscription(
            tenant_id=tid, sub_id=stripe_sub_id,
            immediate=(mode == "immediate"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[subscriptions] cancel failed: %s", exc)
        raise HTTPException(502, f"stripe_cancel_failed: {exc}")
    if row is None:
        raise HTTPException(404, "subscription_not_found")
    return row
