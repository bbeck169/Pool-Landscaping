"""LZ2 · Feb-2026 — Outbound Zapier catch-hook dispatcher.

Fires a request to the Zapier catch-hook that runs the
"Create Lumino Payment Link" Zap. The Zap synthesizes a Lumino
checkout URL and calls back into
``POST /api/webhooks/lumino/invoice-link-created`` (LZ1) with the
URL so we can store it on the invoice.

Fail-open design: any failure here is logged but never raises to
the caller. Invoice creation must NOT block on Zapier availability.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

log = logging.getLogger("lz2.dispatcher")

_TIMEOUT_SECS = 10.0
_RETRY_BACKOFF_SECS = 2.0


def _webhook_url() -> str:
    v = (os.environ.get("ZAPIER_INVOICE_LINK_WEBHOOK_URL") or "").strip()
    if not v or v.startswith("REPLACE_ME_") or "/REPLACE_ME/" in v:
        return ""
    return v


def _shared_secret() -> str:
    v = (os.environ.get("LUMINO_ZAPIER_SHARED_SECRET") or "").strip()
    if v.startswith("REPLACE_ME_"):
        return ""
    return v


def _cid() -> str:
    return uuid.uuid4().hex[:16]


def _amount_cents(inv: Dict[str, Any]) -> int:
    """Prefer explicit amount_cents; else derive from total (dollars).
    Handles decimals safely."""
    if inv.get("amount_cents") is not None:
        try:
            return int(inv["amount_cents"])
        except (TypeError, ValueError):
            pass
    total = inv.get("balance") if inv.get("balance") is not None else inv.get("total")
    try:
        return int(round(float(total or 0) * 100))
    except (TypeError, ValueError):
        return 0


def _build_payload(invoice: Dict[str, Any], customer: Dict[str, Any],
                    base_return_url: str, correlation_id: str) -> Dict[str, Any]:
    invoice_id = str(invoice.get("id") or "")
    number = invoice.get("invoice_number") or invoice.get("number") or invoice_id
    cents = _amount_cents(invoice)
    return {
        "event_type": "invoice.created",
        "invoice_id": invoice_id,
        "invoice_number": number,
        "customer_id": customer.get("id") or invoice.get("customer_id"),
        "customer_name": customer.get("name") or invoice.get("customer_name"),
        "customer_email": customer.get("email") or invoice.get("customer_email"),
        "customer_phone": customer.get("phone") or customer.get("phone_number"),
        "amount_cents": cents,
        "amount_display": f"{cents / 100:.2f}",
        "currency": invoice.get("currency") or "USD",
        "description": f"Invoice {number} — "
                          f"{invoice.get('title') or invoice.get('description') or 'Payment'}",
        "return_url":
            f"{base_return_url.rstrip('/')}/portal/payment-method/return"
            f"?invoice_id={invoice_id}",
        "external_id": invoice_id,
        "tenant_id": invoice.get("tenant_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": correlation_id,
    }


async def _post_once(client: httpx.AsyncClient, url: str, payload: Dict[str, Any],
                      headers: Dict[str, str]) -> httpx.Response:
    return await client.post(url, json=payload, headers=headers,
                              timeout=_TIMEOUT_SECS)


async def dispatch_invoice_link_request(
    invoice: Dict[str, Any],
    customer: Dict[str, Any],
    base_return_url: str = "",
) -> Dict[str, Any]:
    """Fire-and-forget POST to Zapier catch-hook.

    Returns ``{"dispatched": bool, "reason": str | None, "correlation_id": str}``.
    """
    correlation_id = _cid()

    # ── Pre-flight guards ─────────────────────────────────────────
    url = _webhook_url()
    if not url:
        log.warning("[LZ2] ZAPIER_INVOICE_LINK_WEBHOOK_URL not configured — "
                     "skipping dispatch invoice_id=%s",
                     invoice.get("id"))
        return {"dispatched": False, "reason": "not_configured",
                "correlation_id": correlation_id}

    if invoice.get("status") == "paid" or invoice.get("paid_at"):
        return {"dispatched": False, "reason": "already_paid",
                "correlation_id": correlation_id}

    if invoice.get("lumino_payment_url"):
        return {"dispatched": False, "reason": "already_has_url",
                "correlation_id": correlation_id}

    payload = _build_payload(invoice, customer, base_return_url or "",
                              correlation_id)
    headers = {"Content-Type": "application/json"}
    secret = _shared_secret()
    if secret:
        headers["x-zapier-shared-secret"] = secret

    # ── POST with one retry on 5xx / timeout ──────────────────────
    async with httpx.AsyncClient() as client:
        for attempt in (1, 2):
            try:
                r = await _post_once(client, url, payload, headers)
                if 200 <= r.status_code < 300:
                    log.info("[LZ2] dispatched invoice-link request "
                              "invoice_id=%s correlation=%s attempt=%d",
                              invoice.get("id"), correlation_id, attempt)
                    return {"dispatched": True, "reason": None,
                            "correlation_id": correlation_id}
                if r.status_code >= 500 and attempt == 1:
                    await asyncio.sleep(_RETRY_BACKOFF_SECS)
                    continue
                # 4xx or repeated 5xx — give up.
                log.error("[LZ2] Zapier catch-hook returned %d on attempt %d "
                          "for invoice_id=%s correlation=%s",
                          r.status_code, attempt, invoice.get("id"),
                          correlation_id)
                break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == 1:
                    log.warning("[LZ2] Zapier transient failure attempt=1 "
                                 "invoice_id=%s reason=%s",
                                 invoice.get("id"), type(exc).__name__)
                    await asyncio.sleep(_RETRY_BACKOFF_SECS)
                    continue
                log.error("[LZ2] Zapier unreachable after 2 attempts "
                          "invoice_id=%s reason=%s correlation=%s",
                          invoice.get("id"), type(exc).__name__,
                          correlation_id)
                break

    return {"dispatched": False, "reason": "zapier_unreachable",
            "correlation_id": correlation_id}


def schedule_dispatch(invoice: Dict[str, Any], customer: Dict[str, Any],
                       base_return_url: str = "") -> None:
    """Fire-and-forget helper — schedules the dispatch on the event
    loop so the calling request-handler returns immediately. Any
    exceptions inside the task are swallowed and logged."""

    async def _runner():
        try:
            await dispatch_invoice_link_request(invoice, customer,
                                                  base_return_url)
        except Exception as exc:                                      # noqa: BLE001
            log.error("[LZ2] scheduled dispatcher crashed: %s",
                        type(exc).__name__)

    try:
        asyncio.create_task(_runner())
    except RuntimeError:
        # No running loop (edge case, e.g. sync-context callers).
        # Best-effort: run to completion inline. This should be rare.
        try:
            asyncio.run(_runner())
        except Exception as exc:                                      # noqa: BLE001
            log.error("[LZ2] inline dispatcher fallback crashed: %s",
                        type(exc).__name__)
