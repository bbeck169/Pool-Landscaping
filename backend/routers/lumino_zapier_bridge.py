"""Task QQ Phase 2 (+ Phase 2.5 · Feb 2026) — Zapier bridge for Lumino.

Lumino has no native webhooks. Zapier bridges the async event stream:
Lumino event → Zap → POST /api/webhooks/lumino/zapier with a shared
secret. This endpoint verifies the secret, resolves the event_type
(header → payload inference → unknown), persists idempotently, and
dispatches to per-event handlers (stubs for now).

Preview safety: verification + persist still run; downstream state
transitions are TODO(phase3) stubs guarded by logging only.

Phase 2.5 — event_type resolution
---------------------------------

User's Zapier setup ships **3 payment Zaps** (New / Updated /
Refunded) plus the existing subscription + dispute Zaps. Each Zap
sets a static ``event_type`` HTTP header. If a Zap is misconfigured
and the header is missing (or arrives with a garbage value that
isn't in the allow-list), we fall back to inferring from the JSON
payload's ``data.status`` field so no event is silently dropped.

Every stored ``payment_events`` doc records ``resolution_source``:
``header`` / ``inferred`` / ``unknown`` — so operators can spot a
mis-configured Zap by querying
``db.payment_events.count_documents({"resolution_source": "inferred"})``
over a rolling window.

Shared-secret handling: ``LUMINO_ZAPIER_SHARED_SECRET`` stays empty
in preview `.env`. The prod secret is minted with
``openssl rand -hex 32`` at cutover and set directly in the prod
pod's secure env vars — **never** in code, chat, email, or logs.
The last chat-pasted value is treated as compromised regardless of
whether it actually leaked and MUST be regenerated.
"""
from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request

from config import db

router = APIRouter()
log = logging.getLogger("lumino_zapier_bridge")

# ────────────────────────────────────────────────────────────────
# Allow-list. Every event_type the bridge is willing to accept
# from a header or inference. Anything outside this set is treated
# as "unknown" and stored with ``event_type="unknown"``.
# ────────────────────────────────────────────────────────────────
VALID_EVENT_TYPES = frozenset({
    "payment.created",
    "payment.updated",
    "payment.refunded",
    "subscription.renewed",
    "subscription.canceled",
    "dispute.opened",
    "dispute.resolved",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _shared_secret() -> str:
    return (os.environ.get("LUMINO_ZAPIER_SHARED_SECRET") or "").strip()


async def _has_prior_payment_event(payment_id: str) -> bool:
    """Return True iff we have previously seen a Lumino event that
    referenced this ``data.payment_id``. Used to disambiguate
    ``payment.created`` from ``payment.updated`` when inferring
    from ``data.status``."""
    if not payment_id:
        return False
    prev = await db.payment_events.find_one(
        {"raw.data.payment_id": payment_id},
        {"_id": 0, "id": 1},
    )
    return prev is not None


async def _infer_event_type(data: Dict[str, Any]) -> str:
    """Second-chance resolver — uses ``data.status`` when the
    header was missing / invalid. Returns ``"unknown"`` if nothing
    matches so the caller can persist a bookkeeping row and WARN."""
    status = (data.get("status") or "").strip().lower()
    if status in ("succeeded", "paid", "completed"):
        # ``payment.created`` for a first sighting; ``payment.updated``
        # if we've stored an event carrying this payment_id already.
        seen = await _has_prior_payment_event(data.get("payment_id") or "")
        return "payment.updated" if seen else "payment.created"
    if status in ("refunded", "partial_refund"):
        return "payment.refunded"
    if status in ("failed", "declined"):
        return "payment.updated"
    if status == "canceled" and (data.get("subscription_id")
                                        or data.get("object") == "subscription"):
        return "subscription.canceled"
    return "unknown"


async def _resolve_event_type(request: Request,
                                    body: Dict[str, Any]) -> Tuple[str, str]:
    """Header-first → payload-inference → unknown. Returns
    ``(event_type, resolution_source)`` where ``resolution_source``
    is ``"header"`` / ``"inferred"`` / ``"unknown"``."""
    header_val = (request.headers.get("event_type") or "").strip()
    if header_val and header_val in VALID_EVENT_TYPES:
        return header_val, "header"
    # Header missing OR contains a value not in the allow-list.
    inferred = await _infer_event_type(body.get("data") or {})
    if inferred == "unknown":
        log.warning("Zapier bridge: could not resolve event_type "
                       "(header=%r, data.status=%r) — storing as "
                       "'unknown' for later triage",
                       header_val or None,
                       (body.get("data") or {}).get("status"))
        return "unknown", "unknown"
    return inferred, "inferred"


async def _dispatch(event_type: str, data: Dict[str, Any]) -> None:
    """Per-event-type state-transition dispatcher. Phase 2 stubs —
    each branch logs the intent; Phase 3 (post-cutover) fills in
    the actual mutations. Every event_type in ``VALID_EVENT_TYPES``
    has an explicit branch so nothing is silently dropped."""
    if event_type == "payment.created":
        # TODO(phase3): create/update local `payments` doc, mirror
        # to invoice if `data.invoice_id` present.
        log.info("Zapier: payment.created for %s", data.get("payment_id"))
    elif event_type == "payment.updated":
        # TODO(phase3): patch local `payments` doc status/amount.
        log.info("Zapier: payment.updated for %s", data.get("payment_id"))
    elif event_type == "payment.refunded":
        # TODO(phase3): mark invoice refunded, emit customer notification.
        log.info("Zapier: payment.refunded for %s", data.get("payment_id"))
    elif event_type == "subscription.renewed":
        # TODO(phase3): mark invoice paid on data.invoice_id, extend
        # subscription.current_period_end.
        log.info("Zapier: subscription.renewed for %s",
                    data.get("subscription_id"))
    elif event_type == "subscription.canceled":
        # TODO(phase3): mark subscription.status = canceled,
        # freeze autobilling.
        log.info("Zapier: subscription.canceled for %s",
                    data.get("subscription_id"))
    elif event_type in ("dispute.opened", "dispute.resolved"):
        # TODO(phase3): append to dispute dashboard.
        log.info("Zapier: %s for %s", event_type, data.get("dispute_id"))
    elif event_type == "unknown":
        # Persist-only — no state mutation. Operator picks this up
        # via a dashboard query (see module docstring).
        log.info("Zapier: unknown event stored for later triage")
    else:
        # Should be unreachable — every allow-listed type has a
        # branch above. Present so a future contributor who adds a
        # new event_type but forgets a case doesn't silently fail.
        log.warning("Zapier: unhandled event_type=%s (add a branch "
                       "in _dispatch)", event_type)


@router.post("/webhooks/lumino/zapier",
              operation_id="webhooks.lumino.zapier")
async def receive_zapier_bridge(request: Request):
    # ── Shared-secret verification ────────────────────────────────
    expected = _shared_secret()
    if not expected:
        # Fail closed — refuse to accept anything until env is set.
        raise HTTPException(401, "shared secret not configured")
    got = (request.headers.get("x-zapier-shared-secret") or "").strip()
    if not hmac.compare_digest(expected, got):
        log.warning("Zapier bridge auth failed (header mismatch)")
        raise HTTPException(401, "invalid shared secret")

    # ── Body parse + event_id gate ────────────────────────────────
    try:
        body = await request.json()
    except Exception:                                                # noqa: BLE001
        raise HTTPException(400, "invalid json body")
    event_id: Optional[str] = body.get("event_id")
    if not event_id:
        # ``event_type`` is no longer required in the body; it can
        # come from the header or be inferred. But without an
        # ``event_id`` we cannot idempotently dedupe.
        raise HTTPException(400, "event_id required")

    # ── Idempotent dedupe ────────────────────────────────────────
    existing = await db.payment_events.find_one(
        {"lumino_event_id": event_id}, {"_id": 0, "id": 1},
    )
    if existing:
        return {"ok": True, "deduped": True, "event_id": event_id}

    # ── Resolve event_type (header → inference → unknown) ────────
    event_type, resolution_source = await _resolve_event_type(request, body)

    # ── Persist + dispatch ───────────────────────────────────────
    await db.payment_events.insert_one({
        "id": event_id,
        "lumino_event_id": event_id,
        "type": event_type,
        "event_type": event_type,                                     # duplicate for readability in ops queries
        "resolution_source": resolution_source,
        "source": "zapier",
        "occurred_at": body.get("occurred_at") or _now_iso(),
        "received_at": _now_iso(),
        "raw": body,
        "processed": False,
    })
    await _dispatch(event_type, body.get("data") or {})
    return {
        "ok": True,
        "deduped": False,
        "event_id": event_id,
        "event_type": event_type,
        "resolution_source": resolution_source,
    }
