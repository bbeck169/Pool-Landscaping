"""Phase I1.7.b · Feb-2026 — Resend email provider (tenant-scoped)."""
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


log = logging.getLogger("messaging.email.resend")
_RESEND_BASE = "https://api.resend.com"


class ResendEmailProvider(EmailProvider):
    provider_key = "resend"
    primary_secret_field = "api_key"

    config_fields: Dict[str, Dict[str, Any]] = {
        "api_key":     {"required": True, "secret": True,  "label": "Resend API key"},
        "from_addr":   {"required": True, "secret": False, "label": "Default From address"},
        "from_name":   {"required": False, "secret": False, "label": "From display name (optional)"},
        "webhook_secret": {"required": False, "secret": True, "label": "Webhook signing secret (optional)"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=15.0)

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantMessagingNotConnected(f"Tenant {tenant_id} has no Resend config")
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
                id=f"resend_test_{uuid.uuid4().hex[:20]}",
                status="queued", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        cfg = await self._cfg(tenant_id)
        addr = from_addr or cfg["from_addr"]
        if cfg.get("from_name"):
            addr = f"{cfg['from_name']} <{addr}>"
        payload: Dict[str, Any] = {"from": addr, "to": to, "subject": subject}
        if html_body: payload["html"] = html_body
        if text_body: payload["text"] = text_body
        if reply_to: payload["reply_to"] = reply_to
        if attachments:
            payload["attachments"] = [
                {"filename": a.filename, "content": a.content_b64} for a in attachments
            ]
        client = await self._client()
        try:
            r = await client.post(
                f"{_RESEND_BASE}/emails",
                json=payload,
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"RESEND_{r.status_code}",
                    message=f"send_email HTTP {r.status_code}",
                )
                return EmailResult(
                    id="", status="failed", to=to,
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    raw=j, error=f"resend HTTP {r.status_code}",
                )
            await mark_used(tenant_id, self.provider_key)
            return EmailResult(
                id=str(j.get("id") or ""),
                status="queued", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw=j,
            )
        except Exception as e:
            log.warning("resend send_email failed: %s", type(e).__name__)
            await log_secret_error(tenant_id, self.provider_key,
                                     code="RESEND_EXCEPTION",
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
        if email_testmode_mock():
            return EmailStatus(id=message_id, status="delivered",
                                provider_key=self.provider_key, tenant_id=tenant_id,
                                raw={"mock": True})
        cfg = await self._cfg(tenant_id)
        client = await self._client()
        try:
            r = await client.get(
                f"{_RESEND_BASE}/emails/{message_id}",
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
            )
            j = r.json() if r.content else {}
            return EmailStatus(
                id=message_id,
                status=(j.get("last_event") or j.get("status") or "unknown"),
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw=j,
            )
        finally:
            if self._http is None:
                await client.aclose()

    async def verify_webhook(
        self, *, payload: bytes, headers: Dict[str, str],
    ) -> EmailInboundEvent:
        import json
        try:
            data = json.loads(payload.decode() if isinstance(payload, (bytes, bytearray)) else payload)
            return EmailInboundEvent(
                id=str(data.get("id", uuid.uuid4().hex)),
                event_type=data.get("type", "unknown"),
                message_id=(data.get("data") or {}).get("email_id"),
                recipient=(data.get("data") or {}).get("to", [None])[0]
                    if isinstance((data.get("data") or {}).get("to"), list) else None,
                provider_key=self.provider_key, tenant_id=None,
                raw=data,
            )
        except Exception as e:
            raise MessagingError(f"resend webhook parse failed: {type(e).__name__}") from e

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No Resend config saved for this tenant.",
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
                f"{_RESEND_BASE}/domains",
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
            )
            if r.status_code < 400:
                return ConnectionHealth(
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    ok=True, message="Resend domains.list OK.",
                    checked_at=now_iso(),
                )
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Resend probe HTTP {r.status_code}",
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Resend probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
