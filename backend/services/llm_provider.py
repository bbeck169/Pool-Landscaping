"""LLM provider fallback — used by ai_estimator + autopilot_copy.

Design
======
* Primary: **Emergent Universal LLM Key** via ``emergentintegrations``.
* Fallback: **direct OpenAI SDK** using ``OPENAI_API_KEY`` from the
  environment. Only fires when the Emergent path fails hard — 5xx / auth
  / timeout / import error / bad payload. Same JSON contract preserved.
* Env-only ``PROVIDER_FORCE`` (values: ``emergent`` | ``openai``)
  bypasses the primary and calls straight into the chosen provider.
  Used by tests + preview smoke curls to prove the fallback wire.

Every caller records ``ai_meta.provider`` in whatever downstream doc it
persists (draft estimate, autopilot copy row) so we can inspect after
the fact which provider actually served the request.

Timeouts
--------
* Emergent path: 30 s soft (the emergentintegrations lib does not
  expose a timeout kwarg, so we wrap the call in ``asyncio.wait_for``).
* OpenAI path: 30 s (via SDK's ``timeout=30``).
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Callable, Dict, List, Optional

from config import EMERGENT_LLM_KEY, logger
from utils import new_id

_PROVIDER_EMERGENT = "emergent"
_PROVIDER_OPENAI = "openai"
_TIMEOUT_SECONDS = 30.0

# Default OpenAI model used for the fallback path. Kept in one place so
# it's trivial to bump. Uses gpt-4o for parity with Claude Sonnet on
# vision + JSON responses.
OPENAI_DEFAULT_MODEL = os.environ.get("OPENAI_FALLBACK_MODEL", "gpt-4o")


def force_provider() -> Optional[str]:
    """Return the value of ``PROVIDER_FORCE`` when set to a known
    provider — otherwise None."""
    v = (os.environ.get("PROVIDER_FORCE") or "").strip().lower()
    return v if v in (_PROVIDER_EMERGENT, _PROVIDER_OPENAI) else None


def openai_available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def _extract_json(text: str) -> Dict[str, Any]:
    """Slice a JSON object out of an LLM response body. Tolerant of
    leading commentary / trailing prose the way both Claude and GPT
    occasionally leak."""
    if not text:
        return {}
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return {}


async def _call_emergent_text(*, system_prompt: str, user_text: str,
                                photo_urls: Optional[List[str]] = None,
                                provider: str = "anthropic",
                                model: str = "claude-sonnet-4-5",
                                ) -> Dict[str, Any]:
    """Single Emergent LLM round-trip. Returns ``{"raw": <parsed json>}``
    on success or ``{"error": "..."}`` on any failure."""
    key = EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        return {"error": "emergent_key_missing"}
    try:
        from emergentintegrations.llm.chat import (
            LlmChat, UserMessage, ImageContent,
        )
    except Exception as e:
        return {"error": f"emergent_import_failed: {e}"}
    try:
        chat = (LlmChat(api_key=key, session_id=new_id(),
                          system_message=system_prompt)
                .with_model(provider, model))
        parts: List[Any] = [user_text]
        for url in (photo_urls or [])[:8]:
            try:
                parts.append(ImageContent(image_url=url))
            except Exception:
                pass
        msg = UserMessage(text="\n".join(str(p) for p in parts
                                            if isinstance(p, str)))
        resp = await asyncio.wait_for(chat.send_message(msg),
                                        timeout=_TIMEOUT_SECONDS)
        raw_text = str(resp).strip()
        payload = _extract_json(raw_text)
        if not payload:
            return {"error": "emergent_empty_json"}
        return {"raw": payload}
    except asyncio.TimeoutError:
        return {"error": "emergent_timeout"}
    except Exception as e:
        logger.warning(f"[llm_provider] emergent call failed: {e}")
        return {"error": f"emergent_call_failed: {e}"}


async def _call_openai_text(*, system_prompt: str, user_text: str,
                              photo_urls: Optional[List[str]] = None,
                              model: Optional[str] = None,
                              ) -> Dict[str, Any]:
    """OpenAI fallback branch — **STUBBED OUT** as of Feb 2026 per the
    user's decision to run on Emergent only.

    Returns ``{"error": "openai_disabled"}`` immediately when
    ``OPENAI_API_KEY`` is unset. When a key IS set (opt-in), performs a
    real ``chat.completions`` call. The ``openai`` SDK is imported
    lazily inside this function so a completely uninstalled SDK still
    lets the module load cleanly.
    """
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return {"error": "openai_disabled"}
    try:
        from openai import OpenAI, APITimeoutError
    except Exception as e:
        return {"error": f"openai_import_failed: {e}"}
    try:
        client = OpenAI(api_key=key, timeout=_TIMEOUT_SECONDS)
        user_parts: List[Dict[str, Any]] = [
            {"type": "text", "text": user_text}
        ]
        for url in (photo_urls or [])[:8]:
            user_parts.append({
                "type": "image_url",
                "image_url": {"url": url, "detail": "low"},
            })
        completion = await asyncio.to_thread(
            client.chat.completions.create,
            model=model or OPENAI_DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_parts},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        text = ""
        if completion and completion.choices:
            text = (completion.choices[0].message.content or "").strip()
        payload = _extract_json(text)
        if not payload:
            return {"error": "openai_empty_json"}
        return {"raw": payload}
    except APITimeoutError:
        return {"error": "openai_timeout"}
    except Exception as e:
        logger.warning(f"[llm_provider] openai call failed: {e}")
        return {"error": f"openai_call_failed: {e}"}


async def call_llm_with_fallback(*, system_prompt: str, user_text: str,
                                    photo_urls: Optional[List[str]] = None,
                                    provider: str = "anthropic",
                                    model: str = "claude-sonnet-4-5",
                                    openai_model: Optional[str] = None,
                                    ) -> Dict[str, Any]:
    """High-level dispatcher.

    Returns::
      {"raw": <parsed json>, "provider": "emergent"|"openai"}
    OR::
      {"error": "...", "provider": "emergent"|"openai"}

    Behaviour (Feb 2026 — Emergent-only default)
    ---------------------------------------------
    * ``PROVIDER_FORCE=openai`` → skip Emergent, call OpenAI branch. When
      ``OPENAI_API_KEY`` is unset the branch immediately returns
      ``{"error": "openai_disabled", "provider": "openai"}``.
    * ``PROVIDER_FORCE=emergent`` → call Emergent only; no fallback.
    * Default (no force) → Emergent first. On hard failure we fall back
      to OpenAI **only if** ``OPENAI_API_KEY`` is present. With no key
      set, the Emergent error is returned as-is tagged
      ``provider: "emergent"``.
    """
    forced = force_provider()
    if forced == _PROVIDER_OPENAI:
        r = await _call_openai_text(system_prompt=system_prompt,
                                       user_text=user_text,
                                       photo_urls=photo_urls,
                                       model=openai_model)
        return {**r, "provider": _PROVIDER_OPENAI}
    if forced == _PROVIDER_EMERGENT:
        r = await _call_emergent_text(system_prompt=system_prompt,
                                         user_text=user_text,
                                         photo_urls=photo_urls,
                                         provider=provider, model=model)
        return {**r, "provider": _PROVIDER_EMERGENT}

    first = await _call_emergent_text(system_prompt=system_prompt,
                                         user_text=user_text,
                                         photo_urls=photo_urls,
                                         provider=provider, model=model)
    if not first.get("error"):
        return {**first, "provider": _PROVIDER_EMERGENT}
    if not openai_available():
        # Emergent-only mode — return the emergent error verbatim so
        # upstream callers (estimator catalog-fallback, autopilot copy
        # error surface) can decide their own recovery path.
        return {**first, "provider": _PROVIDER_EMERGENT}
    logger.info(
        f"[llm_provider] emergent path failed ({first.get('error')!r}) — "
        f"falling back to OpenAI"
    )
    second = await _call_openai_text(system_prompt=system_prompt,
                                        user_text=user_text,
                                        photo_urls=photo_urls,
                                        model=openai_model)
    return {**second, "provider": _PROVIDER_OPENAI}
