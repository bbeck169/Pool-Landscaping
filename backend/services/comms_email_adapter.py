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
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Send an email via Resend. Never raises."""
    if not to_email:
        return {"status": "failed", "error": "empty recipient email"}
    if await _is_opted_out(tenant_id, to_email):
        return {"status": "skipped_opted_out"}

    key = os.environ.get("RESEND_API_KEY")
    if not key:
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

    try:
        import resend  # type: ignore
        resend.api_key = key
        resp = resend.Emails.send(payload)
        provider_id = None
        if isinstance(resp, dict):
            provider_id = resp.get("id")
        return {"status": "sent", "provider_id": provider_id}
    except Exception as e:
        logger.warning(f"comms_email_adapter: resend send failed: {type(e).__name__}: {e}")
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"}
