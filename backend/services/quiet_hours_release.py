"""Feb-2026 · P34 — Quiet-hours deferred-send release worker.

Runs on a 5-minute APScheduler interval (see ``server.py`` boot).
Every tick:

  1. Atomically claim up to ``BATCH_LIMIT`` pending rows in
     ``outbound_deferred`` whose ``scheduled_for <= now(UTC)``.
     Claim flips ``status`` from ``pending`` → ``releasing`` so a
     concurrent worker cannot double-send.
  2. For each claimed row, dispatch via the same adapter that
     originally deferred it (email → :func:`comms_email_adapter.send_email`,
     sms → :func:`comms_sms_adapter.send_sms`), BYPASSING the quiet-hours
     gate this time by calling the underlying send path directly.
  3. Mark the row ``sent`` (with provider_id) or ``failed``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from config import db, logger
from services.quiet_hours import claim_pending_batch
from utils import now_iso


BATCH_LIMIT = 200


def _now_utc_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


async def _dispatch_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a single claimed row. Bypasses the quiet-hours gate
    (we're already past the window) by calling into the same adapter
    with an environment sentinel that the adapter can check — but the
    cleaner route is to call the RESEND / RingCentral primitives
    directly, mirroring the adapter's happy path."""
    tenant_id = row.get("tenant_id")
    channel = row.get("channel")
    payload = row.get("payload") or {}

    # The simplest correct thing: temporarily flip the tenant into
    # "quiet_hours_disabled" for the duration of this single call is
    # unsafe (races with other requests). Instead, call the adapter
    # and let its is_within_send_window() re-check succeed because
    # we ONLY release rows whose scheduled_for has already passed —
    # by definition their window is open right now (or the tenant
    # config changed). If the tenant re-closed the window between
    # ``scheduled_for`` and ``now``, we still release: the operator
    # accepted the deferral and shouldn't get double-deferrals.
    #
    # To bypass a re-defer loop, we call the adapter with a special
    # marker on the payload the adapters look for.
    try:
        from services.quiet_hours_context import bypass_gate
        with bypass_gate():
            if channel == "email":
                from services.comms_email_adapter import send_email as _se
                res = await _se(
                    tenant_id=tenant_id,
                    to_email=payload.get("to_email"),
                    subject=payload.get("subject", ""),
                    html=payload.get("html", ""),
                    from_name=payload.get("from_name"),
                    from_email=payload.get("from_email"),
                    headers=payload.get("headers"),
                )
            elif channel == "sms":
                from services.comms_sms_adapter import send_sms as _ss
                res = await _ss(
                    tenant_id=tenant_id,
                    to_phone=payload.get("to_phone"),
                    body=payload.get("body", ""),
                    mms_url=payload.get("mms_url"),
                )
            else:
                return {"status": "failed", "error": f"unknown channel {channel!r}"}
        return res
    except Exception as e:
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"}


async def run_release_tick() -> Dict[str, int]:
    """Single tick of the release worker. Safe to call concurrently
    (individual row claim is atomic). Returns counts."""
    claimed = await claim_pending_batch(_now_utc_iso(), limit=BATCH_LIMIT)
    n_sent = 0
    n_failed = 0
    for row in claimed:
        result = await _dispatch_row(row)
        status = "sent" if result.get("status") in ("sent", "mocked", "deferred") else "failed"
        # Deferred-during-release is treated as sent for accounting
        # purposes — the adapter's re-defer will handle the follow-up
        # send when the window opens again.
        if status == "sent":
            n_sent += 1
        else:
            n_failed += 1
        await db.outbound_deferred.update_one(
            {"id": row["id"]},
            {"$set": {
                "status": status,
                "released_at": now_iso(),
                "provider_id": result.get("provider_id"),
                "release_result": {k: v for k, v in result.items()
                                        if k in ("status", "error", "provider_id")},
            }},
        )
    if claimed:
        logger.info("[p34] release tick: claimed=%s sent=%s failed=%s",
                        len(claimed), n_sent, n_failed)
    return {"claimed": len(claimed), "sent": n_sent, "failed": n_failed}
