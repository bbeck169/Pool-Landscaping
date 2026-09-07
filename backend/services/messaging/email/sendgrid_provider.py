"""Phase I1.7.b · Feb-2026 — SendGrid email provider (tenant-scoped)."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

import httpx

from services.secrets import log_error as log_secret_error, mark_used

from .._helpers import email_testmode_mock, load_provider_config, now_iso
from ..models import (
    ConnectionHealth,
    EmailAttachment,
    EmailInboundEvent,
    EmailResult,
    EmailStatus,
    MessagingError,
    TenantMessagingNotConnected,
)
from .base import EmailProvider


log = logging.getLogger("messaging.email.sendgrid")
_SG_BASE = "https://api.sendgrid.com/v3"


class SendGridEmailProvider(EmailProvider):
    provider_key = "sendgrid"
    primary_secret_field = "api_key"

    config_fields: Dict[str, Dict[str, Any]] = {
        "api_key":     {"required": True, "secret": True,  "label": "SendGrid API key"},
        "from_addr":   {"required": True, "secret": False, "label": "Verified sender address"},
        "from_name":   {"required": False, "secret": False, "label": "From display name"},
        "webhook_public_key": {"required": False, "secret": True, "label": "Event webhook verification key"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=15.0)

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantMessagingNotConnected(f"Tenant {tenant_id} has no SendGrid config")
        return cfg

    async def send_email(
        self, *, tenant_id: str, to: List[str], subject: str,
        html_body: Optional[str] = None, text_body: Optional[str] = None,
        from_addr: Optional[str] = None,
        attachments: Optional[List[EmailAttachment]] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EmailResult:
        if email_testmode_mock():
            return EmailResult(
                id=f"sg_test_{uuid.uuid4().hex[:20]}",
                status="queued", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        cfg = await self._cfg(tenant_id)
        contents = []
        if text_body: contents.append({"type": "text/plain", "value": text_body})
        if html_body: contents.append({"type": "text/html", "value": html_body})
        if not contents:
            contents.append({"type": "text/plain", "value": ""})
        payload: Dict[str, Any] = {
            "personalizations": [{"to": [{"email": e} for e in to]}],
            "from": {"email": from_addr or cfg["from_addr"], "name": cfg.get("from_name")},
            "subject": subject,
            "content": contents,
        }
        if reply_to:
            payload["reply_to"] = {"email": reply_to}
        if attachments:
            payload["attachments"] = [
                {"filename": a.filename, "content": a.content_b64,
                 "type": a.content_type} for a in attachments
            ]
        client = await self._client()
        try:
            r = await client.post(
                f"{_SG_BASE}/mail/send",
                json=payload,
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
            )
            if r.status_code >= 400:
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"SENDGRID_{r.status_code}",
                    message=f"send_email HTTP {r.status_code}",
                )
                return EmailResult(
                    id="", status="failed", to=to,
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    raw={"status_code": r.status_code},
                    error=f"sendgrid HTTP {r.status_code}",
                )
            # SendGrid returns X-Message-Id header on success.
            msg_id = r.headers.get("X-Message-Id", "")
            await mark_used(tenant_id, self.provider_key)
            return EmailResult(
                id=msg_id, status="queued", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"headers": dict(r.headers)},
            )
        except Exception as e:
            log.warning("sendgrid send_email failed: %s", type(e).__name__)
            await log_secret_error(tenant_id, self.provider_key,
                                     code="SENDGRID_EXCEPTION",
                                     message=type(e).__name__)
            return EmailResult(
                id="", status="failed", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={}, error=type(e).__name__,
            )
        finally:
            if self._http is None:
                await client.aclose()

    async def get_status(self, *, tenant_id: str, message_id: str) -> EmailStatus:
        # SendGrid has no simple GET; consumers rely on webhooks. Return a
        # neutral response so callers don't loop.
        return EmailStatus(id=message_id, status="unknown",
                            provider_key=self.provider_key, tenant_id=tenant_id,
                            raw={"note": "sendgrid delivery status is webhook-only"})

    async def verify_webhook(
        self, *, payload: bytes, headers: Dict[str, str],
    ) -> EmailInboundEvent:
        import json
        try:
            events = json.loads(payload.decode() if isinstance(payload, (bytes, bytearray)) else payload)
            first = events[0] if isinstance(events, list) and events else {}
            return EmailInboundEvent(
                id=str(first.get("sg_message_id", uuid.uuid4().hex)),
                event_type=first.get("event", "unknown"),
                message_id=first.get("sg_message_id"),
                recipient=first.get("email"),
                provider_key=self.provider_key, tenant_id=None,
                raw={"events": events},
            )
        except Exception as e:
            raise MessagingError(f"sendgrid webhook parse failed: {type(e).__name__}") from e

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No SendGrid config saved for this tenant.",
                checked_at=now_iso(),
            )
        if email_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="mock", checked_at=now_iso(),
            )
        client = await self._client()
        try:
            r = await client.get(
                f"{_SG_BASE}/scopes",
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
            )
            if r.status_code < 400:
                return ConnectionHealth(
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    ok=True, message="SendGrid scopes.get OK.",
                    checked_at=now_iso(),
                )
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"SendGrid probe HTTP {r.status_code}",
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"SendGrid probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
