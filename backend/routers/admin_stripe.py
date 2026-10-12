"""Phase B3 · Feb-2026 — Stripe admin dead-letter surface.

Super_admin-only endpoints for operators to see + replay events
that crashed inside ``handle_webhook_event``. Kept intentionally
minimal — the retry endpoint just re-runs the shipped handler with
the payload we stashed at dead-letter time.

Prefix: ``/admin/stripe`` (mounted at ``/api/admin/stripe`` by the
main ``api_router``).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from utils import get_current_user
from services.payments import stripe_charge as stripe_svc
from services.payments.stripe_webhook_ledger import (
    get_dead_letter_row,
    list_dead_letter,
    mark_dead_letter_resolved,
    mark_handled,
    mark_failed,
    record_dead_letter,
)


router = APIRouter(prefix="/admin/stripe", tags=["admin-stripe"])
logger = logging.getLogger("admin_stripe")


def _require_super_admin(user: Dict[str, Any]) -> None:
    if (user or {}).get("role") != "super_admin":
        raise HTTPException(403, "super_admin_only")


@router.get("/dead-letter")
async def get_dead_letter(
    resolved: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_super_admin(user)
    rows = await list_dead_letter(resolved=resolved, limit=limit)
    return {"count": len(rows), "rows": rows}


@router.post("/dead-letter/{event_id}/retry")
async def retry_dead_letter(
    event_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    _require_super_admin(user)
    row = await get_dead_letter_row(event_id)
    if not row:
        raise HTTPException(404, f"event {event_id} not in dead-letter")
    if row.get("resolved"):
        return {"status": "already_resolved", "event_id": event_id}
    payload = row.get("raw_payload") or {}
    if not payload:
        raise HTTPException(422, "dead-letter row has no raw_payload; cannot replay")
    try:
        result = await stripe_svc.handle_webhook_event(payload)
    except Exception as exc:  # noqa: BLE001
        import traceback
        await record_dead_letter(
            payload,
            error_class=type(exc).__name__,
            error_message=str(exc),
            stack_trace=traceback.format_exc(),
        )
        await mark_failed(event_id, error=str(exc))
        raise HTTPException(500, f"retry failed: {exc}")
    await mark_handled(event_id, result=result)
    await mark_dead_letter_resolved(event_id)
    return {"status": "resolved", "event_id": event_id, "handler_result": result}


# ────────────────────────────────────────────────────────────────────
# P0c Stage 2 · S2-2 — Admin diagnostic for the Stripe webhook.
#
# ``GET /api/admin/stripe/webhook-diagnostic``
#
# Returns a redacted inventory of the Stripe mode / key / secret
# configuration PLUS the last-10 ledger rows and last-5 dead-letter
# rows. The operator reads this on prod to confirm:
#
#   * Which webhook URL(s) are mounted (both primary + legacy alias).
#   * Whether the API key + webhook signing secret are set, and
#     whether their prefixes agree with ``STRIPE_MODE``.
#   * ``mode_match`` — the single-field diagnostic that collapses
#     the 4-dimension matrix (mode × api_key × secret × app_env)
#     into one of ``live`` / ``test`` / ``mismatch`` / ``unknown``.
#     ``mismatch`` is THE most common production bug.
#   * Recent event-delivery activity so the operator can tell a
#     "no events reaching the pod" symptom from a "events arriving
#     but signature-failing" one at a glance.
#   * A suggested next-action string when a misconfig is detected,
#     so the admin UI can render actionable guidance without the
#     caller needing to reproduce the diagnostic logic.
#
# Secrets are NEVER returned in full. The ``_prefix`` fields show
# the first 8 characters only; the ``_length`` fields expose the
# character count so an operator can spot a truncated paste.
# ────────────────────────────────────────────────────────────────────
from config import db
from datetime import datetime, timezone


_MODE_MATCH_SUGGESTION = {
    "mismatch": (
        "Rotate the Stripe secret-key / webhook-secret pair so BOTH "
        "match STRIPE_MODE. Copy the current signing secret from the "
        "Stripe Dashboard → Developers → Webhooks → <your endpoint> → "
        "Signing secret, and store it in STRIPE_WEBHOOK_SECRET_LIVE "
        "(or _TEST) matching STRIPE_MODE."
    ),
    "unknown": (
        "At least one of STRIPE_SECRET_KEY_* or STRIPE_WEBHOOK_SECRET_* "
        "is unset or malformed. Set both for the current STRIPE_MODE "
        "and restart the backend. See the ``issues`` array below for "
        "the exact code + remediation per misconfig."
    ),
}


@router.get("/webhook-diagnostic")
async def webhook_diagnostic(
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Admin-gated. Returns a secret-redacted Stripe webhook config
    audit. Shaped so the admin UI panel can render both the
    diagnostic grid AND an actionable remediation string without
    reproducing the resolution logic client-side.
    """
    _require_super_admin(user)

    # Mode + secret consistency inventory.
    try:
        from services.payments.stripe_charge import (
            check_stripe_mode_consistency,
        )
        report = check_stripe_mode_consistency()
    except Exception as exc:  # noqa: BLE001 — defensive, must never 500 the admin UI
        logger.error("[admin.stripe.webhook-diagnostic] consistency check crashed: %s", exc)
        report = {
            "mode": None, "app_env": None,
            "api_key_configured": False,
            "api_key_prefix": None, "api_key_length": 0,
            "webhook_secret_configured": False,
            "webhook_secret_prefix": None, "webhook_secret_length": 0,
            "mode_match": "unknown",
            "issues": [{
                "severity": "error", "code": "diagnostic_crashed",
                "message": f"check_stripe_mode_consistency raised: {exc}",
            }],
        }

    # Registered webhook paths (hard-coded here — these are static per
    # router definition, so introspecting app.routes would just add
    # import cycles for zero benefit).
    registered_paths = [
        "/api/payments/stripe/webhook",     # primary
        "/api/stripe/webhook",              # legacy alias (same handler)
    ]

    # Recent events — up to 10 rows from the dedup ledger.
    recent_events: list = []
    try:
        cursor = db.stripe_webhook_events.find(
            {}, {"_id": 0, "event_id": 1, "event_type": 1,
                  "received_at": 1, "status": 1, "retry_count": 1,
                  "first_handled_at": 1, "last_error": 1,
                  "tenant_id_hint": 1},
        ).sort("received_at", -1).limit(10)
        recent_events = [row async for row in cursor]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[admin.stripe.webhook-diagnostic] ledger read failed: %s", exc)

    # Recent dead-letter rows — up to 5 unresolved.
    recent_dead_letters: list = []
    try:
        cursor = db.stripe_webhook_dead_letter.find(
            {"resolved": False},
            {"_id": 0, "event_id": 1, "event_type": 1,
              "first_failed_at": 1, "last_retry_at": 1,
              "error_class": 1, "error_message": 1,
              "retry_count_after_first": 1, "tenant_id_hint": 1},
        ).sort("first_failed_at", -1).limit(5)
        recent_dead_letters = [row async for row in cursor]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[admin.stripe.webhook-diagnostic] dead-letter read failed: %s", exc)

    # Suggested next action — single actionable string the UI shows.
    mm = report.get("mode_match")
    if mm in _MODE_MATCH_SUGGESTION:
        suggested = _MODE_MATCH_SUGGESTION[mm]
    elif report.get("issues"):
        # Have specific issue codes — point the admin at the first one.
        suggested = (
            f"{report['issues'][0]['code']}: {report['issues'][0]['message']}"
        )
    elif recent_dead_letters:
        suggested = (
            f"{len(recent_dead_letters)} unresolved dead-letter event(s). "
            "Replay via POST /api/admin/stripe/dead-letter/{event_id}/retry "
            "after fixing the underlying handler issue."
        )
    else:
        suggested = (
            "Configuration looks healthy. If webhooks still fail from the "
            "Stripe Dashboard, verify the Dashboard endpoint URL exactly "
            "matches one of the paths in registered_webhook_paths below."
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": now_iso,
        "registered_webhook_paths": registered_paths,
        "config": report,
        "recent_events_total": len(recent_events),
        "recent_events": recent_events,
        "recent_dead_letters_total": len(recent_dead_letters),
        "recent_dead_letters": recent_dead_letters,
        "suggested_next_action": suggested,
    }
