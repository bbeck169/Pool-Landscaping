"""Phase I1.7.c.1 · Feb-2026 — AI provider abstract base class.

Mirrors ``services.messaging.sms.base.SmsProvider`` — each concrete
provider reads its credentials via ``services.secrets`` so plaintext
never crosses the encryption boundary.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .models import AICompletionResult, ConnectionHealth


class AIProvider(ABC):
    """Tenant-scoped AI provider contract."""

    provider_key: str = "abstract_ai"
    #: Short name used in ``tenant_ai_usage.provider`` + the ``/usage``
    #: response — e.g. ``"openai"``, ``"anthropic"``, ``"gemini"``.
    short_name: str = "abstract"
    default_model: str = ""
    #: Model options surfaced to the frontend dropdown.
    supported_models: List[str] = []

    config_fields: Dict[str, Dict[str, Any]] = {}
    primary_secret_field: Optional[str] = None

    @abstractmethod
    async def complete(
        self, *, tenant_id: str, system_prompt: str, user_text: str,
        model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AICompletionResult:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(
        self, *, tenant_id: str,
    ) -> ConnectionHealth:
        raise NotImplementedError
