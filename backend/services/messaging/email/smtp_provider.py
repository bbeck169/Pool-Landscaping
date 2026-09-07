"""Phase I1.7.b · Feb-2026 — Generic SMTP email provider (tenant-scoped).

Fallback path for tenants with a custom mail server (Office 365,
Google Workspace via SMTP, self-hosted Exim, etc.). Host / port / user
/ password / TLS mode are all stored inside the encrypted blob via
``services.secrets`` — plaintext never touches disk or logs.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import smtplib
import ssl
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import Any, Dict, List, Optional

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


log = logging.getLogger("messaging.email.smtp")


class SmtpEmailProvider(EmailProvider):
    provider_key = "smtp"

    config_fields: Dict[str, Dict[str, Any]] = {
        "host":       {"required": True,  "secret": False, "label": "SMTP host"},
        "port":       {"required": True,  "secret": False, "label": "SMTP port (usually 587)"},
        "username":   {"required": True,  "secret": False, "label": "SMTP username"},
        "password":   {"required": True,  "secret": True,  "label": "SMTP password"},
        "from_addr":  {"required": True,  "secret": False, "label": "Default From address"},
        "use_tls":    {"required": False, "secret": False, "label": "STARTTLS (default: true)"},
        "use_ssl":    {"required": False, "secret": False, "label": "Implicit SSL (default: false — port 465)"},
    }

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantMessagingNotConnected(f"Tenant {tenant_id} has no SMTP config")
        return cfg

    def _send_blocking(
        self, cfg: Dict[str, Any], to: List[str], subject: str,
        html_body: Optional[str], text_body: Optional[str],
        from_addr: str, attachments: Optional[List[EmailAttachment]],
        reply_to: Optional[str],
    ) -> str:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = ", ".join(to)
        if reply_to:
            msg["Reply-To"] = reply_to
        message_id = f"<{uuid.uuid4().hex}@{cfg['host']}>"
        msg["Message-ID"] = message_id
        if text_body:
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))
        if attachments:
            for a in attachments:
                part = MIMEApplication(base64.b64decode(a.content_b64), _subtype=a.content_type.split("/")[-1])
                part.add_header("Content-Disposition", "attachment", filename=a.filename)
                msg.attach(part)

        host, port = cfg["host"], int(cfg["port"])
        use_ssl = bool(cfg.get("use_ssl"))
        use_tls = cfg.get("use_tls")
        use_tls = True if use_tls is None else bool(use_tls)
        ctx = ssl.create_default_context()
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as srv:
                srv.login(cfg["username"], cfg["password"])
                srv.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as srv:
                if use_tls:
                    srv.starttls(context=ctx)
                srv.login(cfg["username"], cfg["password"])
                srv.send_message(msg)
        return message_id

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
                id=f"smtp_test_{uuid.uuid4().hex[:20]}",
                status="queued", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso()},
            )
        cfg = await self._cfg(tenant_id)
        addr = from_addr or cfg["from_addr"]
        try:
            message_id = await asyncio.to_thread(
                self._send_blocking, cfg, to, subject, html_body,
                text_body, addr, attachments, reply_to,
            )
            await mark_used(tenant_id, self.provider_key)
            return EmailResult(
                id=message_id, status="sent", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"host": cfg["host"], "port": cfg["port"]},
            )
        except Exception as e:
            log.warning("smtp send_email failed: %s", type(e).__name__)
            await log_secret_error(tenant_id, self.provider_key,
                                     code="SMTP_EXCEPTION",
                                     message=type(e).__name__)
            return EmailResult(
                id="", status="failed", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={}, error=type(e).__name__,
            )

    async def get_status(self, *, tenant_id: str, message_id: str) -> EmailStatus:
        # SMTP is fire-and-forget — no delivery status API.
        return EmailStatus(id=message_id, status="unknown",
                            provider_key=self.provider_key, tenant_id=tenant_id,
                            raw={"note": "smtp has no delivery status API"})

    async def verify_webhook(
        self, *, payload: bytes, headers: Dict[str, str],
    ) -> EmailInboundEvent:
        raise MessagingError("smtp provider does not accept webhooks")

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No SMTP config saved for this tenant.",
                checked_at=now_iso(),
            )
        if email_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="mock", checked_at=now_iso(),
            )
        def _probe() -> str:
            host, port = cfg["host"], int(cfg["port"])
            use_ssl = bool(cfg.get("use_ssl"))
            use_tls = cfg.get("use_tls")
            use_tls = True if use_tls is None else bool(use_tls)
            ctx = ssl.create_default_context()
            if use_ssl:
                with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as srv:
                    srv.login(cfg["username"], cfg["password"])
                    srv.noop()
            else:
                with smtplib.SMTP(host, port, timeout=15) as srv:
                    if use_tls:
                        srv.starttls(context=ctx)
                    srv.login(cfg["username"], cfg["password"])
                    srv.noop()
            return "SMTP login + NOOP returned OK."
        try:
            msg = await asyncio.to_thread(_probe)
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message=msg, checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"SMTP probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
