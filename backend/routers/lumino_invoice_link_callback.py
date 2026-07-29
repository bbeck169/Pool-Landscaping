"""LZ1 · Feb-2026 — Lumino invoice-link callback receiver.

Zapier calls this endpoint after successfully creating a Lumino
payment link. We persist the returned ``lumino_payment_url`` on the
CRM invoice so it can be surfaced to the user (Pay button, portal,
email links).

Auth: header-only shared-secret pattern (same as ``routers/audits.py``).
Not the HMAC pattern from ``lumino_zapier_bridge.py`` — the callback
carries no sensitive customer data beyond the invoice id + URL, and
the Zap can rotate the secret at any time.

New invoice fields (added implicitly — ``db.invoices`` is a
schema-free Mongo collection):
    lumino_payment_url:      Optional[str]
    lumino_customer_ref:     Optional[str]
    lumino_payment_ref:      Optional[str]
    lumino_link_created_at:  Optional[datetime]

Idempotency: a `payment_events` audit row is upserted with a
deterministic id derived from (invoice_id, payment_url). Repeat
callbacks for the same combination return 200 without duplicating
the audit trail.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import db

router = APIRouter()
log = logging.getLogger("lumino_invoice_link_callback")

_MAX_BODY_BYTES = 100 * 1024  # 100 KB


class InvoiceLinkCallbackResponse(BaseModel):
    ok: bool
    invoice_id: str
    lumino_payment_url_set: bool
    correlation_id: str


def _shared_secret() -> str:
    v = (os.environ.get("LUMINO_ZAPIER_SHARED_SECRET") or "").strip()
    if v.startswith("REPLACE_ME_"):
        return ""
    return v


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _persist_event_id(invoice_id: str, payment_url: str) -> str:
    """Deterministic id per (invoice_id, payment_url) combination.
    Enables idempotent upserts — same input → same document."""
    h = hashlib.sha256(f"{invoice_id}|{payment_url}".encode()).hexdigest()[:16]
    return f"invoice_link_{h}"


@router.post(
    "/webhooks/lumino/invoice-link-created",
    response_model=InvoiceLinkCallbackResponse,
)
async def lumino_invoice_link_created(request: Request):
    """Zapier-fed callback after Lumino invoice-link creation.

    Auth: ``x-zapier-shared-secret`` header must equal env
    ``LUMINO_ZAPIER_SHARED_SECRET``.
    """
    correlation_id = uuid.uuid4().hex[:16]

    # ── Auth (fail-closed on empty env) ────────────────────────────
    expected = _shared_secret()
    if not expected:
        return JSONResponse(
            status_code=503,
            content={"error": "not_configured",
                     "correlation_id": correlation_id},
        )
    got = (request.headers.get("x-zapier-shared-secret") or "").strip()
    if not got or got != expected:
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized",
                     "correlation_id": correlation_id},
        )

    # ── Body size cap ──────────────────────────────────────────────
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > _MAX_BODY_BYTES:
        return JSONResponse(status_code=413,
                             content={"error": "too_large"})
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        return JSONResponse(status_code=413,
                             content={"error": "too_large"})

    # ── Parse ──────────────────────────────────────────────────────
    try:
        body = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(status_code=400,
                             content={"error": "invalid_json"})
    if not isinstance(body, dict):
        return JSONResponse(status_code=400,
                             content={"error": "not_json_object"})

    # ── Validate required fields ───────────────────────────────────
    invoice_id = body.get("invoice_id")
    if not isinstance(invoice_id, str) or not invoice_id.strip():
        return JSONResponse(status_code=400,
                             content={"error": "missing_invoice_id"})
    invoice_id = invoice_id.strip()

    payment_url = body.get("lumino_payment_url")
    if not isinstance(payment_url, str) or not payment_url.startswith("https://"):
        return JSONResponse(status_code=400,
                             content={"error": "invalid_payment_url"})
    payment_url = payment_url.strip()

    customer_ref: Optional[str] = body.get("lumino_customer_ref")
    if customer_ref is not None and not isinstance(customer_ref, str):
        customer_ref = None
    payment_ref: Optional[str] = body.get("lumino_payment_ref")
    if payment_ref is not None and not isinstance(payment_ref, str):
        payment_ref = None

    # ── Look up invoice (dual-collection) ─────────────────────────
    from services.invoice_lookup import find_invoice_dual
    inv, collection = await find_invoice_dual(db, invoice_id)
    if not inv:
        # INFO not ERROR — this might be a probe/typo, not a real bug.
        log.info("[%s] invoice_not_found id=%s", correlation_id, invoice_id)
        return JSONResponse(status_code=404,
                             content={"error": "invoice_not_found",
                                      "correlation_id": correlation_id})

    # ── Persist on invoice (write to the collection it lives in) ─
    now = _now()
    set_fields = {
        "lumino_payment_url": payment_url,
        "lumino_link_created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    if customer_ref:
        set_fields["lumino_customer_ref"] = customer_ref
    if payment_ref:
        set_fields["lumino_payment_ref"] = payment_ref
    try:
        target = db.invoices if collection == "invoices" else db.quotes
        await target.update_one({"id": invoice_id}, {"$set": set_fields})
    except Exception as exc:                                          # noqa: BLE001
        log.error("[%s] invoice update failed: %s",
                    correlation_id, type(exc).__name__)
        return JSONResponse(status_code=500,
                             content={"error": "persist_failed",
                                      "correlation_id": correlation_id})

    # ── Idempotent audit row in payment_events ─────────────────────
    event_id = _persist_event_id(invoice_id, payment_url)
    try:
        await db.payment_events.update_one(
            {"id": event_id},
            {"$set": {
                "id": event_id,
                "type": "invoice.link_created",
                "event_type": "invoice.link_created",
                "source": "zapier",
                "invoice_id": invoice_id,
                "lumino_payment_url": payment_url,
                "lumino_customer_ref": customer_ref,
                "lumino_payment_ref": payment_ref,
                "correlation_id": correlation_id,
                "received_at": now.isoformat(),
                "raw": body,
                "processed": True,
            }},
            upsert=True,
        )
    except Exception as exc:                                          # noqa: BLE001
        # Non-fatal — invoice was persisted. Log and continue.
        log.warning("[%s] payment_events upsert failed: %s",
                     correlation_id, type(exc).__name__)

    log.info("[%s] invoice-link stored invoice_id=%s",
              correlation_id, invoice_id)
    return {
        "ok": True,
        "invoice_id": invoice_id,
        "lumino_payment_url_set": True,
        "correlation_id": correlation_id,
    }
