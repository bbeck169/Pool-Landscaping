"""Feb-2026 · P0/2 recurrence — comms diagnostic endpoints.

Read-only view of every comms-related env var boolean + the in-mem
last-send state maintained by ``services.comms_send_log``, plus a
POST test-send action to fire a real provider call marked
``diagnostic=True`` in the audit row.

All routes are admin-gated. Values that would leak an API key are
returned as booleans + short prefixes only.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from utils import require_admin
from services.comms_send_log import get_state, record_attempt, format_exc

router = APIRouter()


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _present(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def _prefix(name: str, n: int = 6) -> Optional[str]:
    v = (os.environ.get(name) or "").strip()
    return v[:n] if v else None


@router.get("/admin/comms-diagnostics")
async def comms_diagnostics(user: dict = Depends(require_admin)):
    """Env + state visibility for the ``*_TESTMODE_MOCK`` flags and
    provider credentials. Admin/super_admin only. Never returns the
    actual secret values.
    """
    state = get_state()
    return {
        "env": os.environ.get("APP_ENV") or None,
        # Testmode mocks (must ALL be False on prod).
        "messaging_testmode_mock": _truthy("MESSAGING_TESTMODE_MOCK"),
        "ai_testmode_mock":        _truthy("AI_TESTMODE_MOCK"),
        "calendars_testmode_mock": _truthy("CALENDARS_TESTMODE_MOCK"),
        "payments_testmode_mock":  _truthy("PAYMENTS_TESTMODE_MOCK"),
        "zillow_testmode_mock":    _truthy("ZILLOW_TESTMODE_MOCK"),
        # Companion flags asked-for by the diagnostic contract.
        "health_ready_integrity_check": _truthy("HEALTH_READY_INTEGRITY_CHECK"),
        "public_frontend_origin": os.environ.get("PUBLIC_FRONTEND_ORIGIN") or None,
        # Resend
        "resend_api_key_present": _present("RESEND_API_KEY"),
        "resend_api_key_prefix":  _prefix("RESEND_API_KEY", 6),
        "resend_from_email":      os.environ.get("EMAIL_FROM") or None,
        # RingCentral
        "ringcentral_client_id_present": _present("RC_CLIENT_ID"),
        "ringcentral_jwt_present":       _present("RC_JWT"),
        "ringcentral_env":               os.environ.get("RC_ENVIRONMENT") or None,
        # Last-send state (in-memory since boot; cleared on restart).
        "last_email_send_ok_at":    state.get("email", {}).get("last_ok_at"),
        "last_email_send_error":    state.get("email", {}).get("last_error"),
        "last_email_send_error_at": state.get("email", {}).get("last_error_at"),
        "last_email_provider_id":   state.get("email", {}).get("last_provider_id"),
        "last_sms_send_ok_at":      state.get("sms", {}).get("last_ok_at"),
        "last_sms_send_error":      state.get("sms", {}).get("last_error"),
        "last_sms_send_error_at":   state.get("sms", {}).get("last_error_at"),
        "last_sms_provider_id":     state.get("sms", {}).get("last_provider_id"),
    }


class _TestSendIn(BaseModel):
    channel: str  # "email" | "sms"
    to: str
    subject: Optional[str] = None
    body: Optional[str] = None


@router.post("/admin/comms-diagnostics/test")
async def comms_diagnostics_test(payload: _TestSendIn,
                                    user: dict = Depends(require_admin)):
    """Fire a real provider call. Diagnostic flag on the audit row so
    it can be filtered out of business reports. Never bypasses
    ``comms_env_guard`` or the testmode short-circuit — that's the
    whole point of the diagnostic.
    """
    channel = (payload.channel or "").strip().lower()
    if channel not in ("email", "sms"):
        raise HTTPException(400, "channel must be email or sms")
    if not (payload.to or "").strip():
        raise HTTPException(400, "recipient 'to' required")
    subject = payload.subject or "Comms diagnostic test"
    body = payload.body or "This is a comms diagnostic test from the CRM."
    tenant_id = user.get("tenant_id")

    if channel == "email":
        try:
            from services.comms_email_adapter import send_email
            res = await send_email(
                to_email=payload.to,
                subject=subject,
                html=f"<p>{body}</p>",
                tenant_id=tenant_id,
            )
            status = (res or {}).get("status")
            ok = status == "sent"
            record_attempt(
                "email", ok=ok,
                tenant_id=tenant_id, recipient=payload.to,
                template="_diagnostic_test",
                provider="resend",
                provider_status=status,
                provider_response_id=(res or {}).get("provider_id"),
                was_mock=str(status).startswith("mock"),
                routed_via=(res or {}).get("routed_via"),
                error=None if ok else str(res)[:500],
                diagnostic=True,
            )
            return {"ok": ok, "channel": "email", "provider_response": res}
        except Exception as e:
            record_attempt("email", ok=False,
                             tenant_id=tenant_id, recipient=payload.to,
                             template="_diagnostic_test", diagnostic=True,
                             **format_exc(e))
            raise HTTPException(500, f"email diagnostic failed: {e}")

    # channel == "sms"
    try:
        from services.sms.rc_adapter import send as _sms_send
        res = await _sms_send(
            to=payload.to, body=body,
            category="transactional",
            tenant_id=tenant_id,
        )
        provider = (res or {}).get("provider")
        status = (res or {}).get("provider_status")
        ok = (provider == "ringcentral"
              and status in ("queued", "sent", "delivered", "accepted"))
        record_attempt(
            "sms", ok=ok,
            tenant_id=tenant_id, recipient=payload.to,
            template="_diagnostic_test",
            provider=provider, provider_status=status,
            provider_response_id=(res or {}).get("provider_response_id"),
            was_mock=(provider == "mock"),
            routed_via=(res or {}).get("routed_via"),
            error=None if ok else str(res)[:500],
            diagnostic=True,
        )
        return {"ok": ok, "channel": "sms", "provider_response": res}
    except Exception as e:
        record_attempt("sms", ok=False,
                         tenant_id=tenant_id, recipient=payload.to,
                         template="_diagnostic_test", diagnostic=True,
                         **format_exc(e))
        raise HTTPException(500, f"sms diagnostic failed: {e}")
