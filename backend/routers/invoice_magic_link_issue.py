"""Feb-2026 · Task 3 — Invoices bypass portal.

Route: ``GET /api/invoices/{iid}/magic-link``

Mints a magic-link token for the given invoice and returns a public
URL under ``/i/<token>`` that renders the full itemized ``InvoiceView``
with an inline Pay Now. Portal-free — the customer never sees the
authenticated portal chrome again for invoice pay.

Auth posture:

* Admin / manager / super_admin → any invoice in their tenant.
* Customer role                  → only their own invoices.
* Tech / technician              → 403.

Response:

    {
        "invoice_id": str,
        "token": str,
        "url": str,           # {APP_PUBLIC_URL}/i/<token>
        "days_valid": int,
    }

Logs a single INFO line on issuance so ops can trace portal→magic-link
redirects during the deprecation window:

    ``[invoice_magic_link] issued invoice=<iid> customer=<cid> role=<role>``
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException

from config import db
from services.pay_link_builder import issue_invoice_magic_token
from services.invoice_lookup import find_invoice_dual
from utils import get_current_user


router = APIRouter()
_LOG = logging.getLogger("invoice.magic_link")


def _resolve_base() -> str:
    return (os.environ.get("APP_PUBLIC_URL") or "").rstrip("/")


@router.get("/invoices/{iid}/magic-link")
async def issue_invoice_magic_link(
    iid: str, user: dict = Depends(get_current_user),
):
    role = (user or {}).get("role") or ""
    if role in ("tech", "technician"):
        raise HTTPException(403, "forbidden")

    inv, _collection = await find_invoice_dual(db, iid)
    if not inv:
        raise HTTPException(404, "invoice_not_found")

    tenant_id = inv.get("tenant_id")
    if not tenant_id:
        raise HTTPException(500, "invoice_missing_tenant")

    # Doc-type guard — never mint invoice magic links against an estimate.
    _doc_type = str(inv.get("doc_type") or "invoice").lower()
    if _doc_type in ("estimate", "quote"):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "not_an_invoice",
                "doc_type": _doc_type,
            },
        )

    # Customer ownership check.
    if role == "customer":
        if inv.get("customer_id") != user.get("customer_id"):
            raise HTTPException(403, "not_your_invoice")

    # Cross-tenant guard for staff.
    if role in ("admin", "manager", "super_admin") \
            and user.get("tenant_id") \
            and user.get("tenant_id") != tenant_id:
        raise HTTPException(403, "cross_tenant_forbidden")

    days = 30
    token = issue_invoice_magic_token(iid, tenant_id, days=days)
    base = _resolve_base()
    url = f"{base}/i/{token}" if base else f"/i/{token}"

    _LOG.info(
        "[invoice_magic_link] issued invoice=%s customer=%s role=%s",
        iid, inv.get("customer_id") or "-", role or "-",
    )
    return {
        "invoice_id": iid,
        "token": token,
        "url": url,
        "days_valid": days,
    }
