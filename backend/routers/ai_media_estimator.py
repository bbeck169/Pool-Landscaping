"""Feb-2026 · Phase 25 · AI Photo/Voice → Repair Estimate router.

Exposes:

* ``POST /api/ai/estimate-from-photo`` — multipart image upload → Claude
  vision → normalized estimate + pricebook fuzzy-match.
* ``POST /api/ai/estimate-from-voice`` — multipart audio upload →
  Whisper transcription → Claude → normalized estimate + pricebook
  fuzzy-match. Gracefully degrades to ``voice_provider_disabled`` when
  ``OPENAI_API_KEY`` is missing.

Guardrails
----------
* **Admin + super_admin only.** Techs get 403 — pricing surface, matches
  the Repair Calculator's RBAC rules.
* **Rate limit** ``RATE_LIMIT_PER_HOUR`` (20) per (user, endpoint), based
  on ``ai_estimate_generations.created_at``.
* **Cost tracking** — every call, success or failure, writes a row to
  ``ai_estimate_generations`` so we can audit spend later.
* **File size cap** ``MAX_UPLOAD_BYTES`` (12 MB) — the frontend also
  enforces 10 MB; the 2 MB slack handles headers + base64 growth.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from config import db, logger
from utils import get_current_user, now_iso, new_id
from services.ai import estimate_from_media as _svc


router = APIRouter(tags=["AI Repair Estimator"])

RATE_LIMIT_PER_HOUR = 20
MAX_UPLOAD_BYTES = 12 * 1024 * 1024  # 12 MB (frontend enforces 10)
ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/heic", "image/heif",
                        "image/webp"}
ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg",
                        "audio/mp3", "audio/wav", "audio/x-wav", "audio/x-m4a",
                        "audio/m4a", "audio/aac"}


def _admin_or_403(user: dict) -> None:
    if (user or {}).get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")


async def _rate_limit_or_429(tenant_id: str, user_id: str, endpoint: str) -> None:
    """Sliding-window 1h rate limit per (user, endpoint)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    n = await db.ai_estimate_generations.count_documents({
        "tenant_id": tenant_id,
        "user_id": user_id,
        "endpoint": endpoint,
        "created_at": {"$gte": since},
    })
    if n >= RATE_LIMIT_PER_HOUR:
        raise HTTPException(
            429, f"Rate limit reached ({RATE_LIMIT_PER_HOUR}/hour). "
                    "Try again in a bit.")


async def _log_generation(*, tenant_id: str, user_id: str, endpoint: str,
                             filename: Optional[str], content_type: Optional[str],
                             byte_size: int, result: Dict[str, Any]) -> str:
    gid = new_id()
    await db.ai_estimate_generations.insert_one({
        "id": gid,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "endpoint": endpoint,
        "created_at": now_iso(),
        "filename": filename,
        "content_type": content_type,
        "byte_size": byte_size,
        "provider": result.get("provider"),
        "error": result.get("error"),
        "error_reason": result.get("reason"),
        "parts_count": len(result.get("parts") or []),
        "labor_hours_estimated": result.get("labor_hours_estimated"),
        "confidence": result.get("confidence"),
        "matched_from_pricebook_count": sum(
            1 for p in (result.get("parts") or [])
            if p.get("source") == "pricebook_match"
        ),
    })
    return gid


def _handoff_url() -> str:
    return "/ops/repair-calculator"


@router.post("/ai/estimate-from-photo", operation_id="ai.estimateFromPhoto")
async def estimate_from_photo(
    file: UploadFile = File(..., description="Pool/landscape equipment photo (JPEG/PNG/HEIC/WebP, max 10MB)"),
    context_hint: Optional[str] = Form(
        default=None,
        description="Optional short admin note giving extra context (e.g. 'pump leaking under load')."),
    user: Dict[str, Any] = Depends(get_current_user),
):
    _admin_or_403(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "Missing tenant_id")

    ct = (file.content_type or "").lower()
    if ct and ct not in ALLOWED_PHOTO_TYPES:
        raise HTTPException(415,
                              f"Unsupported image type: {ct}. Allowed: "
                              f"{', '.join(sorted(ALLOWED_PHOTO_TYPES))}.")

    await _rate_limit_or_429(tenant_id, user.get("id") or "?", "photo")

    body = await file.read()
    if not body:
        raise HTTPException(422, "Empty file upload.")
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(413,
                              f"File too large ({len(body):,} bytes). "
                              f"Max is {MAX_UPLOAD_BYTES // (1024*1024)} MB.")

    result = await _svc.estimate_from_photo(
        body, tenant_id=tenant_id,
        context_hint=context_hint,
        filename=file.filename, content_type=ct or None,
    )
    gid = await _log_generation(
        tenant_id=tenant_id, user_id=user.get("id") or "?",
        endpoint="photo", filename=file.filename,
        content_type=ct, byte_size=len(body), result=result,
    )
    result["generation_id"] = gid
    result["handoff_url"] = _handoff_url()
    if result.get("error"):
        # Return 200 with a structured error so the frontend can render
        # a specific error banner without a top-level HTTP failure that
        # would leak into a "Network error" toast.
        result.setdefault("parts", [])
        result.setdefault("labor_hours_estimated", 0.0)
        result.setdefault("concerns", [])
        result.setdefault("confidence", 0)
    return result


@router.post("/ai/estimate-from-voice", operation_id="ai.estimateFromVoice")
async def estimate_from_voice(
    file: UploadFile = File(..., description="Voice memo (webm/ogg/mp4/mp3/wav/m4a, max 10MB)"),
    context_hint: Optional[str] = Form(default=None),
    user: Dict[str, Any] = Depends(get_current_user),
):
    _admin_or_403(user)
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "Missing tenant_id")

    ct = (file.content_type or "").lower()
    # We accept unknown audio types too — browsers sometimes send
    # ``application/octet-stream`` for MediaRecorder blobs — but bounce
    # obvious wrong types.
    if ct and ct.startswith("image/"):
        raise HTTPException(415, f"Expected audio, got {ct}.")

    await _rate_limit_or_429(tenant_id, user.get("id") or "?", "voice")

    body = await file.read()
    if not body:
        raise HTTPException(422, "Empty file upload.")
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(413,
                              f"File too large ({len(body):,} bytes). "
                              f"Max is {MAX_UPLOAD_BYTES // (1024*1024)} MB.")

    result = await _svc.estimate_from_voice(
        body, tenant_id=tenant_id,
        context_hint=context_hint,
        filename=file.filename, content_type=ct or None,
    )
    gid = await _log_generation(
        tenant_id=tenant_id, user_id=user.get("id") or "?",
        endpoint="voice", filename=file.filename,
        content_type=ct, byte_size=len(body), result=result,
    )
    result["generation_id"] = gid
    result["handoff_url"] = _handoff_url()
    if result.get("error"):
        result.setdefault("parts", [])
        result.setdefault("labor_hours_estimated", 0.0)
        result.setdefault("concerns", [])
        result.setdefault("confidence", 0)
        result.setdefault("transcript", None)
    return result
