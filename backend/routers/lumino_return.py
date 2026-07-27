"""Task QQ Phase 2 · Feb 2026 — Lumino return-URL + polling reconciler.

Two endpoints for hosted-checkout completion + a scheduled reconciler
that closes the loop for any session missed by both the return-URL
and the Zapier bridge.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from config import db
from utils import get_current_user
from services.payments import (
    get_payment_provider,
    PaymentProviderDryRun,
    PaymentProviderNotConfigured,
    PaymentTestScopeViolation,
)

router = APIRouter()
log = logging.getLogger("lumino_return_reconciler")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _fetch_status_safe(session_id: str) -> dict:
    """Call the provider — accept a dry-run payload as a valid
    (mocked) status response so preview flows continue without live
    creds."""
    provider = get_payment_provider()
    try:
        return await provider.get_payment_status(session_id=session_id)
    except PaymentProviderDryRun as ex:
        return {"provider_status": "dry_run", "raw": ex.payload}
    except PaymentTestScopeViolation:
        return {"provider_status": "scope_violation"}
    except PaymentProviderNotConfigured:
        return {"provider_status": "not_configured"}
    except NotImplementedError:
        # Active provider (Stripe today) does not implement Lumino's
        # status probe — preview should still render a mock success
        # so QA can exercise the return-URL flow end-to-end.
        return {"provider_status": "paid" if session_id.startswith("mock_")
                                     else "not_supported",
                  "session_id": session_id,
                  "raw": {"mock_fallback": True}}


@router.post("/payments/lumino/return",
              operation_id="payments.lumino.return")
async def payments_lumino_return(
    body: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    """Called by the frontend `/portal/payment-method/return` page
    after Lumino redirects the customer back post-checkout."""
    session_id = (body.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(400, "session_id required")
    status = await _fetch_status_safe(session_id)
    provider_status = status.get("provider_status") or status.get("status")
    invoice_id = status.get("invoice_id")
    outcome = "unknown"
    next_step = "back_to_portal"
    if provider_status in ("paid", "succeeded"):
        outcome = "paid"
        next_step = "success_screen"
        if invoice_id:
            await db.invoices.update_one(
                {"id": invoice_id},
                {"$set": {
                    "status": "paid",
                    "paid_at": _now_iso(),
                    "lumino_payment_session_id": session_id,
                }},
            )
    elif provider_status in ("cancelled", "canceled"):
        outcome = "cancelled"
        next_step = "back_to_invoice"
    elif provider_status in ("failed", "declined"):
        outcome = "failed"
        next_step = "retry_prompt"
    elif provider_status == "dry_run":
        outcome = "paid"  # In preview we pretend the mock said OK.
        next_step = "success_screen"
    return {
        "status": outcome,
        "invoice_id": invoice_id,
        "session_id": session_id,
        "next_step": next_step,
        "provider_status": provider_status,
    }


# ────────────────────────────────────────────────────────────────
# Nightly reconciler — re-exported from ``services.lumino_reconciler``
# so existing pytests that do ``from routers.lumino_return import
# reconcile_once`` keep working. New callers should import from
# ``services.lumino_reconciler.run_reconcile_once`` directly.
# ────────────────────────────────────────────────────────────────
from services.lumino_reconciler import run_reconcile_once as reconcile_once  # noqa: E402,F401
