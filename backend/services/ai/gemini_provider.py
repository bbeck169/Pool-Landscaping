"""Phase I1.7.c.1 · Feb-2026 — Google Gemini BYO provider."""
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


log = logging.getLogger("ai.gemini")

_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(AIProvider):
    provider_key = "ai_gemini"
    short_name = "gemini"
    default_model = "gemini-1.5-flash"
    supported_models = [
        "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash",
    ]
    primary_secret_field = "api_key"

    config_fields: Dict[str, Dict[str, Any]] = {
        "api_key":       {"required": True,  "secret": True,  "label": "Google Gemini API Key"},
        "default_model": {"required": False, "secret": False, "label": "Default model"},
    }

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http_client

    async def _client(self) -> httpx.AsyncClient:
        return self._http or httpx.AsyncClient(timeout=30.0)

    async def _cfg(self, tenant_id: str) -> Dict[str, Any]:
        cfg = await load_provider_config(tenant_id=tenant_id, provider_key=self.provider_key)
        if not cfg:
            raise TenantAINotConnected(f"Tenant {tenant_id} has no Gemini config")
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
                content=f"[mock gemini] {user_text[:40]}",
                provider_key=self.provider_key,
                provider_used=f"tenant:{self.short_name}",
                model=chosen_model,
                tokens_prompt=8, tokens_completion=12, tokens_total=20,
                tenant_id=tenant_id,
                raw={"mock": True, "at": now_iso(), "id": f"gen_test_{uuid.uuid4().hex[:12]}"},
            )
        key = cfg.get("api_key", "")
        client = await self._client()
        try:
            r = await client.post(
                f"{_GEMINI_API_BASE}/models/{chosen_model}:generateContent",
                params={"key": key},
                headers={"Content-Type": "application/json"},
                json={
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{
                        "role": "user",
                        "parts": [{"text": user_text}],
                    }],
                },
            )
            j = r.json() if r.content else {}
            if r.status_code >= 400:
                await log_secret_error(
                    tenant_id, self.provider_key,
                    code=f"GEMINI_{r.status_code}",
                    message=f"complete HTTP {r.status_code}",
                )
                raise AIError(f"gemini HTTP {r.status_code}")
            await mark_used(tenant_id, self.provider_key)
            usage = j.get("usageMetadata", {}) or {}
            content = ""
            candidates = j.get("candidates") or []
            if candidates:
                parts = (candidates[0].get("content") or {}).get("parts") or []
                content = "".join((p.get("text") or "") for p in parts if isinstance(p, dict))
            tokens_prompt = int(usage.get("promptTokenCount", 0) or 0)
            tokens_completion = int(usage.get("candidatesTokenCount", 0) or 0)
            tokens_total = int(usage.get("totalTokenCount", tokens_prompt + tokens_completion) or 0)
            return AICompletionResult(
                content=content,
                provider_key=self.provider_key,
                provider_used=f"tenant:{self.short_name}",
                model=chosen_model,
                tokens_prompt=tokens_prompt,
                tokens_completion=tokens_completion,
                tokens_total=tokens_total,
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
                ok=False, message="No Gemini config saved for this tenant.",
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
            r = await client.get(
                f"{_GEMINI_API_BASE}/models",
                params={"key": key},
            )
            if r.status_code == 200:
                return ConnectionHealth(
                    provider_key=self.provider_key, tenant_id=tenant_id,
                    ok=True, message="Gemini /models returned OK.",
                    checked_at=now_iso(),
                )
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Gemini probe HTTP {r.status_code}",
                checked_at=now_iso(),
            )
        except Exception as e:
            return ConnectionHealth(
                provider_key=self.provider_key, tenant_id=tenant_id,
                ok=False, message=f"Gemini probe failed: {type(e).__name__}",
                checked_at=now_iso(),
            )
        finally:
            if self._http is None:
                await client.aclose()
