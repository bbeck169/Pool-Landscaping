"""Task QQ Phase 2 (+ 2.5 + 2.7 · Feb 2026) — Zapier bridge for Lumino.

Lumino has no native webhooks. Zapier bridges the async event stream:
Lumino event → Zap → POST /api/webhooks/lumino/zapier with a shared
secret. This endpoint verifies the secret, resolves the event_type
(header → payload inference → unknown), persists idempotently, and
dispatches to per-event handlers (stubs for now).

Preview safety: verification + persist still run; downstream state
transitions are TODO(phase3) stubs guarded by logging only.

Phase 2.5 — event_type resolution
---------------------------------

Header ``event_type`` → payload inference via ``data.status`` →
``unknown``. Every stored ``payment_events`` doc records
``resolution_source``.

Phase 2.7 — defensive hardening (Feb 2026)
------------------------------------------

User reported HTTP 500s from Zapier test webhooks against prod.
Preview logs showed only 401s (fail-closed on empty secret), so
the crash lives on the prod side where the secret IS set and some
payload path was blowing up. This pass:

* **Correlation ids** — every request is stamped with a UUID that
  appears in every log line + in the response body when we return
  an error. Grep-able post-mortem.
* **Every field optional** — missing ``event_id``, ``event_type``,
  ``occurred_at``, or ``data`` are all handled with sane defaults
  + WARN log, never a crash.
* **Test-mode short-circuit** — Zapier's "Test this Zap" often
  sends ``{}`` or ``{"data": {}}``. Detect that shape after the
  secret check and return 200 with ``test_mode: true`` so the
  Zapier setup UX doesn't red-X on a normal test click.
* **Dispatch fenced** — the ``_dispatch`` stub is wrapped in
  try/except so a downstream state-transition bug can't 500 the
  bridge. Failures return 200 with ``dispatched: false`` +
  ``dispatch_error``.
* **Handler-wide try/except** — any unhandled exception logs the
  full traceback server-side + returns 500 with a clean JSON body
  ``{ok: false, error: "internal_error", correlation_id}``.
* **Verbose request log** — every incoming request logs remote
  IP, header set (with the shared secret redacted to first-6
  chars), and payload preview (first 500 chars).

Shared-secret handling: ``LUMINO_ZAPIER_SHARED_SECRET`` stays empty
in preview `.env`. The prod secret is minted with
``openssl rand -hex 32`` at cutover and set directly in the prod
pod's secure env vars — **never** in code, chat, email, or logs.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from config import db

router = APIRouter()
log = logging.getLogger("lumino_zapier_bridge")

# ────────────────────────────────────────────────────────────────
# Allow-list — every event_type the bridge is willing to accept
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


# Boot-time confirmation that the env var is populated by Emergent
# Secrets (or wherever). Prints the first 4 characters ONLY so an
# operator can distinguish which secret is active without leaking
# the value. The full secret NEVER appears in any log line.
_boot_sec = (os.environ.get("LUMINO_ZAPIER_SHARED_SECRET") or "").strip()
if _boot_sec:
    log.info("[LUMINO_ZAPIER] shared secret configured: %s… (len=%d)",
                _boot_sec[:4], len(_boot_sec))
else:
    log.warning("[LUMINO_ZAPIER] shared secret NOT configured — bridge "
                   "will 401 every request until env is populated")


def _redact_headers(headers) -> Dict[str, str]:
    """Return a header dict safe for INFO logging — the shared
    secret is truncated to first 6 chars + ellipsis so operators can
    tell WHICH secret Zapier sent without leaking it."""
    out: Dict[str, str] = {}
    for k, v in dict(headers).items():
        if k.lower() == "x-zapier-shared-secret":
            val = str(v or "")
            out[k] = f"{val[:6]}…" if val else "(empty)"
        elif k.lower() in ("authorization", "cookie"):
            out[k] = "(redacted)"
        else:
            out[k] = str(v)
    return out


async def _has_prior_payment_event(payment_id: str) -> bool:
    if not payment_id:
        return False
    try:
        prev = await db.payment_events.find_one(
            {"raw.data.payment_id": payment_id},
            {"_id": 0, "id": 1},
        )
    except Exception:                                                # noqa: BLE001
        return False
    return prev is not None


async def _infer_event_type(data: Dict[str, Any]) -> str:
    status = (data.get("status") or "").strip().lower()
    if status in ("succeeded", "paid", "completed"):
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
                                    body: Dict[str, Any],
                                    correlation_id: str) -> Tuple[str, str]:
    """Header-first → payload-inference → unknown. Returns
    ``(event_type, resolution_source)``. Never raises."""
    try:
        header_val = (request.headers.get("event_type") or "").strip()
    except Exception:                                                # noqa: BLE001
        header_val = ""
    if header_val and header_val in VALID_EVENT_TYPES:
        log.info("[%s] event_type resolved from header: %s",
                    correlation_id, header_val)
        return header_val, "header"
    try:
        inferred = await _infer_event_type(body.get("data") or {})
    except Exception as exc:                                        # noqa: BLE001
        log.warning("[%s] inference crashed: %s", correlation_id, exc)
        inferred = "unknown"
    if inferred == "unknown":
        log.warning("[%s] could not resolve event_type "
                       "(header=%r, data.status=%r) — storing as 'unknown'",
                       correlation_id, header_val or None,
                       (body.get("data") or {}).get("status"))
        return "unknown", "unknown"
    log.info("[%s] event_type inferred from payload: %s",
                correlation_id, inferred)
    return inferred, "inferred"


async def _dispatch(event_type: str, data: Dict[str, Any],
                          correlation_id: str) -> None:
    """Per-event-type state-transition dispatcher. Phase 2 stubs.
    Every branch is best-effort; the caller is responsible for
    catching exceptions and reporting a ``dispatch_error`` in the
    response."""
    if event_type == "payment.created":
        log.info("[%s] Zapier: payment.created for %s",
                    correlation_id, data.get("payment_id"))
    elif event_type == "payment.updated":
        log.info("[%s] Zapier: payment.updated for %s",
                    correlation_id, data.get("payment_id"))
    elif event_type == "payment.refunded":
        log.info("[%s] Zapier: payment.refunded for %s",
                    correlation_id, data.get("payment_id"))
    elif event_type == "subscription.renewed":
        log.info("[%s] Zapier: subscription.renewed for %s",
                    correlation_id, data.get("subscription_id"))
    elif event_type == "subscription.canceled":
        log.info("[%s] Zapier: subscription.canceled for %s",
                    correlation_id, data.get("subscription_id"))
    elif event_type in ("dispute.opened", "dispute.resolved"):
        log.info("[%s] Zapier: %s for %s",
                    correlation_id, event_type, data.get("dispute_id"))
    elif event_type == "unknown":
        log.info("[%s] Zapier: unknown event stored for later triage",
                    correlation_id)
    else:
        log.warning("[%s] Zapier: unhandled event_type=%s (add a "
                       "branch in _dispatch)", correlation_id, event_type)


def _looks_like_test_payload(body: Any) -> bool:
    """Zapier's ``Test this Zap`` sends either ``{}``, ``null``, OR
    ``{"data": {}}`` (with no event_id / event_type header). Return
    True on any of those shapes so we can short-circuit with a
    friendly 200 instead of choking on missing fields."""
    if body is None:
        return True
    if not isinstance(body, dict):
        return False
    if not body:
        return True
    # {"data": {}} or {"data": null} with nothing else.
    keys = set(body.keys())
    if keys <= {"data"}:
        d = body.get("data")
        if d is None or (isinstance(d, dict) and not d):
            return True
    return False


@router.post("/webhooks/lumino/zapier",
              operation_id="webhooks.lumino.zapier")
async def receive_zapier_bridge(request: Request):
    correlation_id = uuid.uuid4().hex[:16]
    remote = None
    try:
        remote = request.client.host if request.client else None
    except Exception:                                                # noqa: BLE001
        pass

    try:
        # ── Verbose request log ────────────────────────────────────
        headers_safe = _redact_headers(request.headers)
        raw_bytes = await request.body()
        raw_preview = raw_bytes[:500].decode("utf-8", errors="replace")
        log.info("[%s] incoming zapier bridge request "
                    "remote=%s headers=%s body=%s",
                    correlation_id, remote, headers_safe, raw_preview)

        # ── Shared-secret verification ────────────────────────────
        expected = _shared_secret()
        got = (request.headers.get("x-zapier-shared-secret") or "").strip()
        if not expected:
            log.warning("[%s] shared secret NOT configured on server "
                           "(LUMINO_ZAPIER_SHARED_SECRET empty) — refusing",
                           correlation_id)
            return JSONResponse(
                status_code=401,
                content={"ok": False, "error": "shared_secret_not_configured",
                            "correlation_id": correlation_id},
            )
        if not hmac.compare_digest(expected, got):
            log.warning("[%s] shared secret mismatch (got prefix=%r)",
                           correlation_id, got[:6])
            return JSONResponse(
                status_code=401,
                content={"ok": False, "error": "invalid_shared_secret",
                            "correlation_id": correlation_id},
            )
        log.info("[%s] shared secret verified OK", correlation_id)

        # ── Body parse ────────────────────────────────────────────
        if not raw_bytes:
            body: Any = {}
        else:
            try:
                body = json.loads(raw_bytes)
            except Exception as exc:                                # noqa: BLE001
                log.warning("[%s] invalid JSON body: %s",
                              correlation_id, exc)
                return JSONResponse(
                    status_code=400,
                    content={"ok": False, "error": "invalid_json_body",
                                "detail": str(exc),
                                "correlation_id": correlation_id},
                )

        # ── Zapier test-payload short-circuit ─────────────────────
        # If the payload is Zapier's "Test this Zap" shape AND no
        # event_type header, respond with a friendly 200 so the
        # Zapier setup UI shows green.
        header_evt = (request.headers.get("event_type") or "").strip()
        if _looks_like_test_payload(body) and not header_evt:
            log.info("[%s] Zapier test payload detected — returning "
                        "test_mode=true", correlation_id)
            return {
                "ok": True, "test_mode": True,
                "message": "Zapier test payload received",
                "correlation_id": correlation_id,
            }

        if not isinstance(body, dict):
            body = {"data": {}}

        # ── Field defaults ────────────────────────────────────────
        event_id: Optional[str] = body.get("event_id")
        if not event_id:
            event_id = f"gen_{uuid.uuid4().hex}"
            log.warning("[%s] event_id missing — generated %s",
                           correlation_id, event_id)
            body["event_id"] = event_id
        if "data" not in body or body.get("data") is None:
            body["data"] = {}
            log.warning("[%s] data missing — defaulted to {}",
                           correlation_id)
        if not body.get("occurred_at"):
            body["occurred_at"] = _now_iso()
            log.warning("[%s] occurred_at missing — defaulted to now",
                           correlation_id)

        # ── Idempotent dedupe ─────────────────────────────────────
        try:
            existing = await db.payment_events.find_one(
                {"lumino_event_id": event_id}, {"_id": 0, "id": 1},
            )
        except Exception as exc:                                    # noqa: BLE001
            log.error("[%s] dedupe query failed: %s",
                         correlation_id, exc)
            existing = None
        if existing:
            log.info("[%s] duplicate event_id=%s — deduped",
                        correlation_id, event_id)
            return {"ok": True, "deduped": True,
                      "event_id": event_id,
                      "correlation_id": correlation_id}

        # ── Resolve event_type ────────────────────────────────────
        event_type, resolution_source = await _resolve_event_type(
            request, body, correlation_id,
        )

        # ── Persist ────────────────────────────────────────────────
        try:
            await db.payment_events.insert_one({
                "id": event_id,
                "lumino_event_id": event_id,
                "type": event_type,
                "event_type": event_type,
                "resolution_source": resolution_source,
                "source": "zapier",
                "occurred_at": body.get("occurred_at"),
                "received_at": _now_iso(),
                "correlation_id": correlation_id,
                "raw": body,
                "processed": False,
            })
        except Exception as exc:                                    # noqa: BLE001
            log.error("[%s] persist failed: %s", correlation_id, exc)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": "persist_failed",
                            "detail": str(exc),
                            "correlation_id": correlation_id},
            )

        # ── Dispatch (fenced — a bug here MUST NOT 500 the bridge) ─
        dispatched = True
        dispatch_error: Optional[str] = None
        try:
            await _dispatch(event_type, body.get("data") or {},
                                correlation_id)
        except Exception as exc:                                    # noqa: BLE001
            dispatched = False
            dispatch_error = str(exc)[:200]
            log.error("[%s] dispatch handler crashed: %s\n%s",
                         correlation_id, exc, traceback.format_exc())

        return {
            "ok": True,
            "deduped": False,
            "event_id": event_id,
            "event_type": event_type,
            "resolution_source": resolution_source,
            "dispatched": dispatched,
            **({"dispatch_error": dispatch_error}
                 if dispatch_error else {}),
            "correlation_id": correlation_id,
        }

    except HTTPException:
        # Any HTTPException we DID raise (e.g., from a helper we
        # haven't inlined) — re-raise so FastAPI serialises normally.
        raise
    except Exception as exc:                                        # noqa: BLE001
        log.error(
            "[%s] UNHANDLED exception in zapier bridge: %s\n%s",
            correlation_id, exc, traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "internal_error",
                        "correlation_id": correlation_id},
        )
