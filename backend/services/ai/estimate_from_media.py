"""Feb-2026 · Phase 25 · AI Photo + Voice → Repair Estimate (Winpal-inspired).

Two async entry points used by the ``ai_media_estimator`` router:

* ``estimate_from_photo(image_bytes, tenant_id, context_hint=None,
   filename=None, content_type=None)`` — Claude Sonnet 4.5 (vision) via
   Emergent Universal LLM Key. Returns a normalized estimate dict:

    {
      "parts": [{"name": "…", "cost": 12.34, "source": "pricebook_match"|"ai_inferred",
                 "matched_pricebook_id": Optional[str], "confidence": 0..100}],
      "labor_hours_estimated": float,
      "concerns": [str],
      "confidence": int (0..100),
      "raw_analysis": str,
      "transcript": None,
      "provider": "claude",
    }

* ``estimate_from_voice(audio_bytes, tenant_id, context_hint=None,
   filename=None, content_type=None)`` — Whisper transcription (OpenAI)
   → Claude estimator. Returns the same dict shape with ``transcript``
   populated. When ``OPENAI_API_KEY`` is missing, returns
   ``{"error": "voice_provider_disabled", "reason": "OPENAI_API_KEY not configured"}``.

Both paths run AI-guessed parts through a fuzzy match against
``db.items`` (this repo's ``pricebook_items`` collection). When the match
ratio exceeds ``PRICEBOOK_MATCH_THRESHOLD`` (0.8), the AI-inferred cost
is swapped for the tenant's real catalog price and ``source`` flips to
``"pricebook_match"``.

Guardrails
----------
* Never raises — all provider errors surface as ``{"error": "..."}`` so
  the router can return a graceful 200 or a targeted 4xx.
* Voice path degrades gracefully when ``OPENAI_API_KEY`` is unset so
  admins never see a broken button — they see a "provider disabled" toast.
* Rate-limiting + cost tracking are handled by the router, not here.
"""
from __future__ import annotations

import base64
import io
import json
import os
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import db, EMERGENT_LLM_KEY, logger
from utils import new_id

# We import ``config`` (the module, not just the ``db`` binding) so
# tests can rebind ``config.db`` to a fresh Motor client tied to the
# test's event loop. All Mongo access inside this file goes through
# ``_db()`` so the rebind is respected.
import config as _cfg


def _db():
    return _cfg.db

# ─────────────────────────────────────────────────────────────────────
# Tunables
# ─────────────────────────────────────────────────────────────────────
CLAUDE_PROVIDER = "anthropic"
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"
PRICEBOOK_MATCH_THRESHOLD = 0.80
WHISPER_MODEL = "whisper-1"
LLM_TIMEOUT_SECONDS = 60.0


# ─────────────────────────────────────────────────────────────────────
# Test-mode injection (mirrors services/ai_estimator.py convention)
# ─────────────────────────────────────────────────────────────────────
_TEST_MOCK_RESPONSES: List[Dict[str, Any]] = []


def prime_test_mocks(*payloads: Dict[str, Any]) -> None:
    """Queue N deterministic mock responses. Consumed one per LLM call."""
    _TEST_MOCK_RESPONSES.extend(payloads)


def clear_test_mocks() -> None:
    _TEST_MOCK_RESPONSES.clear()


def _mock_enabled() -> bool:
    return (os.environ.get("TEST_LLM_MOCK") or "").strip() in ("1", "true", "yes")


def _next_mock() -> Optional[Dict[str, Any]]:
    if _TEST_MOCK_RESPONSES:
        return _TEST_MOCK_RESPONSES.pop(0)
    return None


# ─────────────────────────────────────────────────────────────────────
# JSON extraction + normalization
# ─────────────────────────────────────────────────────────────────────
def _extract_json(text: str) -> Dict[str, Any]:
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


def _normalize_estimate(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce the raw LLM JSON into the strict estimate shape."""
    parts_in = raw.get("parts") or []
    parts_out: List[Dict[str, Any]] = []
    for p in parts_in[:20]:
        if not isinstance(p, dict):
            continue
        try:
            cost = float(p.get("cost") or 0)
        except (TypeError, ValueError):
            cost = 0.0
        parts_out.append({
            "name": str(p.get("name") or "").strip()[:200],
            "cost": round(cost, 2),
            "source": "ai_inferred",
            "matched_pricebook_id": None,
            "confidence": int(p.get("confidence") or 50),
        })
    try:
        hours = float(raw.get("labor_hours_estimated") or 0)
    except (TypeError, ValueError):
        hours = 0.0
    concerns = raw.get("concerns") or []
    if not isinstance(concerns, list):
        concerns = []
    concerns = [str(c)[:280] for c in concerns[:10] if c]
    try:
        confidence = int(float(raw.get("confidence") or 0))
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(100, confidence))
    return {
        "parts": parts_out,
        "labor_hours_estimated": round(hours, 2),
        "concerns": concerns,
        "confidence": confidence,
        "raw_analysis": str(raw.get("raw_analysis") or raw.get("analysis") or "")[:2000],
    }


# ─────────────────────────────────────────────────────────────────────
# Pricebook fuzzy-match
# ─────────────────────────────────────────────────────────────────────
async def _load_pricebook(tenant_id: str) -> List[Dict[str, Any]]:
    """Load the tenant's pricebook rows (this repo's ``db.items``)."""
    query = {"$or": [{"tenant_id": tenant_id}, {"tenant_id": {"$exists": False}}]}
    rows = await _db().items.find(query, {"_id": 0}).limit(2000).to_list(2000)
    return [r for r in rows if r.get("active") is not False and r.get("name")]


def _match_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(a=a.lower(), b=b.lower()).ratio()


async def _fuzzy_match_parts(tenant_id: str,
                                parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For every part, find the nearest pricebook_items.name; if the
    match ratio > threshold, swap in the pricebook cost + flag the
    match. Never raises; on any failure, the input is returned unchanged.
    """
    if not parts:
        return parts
    try:
        catalog = await _load_pricebook(tenant_id)
    except Exception as e:
        logger.warning(f"[ai.estimate] pricebook load failed: {e}")
        return parts
    if not catalog:
        return parts
    out: List[Dict[str, Any]] = []
    for p in parts:
        best_ratio = 0.0
        best: Optional[Dict[str, Any]] = None
        pname = p.get("name") or ""
        for row in catalog:
            r = _match_ratio(pname, row.get("name") or "")
            if r > best_ratio:
                best_ratio = r
                best = row
        if best and best_ratio >= PRICEBOOK_MATCH_THRESHOLD:
            # Prefer ``unit_price`` (retail) then ``cost``.
            price = best.get("unit_price")
            if price is None:
                price = best.get("cost")
            try:
                price_f = float(price or 0)
            except (TypeError, ValueError):
                price_f = 0.0
            if price_f > 0:
                p = {
                    **p,
                    "name": best.get("name") or p.get("name"),
                    "cost": round(price_f, 2),
                    "source": "pricebook_match",
                    "matched_pricebook_id": best.get("id"),
                    "match_ratio": round(best_ratio, 3),
                }
        out.append(p)
    return out


# ─────────────────────────────────────────────────────────────────────
# Prompt builders
# ─────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = (
    "You are a senior pool & landscape service technician working the "
    "field for a repair-focused company. You are looking at either a "
    "photograph of pool/landscape equipment or a transcript of a "
    "technician's voice memo describing the issue.\n\n"
    "Produce a repair estimate for the admin to review. Output STRICT "
    "JSON with no prose outside the JSON block. The schema is:\n\n"
    "{\n"
    "  \"parts\": [\n"
    "    {\"name\": \"<part or material>\", \"cost\": <float USD>, \"confidence\": <0-100>}\n"
    "  ],\n"
    "  \"labor_hours_estimated\": <float>,\n"
    "  \"concerns\": [\"<short concern>\", ...],\n"
    "  \"confidence\": <0-100 overall confidence>,\n"
    "  \"raw_analysis\": \"<one paragraph, plain English, what you see and what likely needs fixing>\"\n"
    "}\n\n"
    "Rules:\n"
    "* List every replacement part you would order (pump seals, motor, "
    "  cartridge, gasket, valve, salt cell, actuator, etc.).\n"
    "* Cost is your best estimate of the *part cost only* (labor is separate).\n"
    "* Never invent brand names. Prefer generic descriptions.\n"
    "* If you cannot see anything relevant, return an empty parts array and set confidence low.\n"
    "* Keep concerns short — safety, code, or warranty callouts only.\n"
    "* Never include prose outside the JSON."
)


def _photo_user_prompt(context_hint: Optional[str]) -> str:
    hint = f"\n\nContext from the admin: {context_hint.strip()}" if context_hint else ""
    return (
        "Analyze the attached photograph of pool or landscape equipment. "
        "Estimate the parts, labor hours, and concerns needed to repair it."
        + hint
    )


def _voice_user_prompt(transcript: str, context_hint: Optional[str]) -> str:
    hint = f"\n\nContext from the admin: {context_hint.strip()}" if context_hint else ""
    return (
        "A field technician recorded the following voice memo describing "
        "a pool or landscape repair. Convert this into a repair estimate.\n\n"
        f"Transcript:\n\"\"\"\n{transcript.strip()}\n\"\"\""
        + hint
    )


# ─────────────────────────────────────────────────────────────────────
# Claude Vision call (via services.llm_provider chokepoint)
# ─────────────────────────────────────────────────────────────────────
async def _call_claude_vision(*, user_text: str,
                                 image_b64: Optional[str] = None,
                                 tenant_id: Optional[str] = None,
                                 ) -> Dict[str, Any]:
    """Single Claude Sonnet 4.5 call. Returns ``{"raw_text": str}`` on
    success or ``{"error": "..."}`` on any failure.

    Phase I1.7.e · Chunk 2.b · Feb-2026 — Migrated from a direct
    ``emergentintegrations.llm.chat.LlmChat`` construction to
    :func:`services.llm_provider.call_llm_with_fallback` so this
    surface honours per-tenant BYO routing + AI spend-cap enforcement
    + ``AI_TESTMODE_MOCK``. Base64 vision is now first-class through
    the chokepoint's ``image_b64s=`` kwarg. Plaintext-response mode
    (``parse_json=False``) preserves the legacy ``raw_text`` contract
    that :func:`estimate_from_photo` and :func:`estimate_from_voice`
    parse locally via ``_extract_json``.

    Cap-exceeded surfaces as ``{"error": "ai_spend_cap_exceeded",
    "cap_exceeded": True}`` so the upstream endpoint
    (``POST /api/ai/estimate-from-photo``) can raise
    ``HTTPException(429)`` via
    :func:`services.ai.cap_http.raise_if_ai_cap_exceeded`.
    """
    if _mock_enabled():
        mock = _next_mock()
        if mock is not None:
            return {"raw_text": json.dumps(mock)}
        return {"raw_text": json.dumps({
            "parts": [{"name": "Pump seal kit", "cost": 42.50, "confidence": 82}],
            "labor_hours_estimated": 1.25,
            "concerns": ["Verify motor is not leaking under load"],
            "confidence": 78,
            "raw_analysis": "Mocked estimate — TEST_LLM_MOCK=1.",
        })}
    from services.llm_provider import call_llm_with_fallback
    from services.ai.cap_http import is_ai_cap_exceeded

    result = await call_llm_with_fallback(
        system_prompt=_SYSTEM_PROMPT,
        user_text=user_text,
        image_b64s=[image_b64] if image_b64 else None,
        provider=CLAUDE_PROVIDER,
        model=CLAUDE_MODEL,
        tenant_id=tenant_id,
        parse_json=False,
    )
    if is_ai_cap_exceeded(result):
        return {"error": "ai_spend_cap_exceeded", "cap_exceeded": True,
                 "reason": "Monthly AI spend cap exceeded for this tenant."}
    err = result.get("error")
    if err:
        # Map chokepoint error codes to the legacy shape upstream expects.
        mapping = {
            "emergent_timeout": "llm_timeout",
            "openai_empty_text": "empty_response",
            "emergent_empty_text": "empty_response",
        }
        return {"error": mapping.get(err, "llm_error"),
                 "reason": str(err)[:200]}
    text = (result.get("raw", {}) or {}).get("text") or ""
    text = text.strip()
    if not text:
        return {"error": "empty_response",
                 "reason": "Claude returned an empty response."}
    return {"raw_text": text}


# ─────────────────────────────────────────────────────────────────────
# OpenAI Whisper transcription
# ─────────────────────────────────────────────────────────────────────
async def _whisper_transcribe(audio_bytes: bytes,
                                 filename: str = "memo.webm",
                                 content_type: str = "audio/webm"
                                 ) -> Dict[str, Any]:
    """Return ``{"text": "…"}`` or ``{"error": "voice_provider_disabled"}``
    when ``OPENAI_API_KEY`` is missing. Any other Whisper failure
    surfaces as ``{"error": "whisper_error", "reason": "..."}``.
    """
    if _mock_enabled():
        mock = _next_mock()
        if isinstance(mock, dict) and mock.get("transcript"):
            return {"text": mock["transcript"]}
        return {"text": "The pool pump is leaking from the shaft seal. "
                          "It needs a new seal kit and about an hour of labor."}
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return {"error": "voice_provider_disabled",
                 "reason": "OPENAI_API_KEY not configured — the voice memo "
                            "path will re-enable automatically once the key "
                            "is added."}
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            files = {"file": (filename or "memo.webm", audio_bytes,
                              content_type or "audio/webm")}
            data = {"model": WHISPER_MODEL, "response_format": "json"}
            r = await c.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                files=files, data=data,
            )
        if r.status_code != 200:
            return {"error": "whisper_error",
                     "reason": f"HTTP {r.status_code}: {r.text[:200]}"}
        body = r.json() or {}
        text = (body.get("text") or "").strip()
        if not text:
            return {"error": "whisper_empty",
                     "reason": "Whisper returned an empty transcript."}
        return {"text": text}
    except Exception as e:
        logger.warning(f"[ai.estimate] whisper call failed: {e}")
        return {"error": "whisper_error", "reason": str(e)[:200]}


# ─────────────────────────────────────────────────────────────────────
# Public entrypoints
# ─────────────────────────────────────────────────────────────────────
async def estimate_from_photo(image_bytes: bytes, *,
                                 tenant_id: str,
                                 context_hint: Optional[str] = None,
                                 filename: Optional[str] = None,
                                 content_type: Optional[str] = None
                                 ) -> Dict[str, Any]:
    """Claude Vision → normalized estimate → pricebook fuzzy-match."""
    if not image_bytes:
        return {"error": "empty_image", "reason": "No image bytes received."}
    b64 = base64.b64encode(image_bytes).decode("ascii")
    user_text = _photo_user_prompt(context_hint)
    r = await _call_claude_vision(user_text=user_text, image_b64=b64,
                                     tenant_id=tenant_id)
    if r.get("error"):
        return r
    raw = _extract_json(r["raw_text"])
    if not raw:
        return {"error": "invalid_json",
                 "reason": "Claude response was not valid JSON.",
                 "raw_text": r.get("raw_text", "")[:500]}
    est = _normalize_estimate(raw)
    est["parts"] = await _fuzzy_match_parts(tenant_id, est["parts"])
    est["transcript"] = None
    est["provider"] = "claude"
    est["input_kind"] = "photo"
    return est


async def estimate_from_voice(audio_bytes: bytes, *,
                                 tenant_id: str,
                                 context_hint: Optional[str] = None,
                                 filename: Optional[str] = None,
                                 content_type: Optional[str] = None
                                 ) -> Dict[str, Any]:
    """Whisper → Claude → normalized estimate. Voice-provider missing
    returns ``{"error": "voice_provider_disabled"}`` immediately so the
    UI can show a graceful toast."""
    if not audio_bytes:
        return {"error": "empty_audio", "reason": "No audio bytes received."}
    w = await _whisper_transcribe(
        audio_bytes,
        filename=filename or "memo.webm",
        content_type=content_type or "audio/webm",
    )
    if w.get("error"):
        return w
    transcript = w["text"]
    user_text = _voice_user_prompt(transcript, context_hint)
    r = await _call_claude_vision(user_text=user_text, image_b64=None,
                                     tenant_id=tenant_id)
    if r.get("error"):
        return {**r, "transcript": transcript}
    raw = _extract_json(r["raw_text"])
    if not raw:
        return {"error": "invalid_json",
                 "reason": "Claude response was not valid JSON.",
                 "transcript": transcript,
                 "raw_text": r.get("raw_text", "")[:500]}
    est = _normalize_estimate(raw)
    est["parts"] = await _fuzzy_match_parts(tenant_id, est["parts"])
    est["transcript"] = transcript
    est["provider"] = "claude+whisper"
    est["input_kind"] = "voice"
    return est
