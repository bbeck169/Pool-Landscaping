"""Phase I1.7.b · Feb-2026 — Mailgun email provider (tenant-scoped)."""
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


log = logging.getLogger("messaging.email.mailgun")


class MailgunEmailProvider(EmailProvider):
    provider_key = "mailgun"

    config_fields: Dict[str, Dict[str, Any]] = {
        "api_key":     {"required": True, "secret": True,  "label": "Mailgun API key"},
        "domain":      {"required": True, "secret": False, "label": "Sending domain (e.g. mg.example.com)"},
        "from_addr":   {"required": True, "secret": False, "label": "Default From address"},
        "region":      {"required": False, "secret": False, "label": "Region (us|eu — default us)"},
        "webhook_signing_key": {"required": False, "secret": True, "label": "Webhook signing key"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client

    def _base(self, cfg: Dict[str, Any]) -> str:
        region = (cfg.get("region") or "us").lower()
        return "https://api.eu.mailgun.net/v3" if region == "eu" else "https://api.mailgun.net/v3"

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=15.0)

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantMessagingNotConnected(f"Tenant {tenant_id} has no Mailgun config")
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
                id=f"mg_test_{uuid.uuid4().hex[:20]}",
                status="queued", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        cfg = await self._cfg(tenant_id)
        data: List[Any] = [
            ("from", from_addr or cfg["from_addr"]),
            ("subject", subject),
        ]
        for e in to:
            data.append(("to", e))
        if html_body: data.append(("html", html_body))
        if text_body: data.append(("text", text_body))
        if reply_to:  data.append(("h:Reply-To", reply_to))
        files = []
        if attachments:
            import base64
            for a in attachments:
                files.append(("attachment", (a.filename, base64.b64decode(a.content_b64), a.content_type)))
        client = await self._client()
        try:
            r = await client.post(
                f"{self._base(cfg)}/{cfg['domain']}/messages",
                data=data, files=files or None,
                auth=("api", cfg["api_key"]),
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"MAILGUN_{r.status_code}",
                    message=f"send_email HTTP {r.status_code}",
                )
                return EmailResult(
                    id="", status="failed", to=to,
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    raw=j, error=f"mailgun HTTP {r.status_code}",
                )
            await mark_used(tenant_id, self.provider_key)
            return EmailResult(
                id=str(j.get("id") or ""),
                status="queued", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw=j,
            )
        except Exception as e:
            log.warning("mailgun send_email failed: %s", type(e).__name__)
            await log_secret_error(tenant_id, self.provider_key,
                                     code="MAILGUN_EXCEPTION",
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
        # Mailgun's message-events API needs a domain scope + storage
        # token; delivery status is best surfaced via the events
        # webhook. Return a neutral response.
        return EmailStatus(id=message_id, status="unknown",
                            provider_key=self.provider_key, tenant_id=tenant_id,
                            raw={"note": "mailgun delivery status is webhook-only"})

    async def verify_webhook(
        self, *, payload: bytes, headers: Dict[str, str],
    ) -> EmailInboundEvent:
        import json
        try:
            data = json.loads(payload.decode() if isinstance(payload, (bytes, bytearray)) else payload)
            event = (data.get("event-data") or {})
            return EmailInboundEvent(
                id=str(event.get("id") or uuid.uuid4().hex),
                event_type=(event.get("event") or "unknown").lower(),
                message_id=(event.get("message") or {}).get("headers", {}).get("message-id"),
                recipient=event.get("recipient"),
                provider_key=self.provider_key, tenant_id=None,
                raw=data,
            )
        except Exception as e:
            raise MessagingError(f"mailgun webhook parse failed: {type(e).__name__}") from e

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No Mailgun config saved for this tenant.",
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
                f"{self._base(cfg)}/{cfg['domain']}",
                auth=("api", cfg["api_key"]),
            )
            if r.status_code < 400:
                return ConnectionHealth(
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    ok=True, message="Mailgun domain.get OK.",
                    checked_at=now_iso(),
                )
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Mailgun probe HTTP {r.status_code}",
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Mailgun probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
