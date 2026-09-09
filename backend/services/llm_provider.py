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
                                image_b64s: Optional[List[str]] = None,
                                provider: str = "anthropic",
                                model: str = "claude-sonnet-4-5",
                                parse_json: bool = True,
                                max_tokens: Optional[int] = None,
                                ) -> Dict[str, Any]:
    """Single Emergent LLM round-trip. Returns ``{"raw": <parsed json>}``
    on success or ``{"error": "..."}`` on any failure.

    Feb-2026 · I1.7.e Chunk 2.b — supports both URL (``photo_urls``) and
    base64 (``image_b64s``) vision so raw-SDK callers migrated in this
    chunk can round-trip through the chokepoint. Cap of 8 images total
    (across both lists) matches the pre-migration behavior of the
    direct-SDK sites.

    ``parse_json=False`` skips the JSON round-trip and returns
    ``{"raw": {"text": <plaintext response>}}`` — the shape plaintext
    callers (review replies, SMS drafts, some AI-brain agents) expect.
    ``max_tokens`` maps to ``.with_max_tokens(n)`` on the ``LlmChat``.
    """
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
        if max_tokens:
            try:
                chat = chat.with_max_tokens(int(max_tokens))
            except Exception:
                pass
        file_contents: List[Any] = []
        for url in (photo_urls or [])[:8]:
            try:
                file_contents.append(ImageContent(image_url=url))
            except Exception:
                pass
        remaining = 8 - len(file_contents)
        for b64 in (image_b64s or [])[:max(0, remaining)]:
            try:
                file_contents.append(ImageContent(image_base64=b64))
            except Exception:
                pass
        msg = UserMessage(text=user_text,
                            file_contents=file_contents or None)
        resp = await asyncio.wait_for(chat.send_message(msg),
                                        timeout=_TIMEOUT_SECONDS)
        raw_text = str(resp).strip()
        if not parse_json:
            # Plaintext branch — return the response verbatim in the
            # legacy ``{"raw": {"text": ...}}`` shape so migrated
            # callers can .get("raw", {}).get("text") uniformly.
            if not raw_text:
                return {"error": "emergent_empty_text"}
            return {"raw": {"text": raw_text}}
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
                              image_b64s: Optional[List[str]] = None,
                              model: Optional[str] = None,
                              parse_json: bool = True,
                              max_tokens: Optional[int] = None,
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
        remaining = 8 - max(0, len(user_parts) - 1)
        for b64 in (image_b64s or [])[:max(0, remaining)]:
            # OpenAI accepts base64 via a `data:` URL — no separate
            # image_base64 param, matches the Anthropic Emergent branch
            # by input surface but a different wire format.
            user_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "low",
                },
            })
        completion = await asyncio.to_thread(
            client.chat.completions.create,
            model=model or OPENAI_DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_parts},
            ],
            **({"response_format": {"type": "json_object"}} if parse_json else {}),
            **({"max_tokens": int(max_tokens)} if max_tokens else {}),
            temperature=0.3,
        )
        text = ""
        if completion and completion.choices:
            text = (completion.choices[0].message.content or "").strip()
        if not parse_json:
            if not text:
                return {"error": "openai_empty_text"}
            return {"raw": {"text": text}}
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
                                    image_b64s: Optional[List[str]] = None,
                                    provider: str = "anthropic",
                                    model: str = "claude-sonnet-4-5",
                                    openai_model: Optional[str] = None,
                                    tenant_id: Optional[str] = None,
                                    parse_json: bool = True,
                                    max_tokens: Optional[int] = None,
                                    ) -> Dict[str, Any]:
    """High-level dispatcher.

    Returns::
      {"raw": <parsed json>, "provider": "emergent"|"openai"|"tenant_byo"}
    OR::
      {"error": "...", "provider": "emergent"|"openai"|"tenant_byo",
        "cap_exceeded": True}   # only when a BYO cap is hit

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

    Phase I1.7.e · chunk 2 · Feb-2026 — Tenant-BYO first hop
    ---------------------------------------------------------
    When ``tenant_id`` is passed AND the tenant has a BYO AI provider
    row configured, the request is routed through
    ``services.ai.dispatcher.dispatch_ai_completion`` instead of the
    Emergent / OpenAI branches. A BYO cap-exceeded is HARD BLOCK — the
    return dict contains ``{"cap_exceeded": True, "error":
    "ai_spend_cap_exceeded", "http_status": 429}`` and callers MUST
    NOT transparently fall back to the platform key (see rule 2 in
    ``services/ai/dispatcher.py``). ``tenant_id=None`` (the default)
    preserves pre-migration behaviour bit-for-bit — no BYO probe, no
    cap check, straight Emergent → OpenAI path.
    """
    # Phase I1.7.e · chunk 2 · Feb-2026 — tenant-BYO first hop.
    if tenant_id:
        try:
            from services.ai.dispatcher import dispatch_ai_completion
            from services.ai.models import TenantAIUsageCapExceeded
            try:
                result = await dispatch_ai_completion(
                    tenant_id=tenant_id,
                    system_prompt=system_prompt, user_text=user_text,
                    model=model,
                )
            except TenantAIUsageCapExceeded as cap:
                logger.info(
                    f"[llm_provider] tenant_byo cap-exceeded tenant={tenant_id} "
                    f"provider={cap.provider} cap={cap.cap} used={cap.used}"
                )
                return {
                    "error": "ai_spend_cap_exceeded",
                    "provider": "tenant_byo",
                    "cap_exceeded": True,
                    "http_status": 429,
                    "detail": {
                        "provider": cap.provider,
                        "monthly_cap": cap.cap,
                        "used": cap.used,
                    },
                }
            # Map AICompletionResult back to the legacy shape.
            raw: Dict[str, Any] = dict(getattr(result, "raw", {}) or {})
            if not raw:
                raw = {}
            raw.setdefault("text", getattr(result, "content", "") or "")
            raw.setdefault("content", getattr(result, "content", "") or "")
            # ``provider_used`` is a colon-prefixed origin tag:
            #   "tenant:{short}"          — real / mocked BYO provider
            #   "byo:{short}"             — test-fake BYO provider
            #   "platform:emergent"       — Emergent platform fallback
            # Any of those three surfaces through as ``tenant_byo``
            # from the migration chokepoint's point of view because
            # the request was routed through the dispatcher (not the
            # legacy Emergent/OpenAI branches below).
            pu = getattr(result, "provider_used", "") or ""
            provider_tag = "tenant_byo" if pu.startswith(("tenant:", "byo:")) else "emergent"
            return {"raw": raw, "provider": provider_tag}
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"[llm_provider] tenant_byo dispatch raised — falling through "
                f"to Emergent/OpenAI: {type(e).__name__}: {e}"
            )

    # Phase I1.7.e · chunk 2 · Feb-2026 — AI_TESTMODE_MOCK short-circuit
    # for the pure platform path (no tenant_id passed). Returns a
    # deterministic mock in the legacy ``{"raw": ..., "provider": ...}``
    # shape so no caller migration is required to hermetic-ify tests.
    try:
        from services.ai.testmode import (
            is_ai_testmode, mock_llm_provider_response,
        )
        if is_ai_testmode():
            return mock_llm_provider_response(
                system_prompt=system_prompt, user_text=user_text,
                provider=_PROVIDER_EMERGENT,
            )
    except Exception:  # noqa: BLE001 — never let testmode probe explode
        pass

    forced = force_provider()
    if forced == _PROVIDER_OPENAI:
        r = await _call_openai_text(system_prompt=system_prompt,
                                       user_text=user_text,
                                       photo_urls=photo_urls,
                                       image_b64s=image_b64s,
                                       model=openai_model,
                                       parse_json=parse_json,
                                       max_tokens=max_tokens)
        return {**r, "provider": _PROVIDER_OPENAI}
    if forced == _PROVIDER_EMERGENT:
        r = await _call_emergent_text(system_prompt=system_prompt,
                                         user_text=user_text,
                                         photo_urls=photo_urls,
                                         image_b64s=image_b64s,
                                         provider=provider, model=model,
                                         parse_json=parse_json,
                                         max_tokens=max_tokens)
        return {**r, "provider": _PROVIDER_EMERGENT}

    first = await _call_emergent_text(system_prompt=system_prompt,
                                         user_text=user_text,
                                         photo_urls=photo_urls,
                                         image_b64s=image_b64s,
                                         provider=provider, model=model,
                                         parse_json=parse_json,
                                         max_tokens=max_tokens)
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
                                        image_b64s=image_b64s,
                                        model=openai_model,
                                        parse_json=parse_json,
                                        max_tokens=max_tokens)
    return {**second, "provider": _PROVIDER_OPENAI}
