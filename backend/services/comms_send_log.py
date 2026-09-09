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
    debugging without leaking the full PII."""
    if not v:
        return v
    s = str(v)
    if "@" in s:
        local, _, dom = s.partition("@")
        keep = 2
        redacted_local = local[:keep] + ("*" * max(0, len(local) - keep))
        return f"{redacted_local}@{dom}"
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

    row = {
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
    }

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


def format_exc(exc: BaseException) -> Dict[str, str]:
    return {
        "error": f"{type(exc).__name__}: {exc}",
        "exc_type": type(exc).__name__,
        "exc_trace": "".join(traceback.format_exception(
            type(exc), exc, exc.__traceback__,
        )),
    }
