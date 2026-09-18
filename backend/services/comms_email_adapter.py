"""Communications Subsystem · Phase 1 — Email delivery adapter (Resend).

Thin wrapper over the same Resend client used by ``services/weekly_digest``,
``services/pool_service_email``, etc. All this adapter adds is:

- Opt-out check FIRST (queries ``communication_opt_outs``); short-circuits
  with ``status="skipped_opted_out"`` if the recipient has opted out on the
  ``email`` channel for this tenant.
- Uniform status enum used by the ``communication_sends`` log:
  ``sent``, ``failed``, ``not_sent_missing_key``, ``skipped_opted_out``.
- Never raises. Delivery failures return ``{"status":"failed", ...}``.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from config import db, logger
from services.comms_send_log import record_attempt, format_exc


async def _is_opted_out(tenant_id: str, email: str) -> bool:
    if not email:
        return False
    row = await db.communication_opt_outs.find_one({
        "tenant_id": tenant_id,
        "contact_email": email.lower(),
        "channel": "email",
    })
    return row is not None


async def send_email(tenant_id: str, to_email: str, subject: str, html: str,
                     from_name: Optional[str] = None,
                     from_email: Optional[str] = None,
                     headers: Optional[Dict[str, str]] = None,
                     attachments: Optional[list] = None) -> Dict[str, Any]:
    """Send an email via Resend. Never raises.

    Feb-2026 · Customer-Attachments (Option D) — optional
    ``attachments`` accepts a list of Resend-shaped dicts
    ``{filename, content_type, content_base64}``. Resend's Python
    SDK expects the base64 payload under ``content`` (not
    ``content_base64``); we remap right before the SDK call so
    the internal API stays semantic.
    """
    if not to_email:
        return {"status": "failed", "error": "empty recipient email"}
    if await _is_opted_out(tenant_id, to_email):
        return {"status": "skipped_opted_out"}

    # Feb-2026 · P34 — Automation quiet-hours gate. If the tenant has
    # enabled quiet hours and ``now`` is outside the window, persist
    # this send into ``outbound_deferred`` for the release worker to
    # dispatch when the window re-opens. Any failure here fails open
    # so we never silently drop mail on a gate bug.
    try:
        from services.quiet_hours import (
            is_within_send_window as _p34_ok,
            defer_send as _p34_defer,
        )
        from services.quiet_hours_context import is_bypassing as _p34_bypass
        if not _p34_bypass() and not await _p34_ok(tenant_id):
            deferred_id = await _p34_defer(
                tenant_id, "email",
                {"to_email": to_email, "subject": subject, "html": html,
                  "from_name": from_name, "from_email": from_email,
                  "headers": headers},
            )
            return {"status": "deferred",
                     "deferred_id": deferred_id, "provider_id": None}
    except Exception as _e34:
        logger.warning("[p34] quiet-hours gate errored — failing open: %s",
                          _e34)

    # Phase I1.7.e · chunk 1 · Feb-2026 — tenant-BYO first hop.
    # If the tenant has a BYO email provider configured, route the
    # send through it. Cap-exceeded (HTTP 429) responses are normalized
    # into ``status="cap_exceeded"`` so the transactional caller can
    # translate to HTTPException(429) and the bulk caller can persist
    # ``skipped_cap_exceeded`` in its delivery ledger. Never raises;
    # returns ``None`` when no tenant provider is configured and the
    # caller should proceed with the platform send path below.
    try:
        from services.messaging.byo_passthrough import (
            try_dispatch_email_tenant_byo,
        )
        _byo = await try_dispatch_email_tenant_byo(
            tenant_id=tenant_id, to=to_email, subject=subject,
            html=html, from_addr=from_email, from_name=from_name,
            attachments=attachments,
        )
    except Exception as _byo_exc:  # noqa: BLE001
        logger.warning(
            "comms_email_adapter: BYO probe raised — falling through: %s",
            _byo_exc,
        )
        _byo = None
    if _byo is not None:
        return _byo

    # Phase I1.7.e · Feb-2026 — MESSAGING_TESTMODE_MOCK short-circuit
    # for the platform (non-BYO) path. Runs AFTER opt-out + BYO probe
    # so both gates still fire; only the outbound Resend HTTP call is
    # skipped. Deterministic envelope keyed on (tenant, to, subject).
    from services.messaging.testmode import (
        is_messaging_testmode, mock_email_envelope,
    )
    if is_messaging_testmode():
        return mock_email_envelope(
            tenant_id=tenant_id, to=to_email, subject=subject,
            routed_via="platform_testmode_mock",
        )

    key = os.environ.get("RESEND_API_KEY")
    if not key:
        record_attempt(
            "email", ok=False, tenant_id=tenant_id, recipient=to_email,
            template=(headers or {}).get("X-Template") if headers else None,
            provider="resend", provider_status="not_sent_missing_key",
            was_mock=False, routed_via="platform_resend",
            error="RESEND_API_KEY missing on this pod",
        )
        return {"status": "not_sent_missing_key"}

    _from = from_email or os.environ.get("RESEND_FROM", "onboarding@resend.dev")
    if from_name:
        _from = f"{from_name} <{_from}>"

    payload: Dict[str, Any] = {
        "from": _from,
        "to": [to_email],
        "subject": subject or "",
        "html": html or "",
    }
    if headers:
        payload["headers"] = headers
    # Feb-2026 · Customer-Attachments (Option D). Resend's Python SDK
    # accepts attachments as ``[{filename, content, content_type}]``
    # where ``content`` is the base64 string.
    if attachments:
        payload["attachments"] = [
            {
                "filename":      a.get("filename") or "attachment.bin",
                "content":       a.get("content_base64") or "",
                "content_type":  a.get("content_type") or "application/octet-stream",
            }
            for a in attachments
        ]

    # Feb-2026 · Comms whitelist gate (P0 safety directive).
    try:
        from services.comms.gate import is_comm_allowed
        allowed = await is_comm_allowed(
            recipient_identifier=to_email,
            comm_type="email",
            tenant_id=tenant_id,
            provider="resend",
            trigger_action="comms_email_adapter",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"comms_email_adapter: gate errored — failing closed: {e}")
        allowed = False
    if not allowed:
        record_attempt(
            "email", ok=False, tenant_id=tenant_id, recipient=to_email,
            template=(headers or {}).get("X-Template") if headers else None,
            provider="resend", provider_status="suppressed_not_demo",
            was_mock=False, routed_via="platform_resend_gate",
            error="Blocked by services.comms.gate.is_comm_allowed",
        )
        return {"status": "suppressed_not_demo", "provider_id": None}

    try:
        import resend  # type: ignore
        resend.api_key = key
        resp = resend.Emails.send(payload)
        provider_id = None
        if isinstance(resp, dict):
            provider_id = resp.get("id")
        record_attempt(
            "email", ok=True, tenant_id=tenant_id, recipient=to_email,
            template=(headers or {}).get("X-Template") if headers else None,
            provider="resend", provider_status="sent",
            provider_response_id=provider_id, was_mock=False,
            routed_via="platform_resend",
        )
        return {"status": "sent", "provider_id": provider_id}
    except Exception as e:
        logger.warning(f"comms_email_adapter: resend send failed: {type(e).__name__}: {e}")
        record_attempt(
            "email", ok=False, tenant_id=tenant_id, recipient=to_email,
            template=(headers or {}).get("X-Template") if headers else None,
            provider="resend", provider_status="failed",
            was_mock=False, routed_via="platform_resend",
            **format_exc(e),
        )
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"}
