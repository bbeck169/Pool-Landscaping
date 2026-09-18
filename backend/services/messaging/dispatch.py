"""Phase I1.7.b · Feb-2026 — Tenant-first messaging dispatch shim.

Routes SMS + email sends through the tenant's configured provider if
one is saved, otherwise falls back to the platform default
(``comms_sms_adapter`` / ``comms_email_adapter``) and appends an
audit entry to ``platform_messaging_fallback_log``.

Callers should ideally migrate to this dispatch layer; existing
adapters keep working unchanged.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from ._helpers import fallback_enabled, now_iso
from .email.registry import get_tenant_email_provider
from .models import EmailAttachment
from .sms.registry import get_tenant_sms_provider


log = logging.getLogger("messaging.dispatch")

FALLBACK_LOG_COLLECTION = "platform_messaging_fallback_log"


async def _log_fallback(*, tenant_id: str, kind: str, reason: str, db=None) -> None:
    if db is None:
        from config import db as _db
        db = _db
    try:
        await db[FALLBACK_LOG_COLLECTION].insert_one({
            "id": uuid.uuid4().hex,
            "tenant_id": tenant_id,
            "kind": kind,             # "sms" | "email"
            "reason": reason,          # e.g. "no_tenant_provider"
            "at": now_iso(),
        })
    except Exception:  # pragma: no cover
        pass


async def dispatch_sms(
    *, tenant_id: str, to: str, body: str,
    media_urls: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db=None,
) -> Dict[str, Any]:
    """Send an SMS via the tenant's provider if configured, else the
    platform default. Return value shape mirrors
    ``comms_sms_adapter.send_sms`` for drop-in compatibility."""
    provider = await get_tenant_sms_provider(tenant_id, db=db)
    if provider is not None:
        result = await provider.send_sms(
            tenant_id=tenant_id, to=to, body=body,
            media_urls=media_urls, metadata=metadata,
        )
        return {
            "status": result.status if result.status not in ("failed",) else "failed",
            "provider_id": result.id,
            "provider_key": result.provider_key,
            "raw": result.raw,
            "error": result.error,
        }
    # Platform fallback path.
    if not fallback_enabled():
        return {"status": "failed",
                "error": "no tenant SMS provider and platform fallback disabled",
                "provider_id": None}
    await _log_fallback(tenant_id=tenant_id, kind="sms",
                         reason="no_tenant_provider", db=db)
    from services.comms_sms_adapter import send_sms as _platform_send
    mms_url = (media_urls or [None])[0]
    return await _platform_send(tenant_id, to, body, mms_url)


async def dispatch_email(
    *, tenant_id: str, to: List[str], subject: str,
    html_body: Optional[str] = None,
    text_body: Optional[str] = None,
    from_addr: Optional[str] = None,
    from_name: Optional[str] = None,
    attachments: Optional[List[EmailAttachment]] = None,
    reply_to: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db=None,
) -> Dict[str, Any]:
    """Send an email via the tenant's provider if configured, else the
    platform default."""
    provider = await get_tenant_email_provider(tenant_id, db=db)
    if provider is not None:
        result = await provider.send_email(
            tenant_id=tenant_id, to=to, subject=subject,
            html_body=html_body, text_body=text_body,
            from_addr=from_addr, from_name=from_name,
            attachments=attachments,
            reply_to=reply_to, metadata=metadata,
        )
        return {
            "status": result.status if result.status not in ("failed",) else "failed",
            "provider_id": result.id,
            "provider_key": result.provider_key,
            "raw": result.raw,
            "error": result.error,
        }
    if not fallback_enabled():
        return {"status": "failed",
                "error": "no tenant email provider and platform fallback disabled",
                "provider_id": None}
    await _log_fallback(tenant_id=tenant_id, kind="email",
                         reason="no_tenant_provider", db=db)
    from services.comms_email_adapter import send_email as _platform_send
    # Legacy adapter takes a single ``to`` string + html; degrade for
    # multi-recipient calls by fanning out.
    if len(to) == 1:
        return await _platform_send(
            tenant_id, to[0], subject, html_body or "",
            from_name=from_name, from_email=from_addr,
        )
    results = []
    for recipient in to:
        r = await _platform_send(
            tenant_id, recipient, subject, html_body or "",
            from_name=from_name, from_email=from_addr,
        )
        results.append(r)
    # Roll up — return the first non-success status or the last success.
    for r in results:
        if r.get("status") != "sent":
            return r
    return results[-1] if results else {"status": "failed", "error": "no recipients"}
