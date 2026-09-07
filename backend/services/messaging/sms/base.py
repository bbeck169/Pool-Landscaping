"""Phase I1.7.b · Feb-2026 — SMS provider abstract base class.

Mirrors ``services.payments.tenant_base.TenantPaymentProvider``.
Each concrete provider reads its credentials via ``services.secrets``
so plaintext never crosses the encryption boundary.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..models import (
    ConnectionHealth,
    SmsInboundEvent,
    SmsResult,
    SmsStatus,
)


class SmsProvider(ABC):
    """Tenant-scoped SMS provider contract."""

    provider_key: str = "abstract_sms"

    #: Field schema for the ``PUT /api/tenants/me/integrations/{key}``
    #: endpoint. Each entry is ``(field_name, {"required": bool, "secret": bool, "label": str})``.
    #: ``secret=True`` fields are stored inside the encrypted blob;
    #: ``secret=False`` fields are stored in ``connected_account_id``
    #: (single string) or serialized alongside the secret payload.
    config_fields: Dict[str, Dict[str, Any]] = {}

    @abstractmethod
    async def send_sms(
        self, *, tenant_id: str, to: str, body: str,
        media_urls: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SmsResult:
        raise NotImplementedError

    @abstractmethod
    async def get_status(
        self, *, tenant_id: str, message_id: str,
    ) -> SmsStatus:
        raise NotImplementedError

    @abstractmethod
    async def verify_webhook(
        self, *, payload: bytes, headers: Dict[str, str],
    ) -> SmsInboundEvent:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(
        self, *, tenant_id: str,
    ) -> ConnectionHealth:
        raise NotImplementedError
