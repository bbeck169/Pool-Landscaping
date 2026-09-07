"""Phase I1.7.b · Feb-2026 — Email provider abstract base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..models import (
    ConnectionHealth,
    EmailAttachment,
    EmailInboundEvent,
    EmailResult,
    EmailStatus,
)


class EmailProvider(ABC):
    provider_key: str = "abstract_email"

    #: Field schema for the settings UI. See ``SmsProvider.config_fields``.
    config_fields: Dict[str, Dict[str, Any]] = {}

    #: I1.7.b.fix — see ``SmsProvider.primary_secret_field``.
    primary_secret_field: Optional[str] = None

    @abstractmethod
    async def send_email(
        self, *, tenant_id: str, to: List[str], subject: str,
        html_body: Optional[str] = None,
        text_body: Optional[str] = None,
        from_addr: Optional[str] = None,
        attachments: Optional[List[EmailAttachment]] = None,
        reply_to: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EmailResult:
        raise NotImplementedError

    @abstractmethod
    async def get_status(
        self, *, tenant_id: str, message_id: str,
    ) -> EmailStatus:
        raise NotImplementedError

    @abstractmethod
    async def verify_webhook(
        self, *, payload: bytes, headers: Dict[str, str],
    ) -> EmailInboundEvent:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(
        self, *, tenant_id: str,
    ) -> ConnectionHealth:
        raise NotImplementedError
