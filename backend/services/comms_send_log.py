"""Feb-2026 · P0/2 recurrence — comms send audit log.

Lightweight best-effort logger used by the two most-hit outbound
adapters (``utils.send_sms`` → RingCentral, and
``services.comms_email_adapter.send_email`` → Resend) so that every
outbound attempt writes a row to ``db.comms_send_log`` with:

* timestamp / tenant_id / channel / recipient (redacted) / template
* provider status / provider response id / mock flag
* exception trace on failure

Also exposes cheap in-memory ``last_ok`` / ``last_error`` accessors
the diagnostic endpoint reads to render "last email send OK at" /
"last email send error" without paging through the collection on
every probe.

Never raises. Never blocks the caller. Failures inside the logger
are swallowed with a WARNING to preserve the caller-side contract.
"""
from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import logger

_STATE: Dict[str, Dict[str, Any]] = {
    "email": {"last_ok_at": None, "last_error_at": None,
              "last_error": None, "last_provider_id": None},
    "sms":   {"last_ok_at": None, "last_error_at": None,
              "last_error": None, "last_provider_id": None},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(v: Optional[str]) -> Optional[str]:
    """Redact a recipient for log storage. Keeps enough shape for
    debugging without leaking the full PII.

    SAFE-SEND-A.1 · Feb-2026 — added phone-aware branch.
    E.164 numbers (leading ``+``, all digits, length 8..16) are
    redacted as ``+1555***4567`` — first 5 chars (country + area)
    plus last 4 (subscriber tail) with the middle digits starred.
    Non-E.164 phones fall to the generic tail-preserving branch
    below.  Emails go through the existing local-part redaction.
    Behaviour for emails is BYTE-IDENTICAL to pre-A.1.
    """
    if not v:
        return v
    s = str(v)
    if "@" in s:
        local, _, dom = s.partition("@")
        keep = 2
        redacted_local = local[:keep] + ("*" * max(0, len(local) - keep))
        return f"{redacted_local}@{dom}"
    # E.164 phone detection: leading '+', digits only after, len 8..16.
    # Preserves country + area code (first 5 chars, e.g. ``+1555``)
    # and the last 4 (subscriber tail) — middle digits starred.
    if (s.startswith("+") and s[1:].isdigit()
            and 8 <= len(s) <= 16):
        star_count = max(0, len(s) - 9)  # 5 leading + 4 trailing kept.
        return s[:5] + ("*" * star_count) + s[-4:]
    if len(s) <= 4:
        return "*" * len(s)
    return s[:2] + ("*" * (len(s) - 6)) + s[-4:]


def get_state() -> Dict[str, Dict[str, Any]]:
    """Read-only snapshot for the diagnostic endpoint."""
    return {k: dict(v) for k, v in _STATE.items()}


def record_attempt(
    channel: str, *,
    ok: bool,
    tenant_id: Optional[str] = None,
    recipient: Optional[str] = None,
    template: Optional[str] = None,
    provider: Optional[str] = None,
    provider_status: Optional[str] = None,
    provider_response_id: Optional[str] = None,
    was_mock: bool = False,
    error: Optional[str] = None,
    exc_type: Optional[str] = None,
    exc_trace: Optional[str] = None,
    routed_via: Optional[str] = None,
    diagnostic: bool = False,
    # SAFE-SEND-A · Feb-2026 — send-time provenance + redirect audit.
    # ``context`` is the ``CommsContext`` enum ``.value`` (str) that
    # the adapter stamped on the call.  ``intended_recipient`` is the
    # address the CALLER handed to ``send_email`` / ``send_sms`` —
    # verbatim, no redaction yet (we redact before store).  ``redirected``
    # is ``True`` when ``intended_recipient != recipient`` (i.e. the
    # SAFE-SEND-A redirect fired).  Preserved on EVERY audit row —
    # regardless of channel, success, mock, or gate outcome — so ops
    # can always answer "where did this send actually go, and where
    # did the caller try to send it?".
    context: Optional[str] = None,
    intended_recipient: Optional[str] = None,
    redirected: bool = False,
) -> None:
    """Fire-and-forget best-effort audit. Never raises."""
    now = _now_iso()
    if channel not in _STATE:
        _STATE[channel] = {"last_ok_at": None, "last_error_at": None,
                             "last_error": None, "last_provider_id": None}
    if ok:
        _STATE[channel]["last_ok_at"] = now
        _STATE[channel]["last_provider_id"] = provider_response_id
    else:
        _STATE[channel]["last_error_at"] = now
        _STATE[channel]["last_error"] = (error or "")[:500]

    row = _build_audit_row(
        channel=channel, ok=ok, now=now,
        tenant_id=tenant_id, recipient=recipient, template=template,
        provider=provider, provider_status=provider_status,
        provider_response_id=provider_response_id, was_mock=was_mock,
        error=error, exc_type=exc_type, exc_trace=exc_trace,
        routed_via=routed_via, diagnostic=diagnostic,
        context=context, intended_recipient=intended_recipient,
        redirected=redirected,
    )

    async def _write():
        try:
            from server import db  # lazy — server imports late
            await db.comms_send_log.insert_one(row)
        except Exception as e:  # pragma: no cover
            logger.warning(f"[comms_send_log] insert failed: {e}")

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_write())
    except RuntimeError:
        # No running loop (sync-fire callers). Spin a tiny one so we
        # still persist the row; total budget < 30ms in the common
        # motor path.
        try:
            asyncio.run(_write())
        except Exception as e:  # pragma: no cover
            logger.warning(f"[comms_send_log] sync-fallback failed: {e}")


def _build_audit_row(
    *,
    channel: str,
    ok: bool,
    now: str,
    tenant_id: Optional[str],
    recipient: Optional[str],
    template: Optional[str],
    provider: Optional[str],
    provider_status: Optional[str],
    provider_response_id: Optional[str],
    was_mock: bool,
    error: Optional[str],
    exc_type: Optional[str],
    exc_trace: Optional[str],
    routed_via: Optional[str],
    diagnostic: bool,
    context: Optional[str],
    intended_recipient: Optional[str],
    redirected: bool,
) -> Dict[str, Any]:
    """SAFE-SEND-A · pure builder for the audit row shape.

    Extracted so unit tests can assert on the exact fields written
    to ``comms_send_log`` without needing to fake Motor / server
    lazy imports.  The runtime path in ``record_attempt`` calls
    this then hands the dict to Motor; the shape is contractual.
    """
    return {
        "at": now, "channel": channel, "ok": bool(ok),
        "tenant_id": tenant_id,
        "recipient_redacted": _redact(recipient),
        "template": template, "provider": provider,
        "provider_status": provider_status,
        "provider_response_id": provider_response_id,
        "was_mock": bool(was_mock),
        "routed_via": routed_via,
        "diagnostic": bool(diagnostic),
        "error": (error or None) if not ok else None,
        "exc_type": exc_type, "exc_trace": (exc_trace or "")[:2000] or None,
        # SAFE-SEND-A audit fields — always present on every row.
        "context": context,
        "intended_recipient_redacted": _redact(intended_recipient),
        "redirected": bool(redirected),
    }


def format_exc(exc: BaseException) -> Dict[str, str]:
    return {
        "error": f"{type(exc).__name__}: {exc}",
        "exc_type": type(exc).__name__,
        "exc_trace": "".join(traceback.format_exception(
            type(exc), exc, exc.__traceback__,
        )),
    }
