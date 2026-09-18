"""Phase I1.7.b · Feb-2026 — Resend email provider (tenant-scoped).

Feb-2026 comms hotfix — ``send_email()`` accepts an optional
``from_name`` display-name override so callers (BYO passthrough,
marketing/campaigns, tenant-branded transactional sends) can
render the correct "AquaTerra Pools <no-reply@…>" header in the
recipient's inbox. The header is assembled with
``email.utils.formataddr`` so display names with commas,
semicolons, or quotes are RFC 5322-safe (blocks header injection
via a crafted tenant name).
"""
from __future__ import annotations

import logging
import uuid
from email.utils import formataddr
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


def _mask_email(e: Optional[str]) -> str:
    """PII-safe recipient rendering for log lines."""
    if not e or "@" not in e:
        return "***"
    local, _, domain = e.partition("@")
    if len(local) <= 2:
        return f"*@{domain}"
    return f"{local[0]}***{local[-1]}@{domain}"


def _mask_recipients(rs: Optional[List[str]]) -> str:
    if not rs:
        return "<none>"
    return ",".join(_mask_email(r) for r in rs[:3]) + (
        f" (+{len(rs) - 3})" if len(rs) > 3 else ""
    )


def _build_from_header(from_email: str, from_name: Optional[str]) -> str:
    """Render an RFC 5322-safe ``From`` header. ``formataddr``
    handles quoting / escaping when the display name contains a
    comma, semicolon, quote, or angle bracket.

    Defense-in-depth: strip ASCII control characters (CR, LF,
    NULL, and other <0x20 bytes) BEFORE handing the name to
    ``formataddr`` so a crafted tenant name cannot smuggle a raw
    ``\\r\\nBcc: ...`` sequence into the JSON payload. Resend's
    transport layer already ignores in-JSON CRLF, but we belt-
    and-braces so downstream consumers of the payload (log lines,
    audits, alternate providers) never see them either.
    """
    if from_name is not None:
        sanitized = "".join(
            ch for ch in from_name if ord(ch) >= 0x20 and ch != "\x7f"
        )
        stripped = sanitized.strip()
        if stripped:
            return formataddr((stripped, from_email))
    return from_email


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
        from_name: Optional[str] = None,
        attachments: Optional[List[EmailAttachment]] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EmailResult:
        """Send a message via Resend for a tenant's BYO account.

        Feb-2026 comms hotfix:
          * ``from_name`` (optional) — per-call display-name override
            (typically ``tenant.name`` for brand fidelity). Empty
            string / None falls back to ``cfg['from_name']`` from
            the tenant's saved provider config, then to the bare
            address.
          * ``From`` header is rendered with
            :func:`email.utils.formataddr` so display names with
            commas / quotes / brackets can't inject extra headers.
          * All send failures are logged at ``ERROR`` with the
            exception type + message, masked recipient(s), a
            truncated subject, and the Resend ``x-request-id`` /
            ``resend-request-id`` header (when present).
        """
        if email_testmode_mock():
            return EmailResult(
                id=f"resend_test_{uuid.uuid4().hex[:20]}",
                status="queued", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso(),
                     "from_name": (from_name or "").strip() or None},
            )
        cfg = await self._cfg(tenant_id)
        addr = from_addr or cfg["from_addr"]
        # Call-arg wins; fall back to the tenant's stored default;
        # empty/whitespace-only strings are treated as None.
        effective_from_name = (
            (from_name.strip() if isinstance(from_name, str) else None)
            or (cfg.get("from_name") if cfg.get("from_name") else None)
        )
        from_header = _build_from_header(addr, effective_from_name)
        payload: Dict[str, Any] = {"from": from_header, "to": to, "subject": subject}
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
            # Resend surfaces its trace id on either header; the
            # public docs use lower-case ``x-request-id`` and the
            # Cloudflare edge sometimes echoes ``resend-request-id``.
            req_id = (
                r.headers.get("x-request-id")
                or r.headers.get("resend-request-id")
                or r.headers.get("cf-ray")
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                log.error(
                    "[resend] send_email non-2xx tenant=%s to=%s "
                    "subject=%r status=%s request_id=%s body=%r",
                    tenant_id, _mask_recipients(to),
                    (subject or "")[:100], r.status_code, req_id,
                    str(j)[:400] if j else "",
                )
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
            log.error(
                "[resend] send_email exception tenant=%s to=%s "
                "subject=%r err=%s: %s",
                tenant_id, _mask_recipients(to),
                (subject or "")[:100], type(e).__name__, e,
                exc_info=True,
            )
            await log_secret_error(tenant_id, self.provider_key,
                                     code="RESEND_EXCEPTION",
                                     message=f"{type(e).__name__}: {e}")
            return EmailResult(
                id="", status="failed", to=to,
                provider_key=self.provider_key, tenant_id=tenant_id,
                raw={}, error=f"{type(e).__name__}: {e}",
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
                # Feb-2026 · P0 comms — surface the domain list + first
                # ``verified`` domain so ops can immediately confirm
                # the BYO key is scoped to the right project.
                _verified = []
                try:
                    _body = r.json()
                    for _d in (_body.get("data") or []):
                        if (_d.get("status") or "").lower() == "verified":
                            _verified.append(_d.get("name"))
                except Exception:  # noqa: BLE001
                    pass
                _msg = "Resend domains.list OK."
                if _verified:
                    _msg += f" verified_domains={_verified}"
                return ConnectionHealth(
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    ok=True, message=_msg, checked_at=now_iso(),
                )
            # Feb-2026 · P0 comms — capture the Resend error body so
            # ops don't have to guess. Resend returns
            # ``{"message":"...","name":"..."}`` on 4xx. Redact any
            # accidental key echoing (Resend doesn't currently, but
            # belt-and-braces).
            _body_text = ""
            try:
                _body_text = r.text[:800] if r.text else ""
                if cfg.get("api_key") and cfg["api_key"] in _body_text:
                    _body_text = _body_text.replace(
                        cfg["api_key"], f"{cfg['api_key'][:6]}...(redacted)",
                    )
            except Exception:  # noqa: BLE001
                _body_text = "<body read failed>"
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False,
                message=f"Resend probe HTTP {r.status_code} body={_body_text}",
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
