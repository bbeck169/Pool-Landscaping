"""Phase I1.7.c.1 · Feb-2026 — Anthropic (Claude) BYO provider."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

import httpx

from services.secrets import log_error as log_secret_error, mark_used

from ._helpers import ai_testmode_mock, load_provider_config, now_iso
from .models import (
    AICompletionResult,
    AIError,
    ConnectionHealth,
    TenantAINotConnected,
)
from .tenant_base import AIProvider


log = logging.getLogger("ai.anthropic")

_ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(AIProvider):
    provider_key = "ai_anthropic"
    short_name = "anthropic"
    default_model = "claude-3-5-sonnet-latest"
    supported_models = [
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-latest",
    ]
    primary_secret_field = "api_key"

    config_fields: Dict[str, Dict[str, Any]] = {
        "api_key":       {"required": True,  "secret": True,  "label": "Anthropic API Key"},
        "default_model": {"required": False, "secret": False, "label": "Default model"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=30.0)

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantAINotConnected(f"Tenant {tenant_id} has no Anthropic config")
        return cfg

    async def complete(
        self, *, tenant_id: str, system_prompt: str, user_text: str,
        model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AICompletionResult:
        cfg = await self._cfg(tenant_id)
        chosen_model = model or cfg.get("default_model") or self.default_model
        if ai_testmode_mock():
            return AICompletionResult(
                content=f"[mock anthropic] {user_text[:40]}",
                provider_key=self.provider_key,
                provider_used=f"tenant:{self.short_name}",
                model=chosen_model,
                tokens_prompt=12, tokens_completion=18, tokens_total=30,
                tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso(), "id": f"msg_test_{uuid.uuid4().hex[:12]}"},
            )
        key = cfg.get("api_key", "")
        client = await self._client()
        try:
            r = await client.post(
                f"{_ANTHROPIC_API_BASE}/messages",
                headers={"x-api-key": key,
                         "anthropic-version": _ANTHROPIC_VERSION,
                         "Content-Type": "application/json"},
                json={
                    "model": chosen_model,
                    "max_tokens": 1024,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_text}],
                },
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"ANTHROPIC_{r.status_code}",
                    message=f"complete HTTP {r.status_code}",
                )
                raise AIError(f"anthropic HTTP {r.status_code}")
            await mark_used(tenant_id, self.provider_key)
            usage = j.get("usage", {}) or {}
            content = ""
            blocks = j.get("content") or []
            if blocks:
                # Anthropic returns a list of content blocks; concatenate all text blocks.
                content = "".join(
                    (b.get("text") or "") for b in blocks
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            tokens_prompt = int(usage.get("input_tokens", 0) or 0)
            tokens_completion = int(usage.get("output_tokens", 0) or 0)
            return AICompletionResult(
                content=content,
                provider_key=self.provider_key,
                provider_used=f"tenant:{self.short_name}",
                model=chosen_model,
                tokens_prompt=tokens_prompt,
                tokens_completion=tokens_completion,
                tokens_total=tokens_prompt + tokens_completion,
                tenant_id=tenant_id,
                raw=j,
            )
        finally:
            if self._http is None:
                await client.aclose()

    async def test_connection(self, *, tenant_id: str) -> ConnectionHealth:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message="No Anthropic config saved for this tenant.",
                checked_at=now_iso(),
            )
        if ai_testmode_mock():
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=True, message="mock", checked_at=now_iso(),
            )
        key = cfg.get("api_key", "")
        client = await self._client()
        try:
            # Anthropic's /models list requires the same auth header.
            r = await client.get(
                f"{_ANTHROPIC_API_BASE}/models",
                headers={"x-api-key": key, "anthropic-version": _ANTHROPIC_VERSION},
            )
            if r.status_code == 200:
                return ConnectionHealth(
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    ok=True, message="Anthropic /models returned OK.",
                    checked_at=now_iso(),
                )
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Anthropic probe HTTP {r.status_code}",
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Anthropic probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
