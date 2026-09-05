"""Feb-2026 P0 restore · Public invoice viewer via magic-link JWT.

Path: ``GET /api/invoices/{iid}/full-magic?token=<jwt>``

Serves the same payload shape as the authenticated
``GET /api/invoices/{iid}/full`` (delegates to
:func:`routers.invoice_viewer._build_viewer_payload`) after verifying
the magic-link JWT minted by
:func:`services.pay_link_builder.issue_invoice_magic_token`.

**Why this file exists (context for the next agent):**
This endpoint originally lived in ``routers/payments_stripe_live.py``
which was deleted in commit ``7047ef4`` as part of the Phase-47
direct-Stripe migration. The frontend ``InvoiceView.jsx`` still
POSTs at line 36 to ``/api/invoices/{id}/full-magic?token=...`` so
the deletion left every customer email pay-link 404'ing with a red
"Not Found" banner. Restored to the exact same route + JWT shape
so tokens minted before the deletion still verify cleanly.

Token contract (unchanged from the deleted implementation, kept
byte-for-byte identical to :func:`issue_invoice_magic_token`):

* ``sub``         — must equal the literal string ``"invoice_pay"``.
* ``invoice_id``  — the invoice id the token was minted for. MUST
                     match the ``iid`` in the URL path.
* ``tenant_id``   — extracted from the token. The URL ``iid`` is
                     resolved against ONLY that tenant, never any
                     query parameter — cross-tenant leak-proof.
* ``exp``         — 30-day expiry by default.

Failure modes (all fail-closed):

* Missing ``token=`` → 401 ``"token_missing"``.
* Bad signature / expired / malformed → 401 ``"token_invalid_or_expired"``.
* Token's ``invoice_id`` doesn't match the URL ``iid`` → 401
  ``"token_invoice_mismatch"`` (defence-in-depth against a customer
  sharing their own token to view someone else's invoice).
* Tenant referenced by the token no longer exists → 404
  ``"tenant_not_found"``.
* Invoice doesn't exist in the tenant → 404 via
  ``_build_viewer_payload`` (returns its own 404).

No RBAC helper is invoked — the magic token IS the credential. The
aggregator is called with a synthesised ``admin`` role so its own
RBAC guard (tech → 403, wrong-customer → 404) is bypassed. Because
we resolve the invoice **against the token's tenant_id only**,
there is no way for a token minted for tenant A to view a tenant-B
invoice.
"""
from __future__ import annotations

import logging

import jwt
from fastapi import APIRouter, HTTPException, Request

from config import db, JWT_ALGO, JWT_SECRET

_LOG = logging.getLogger("invoice.magic_view")

router = APIRouter()


def _verify_invoice_magic_token(token: str) -> dict:
    """Decode + validate an invoice magic-link JWT.

    Kept in sync with ``services.pay_link_builder.issue_invoice_magic_token``
    — every claim that helper stamps is asserted here. Raises
    :class:`HTTPException` on any failure; NEVER returns an invalid
    payload.
    """
    if not token:
        raise HTTPException(401, "token_missing")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token_invalid_or_expired")
    except jwt.PyJWTError:
        raise HTTPException(401, "token_invalid_or_expired")
    if payload.get("sub") != "invoice_pay":
        raise HTTPException(401, "token_invalid_or_expired")
    if not payload.get("invoice_id") or not payload.get("tenant_id"):
        raise HTTPException(401, "token_invalid_or_expired")
    return payload


@router.get("/invoices/{iid}/full-magic")
async def invoice_full_magic(iid: str, token: str = "", src: str = "",
                              request: Request = None):
    """Public — no session cookie / no ``get_current_user`` dep.

    Verifies the magic token, then returns the exact same payload
    shape as the authenticated ``/full`` endpoint. Frontend
    ``InvoiceView.jsx`` treats both endpoints as interchangeable
    once auth is established.

    Phase K47 · Feb-2026 — the optional ``?src=email|sms|link``
    query param is forwarded into the ``invoice_view_tracker`` so
    the resulting ``invoice_views`` record carries the send
    channel. Values outside the whitelist collapse to ``"link"``.
    """
    payload = _verify_invoice_magic_token(token)
    # Defence-in-depth — the token's invoice_id MUST match the URL
    # path. Prevents a leaked token being reused across invoices.
    if payload.get("invoice_id") != iid:
        raise HTTPException(401, "token_invoice_mismatch")

    tenant = await db.tenants.find_one(
        {"id": payload["tenant_id"]}, {"_id": 0},
    )
    if not tenant:
        raise HTTPException(404, "tenant_not_found")

    # Local import to avoid pulling the invoice_viewer aggregator into
    # the boot path of this small router. Also keeps this module's
    # dep graph flat for the test that stubs out the aggregator.
    from routers.invoice_viewer import _build_viewer_payload

    # Synthesise an admin-scoped user so the aggregator's own RBAC
    # (tech → 403, wrong-customer → 404) is bypassed — the magic
    # token has already established ownership.
    virt_user = {"role": "admin", "id": "magic-link",
                    "email": "magic-link@invoice"}
    result = await _build_viewer_payload(iid, tenant, virt_user)

    # Phase K47 · Fire-and-forget view stamp. Never raises —
    # ``record_invoice_view`` swallows Mongo failures internally so
    # the customer's page render is never blocked on it.
    try:
        from services.invoice_view_tracker import record_invoice_view
        ua = request.headers.get("user-agent") if request is not None else None
        ip = (request.client.host
                if request is not None and request.client is not None
                else None)
        await record_invoice_view(
            invoice_id=iid,
            tenant_id=tenant["id"],
            source=src or "link",
            user_agent=ua,
            ip=ip,
        )
    except Exception:  # pragma: no cover — defensive belt-and-suspenders
        pass

    return result
