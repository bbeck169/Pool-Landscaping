"""MA2 · Feb-2026 — POST /audio/transcribe.

Thin FastAPI adapter that accepts a multipart-uploaded audio file
from the mobile FAB, forwards the bytes to OpenAI Whisper via the
existing helper in ``services.ai.estimate_from_media._whisper_transcribe``,
and returns the transcript for MARCO to parse (via
``POST /api/marco/execute``).

Contract
────────
    POST /audio/transcribe?language=<optional>
    Content-Type: multipart/form-data
    Auth:  require_tech_or_above  (tenant-scoped)
    Body:  file (audio file: m4a, mp3, wav, webm, ogg — up to 25 MB)

    Response 200 (happy):
        {
          "transcript": "<transcribed text>",
          "language":   "en" | null,   # echoed from the query param
          "duration_sec": null,        # see note below
          "model":      "whisper-1"
        }

    Error responses (structured detail — client renders friendly toast):
      * 400 UNSUPPORTED_CONTENT_TYPE  — mime not in the whitelist
      * 400 EMPTY_FILE                — 0-byte upload
      * 413 AUDIO_TOO_LARGE           — >25 MB
      * 422 (FastAPI)                 — no ``file`` field supplied
      * 500 WHISPER_CONFIG_ERROR      — OPENAI_API_KEY missing / provider disabled
      * 502 WHISPER_UPSTREAM_ERROR    — Whisper HTTP failure or empty transcript
      * 401/403                       — auth gate (require_tech_or_above)

Notes
─────
* ``duration_sec`` is intentionally ``null`` in v1. The reused helper
  uses Whisper's ``response_format="json"`` (not ``verbose_json``),
  so duration metadata is not returned. Ruling a1 on this dispatch:
  don't widen the helper touch surface for optional metadata. If a
  downstream flow ever needs real duration, flip the helper to
  ``verbose_json`` in a follow-up commit.
* ``language`` on the query param is threaded into Whisper's form
  data via the ``language`` kwarg added to ``_whisper_transcribe`` in
  this same commit (ruling b1). When ``None``, Whisper auto-detects.
* Size cap is enforced server-side per Ruling c1 (413 per REST spec,
  new endpoint = new contract; walkie.py's legacy 400 stays as-is).
* The tenant dep is injected for middleware-level tenant validation
  even though the endpoint is stateless (no DB writes). Matches the
  MA0 / MA1 auth model.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from routers.pool_calculators import require_tech_or_above
from routers.tenants import get_current_tenant
from services.ai.estimate_from_media import (
    WHISPER_MODEL,
    _whisper_transcribe,
)


router = APIRouter()


# ── Config ──────────────────────────────────────────────────────────
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB · Whisper's own upload cap.
ALLOWED_AUDIO_MIMES = frozenset({
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/webm",
    "audio/x-m4a",
    "audio/ogg",
})


# ── Endpoint ────────────────────────────────────────────────────────
@router.post("/audio/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: Optional[str] = Query(
        default=None,
        max_length=8,
        description="Optional ISO-639-1 language hint threaded to "
                    "Whisper (e.g. 'en', 'es'). When omitted, Whisper "
                    "auto-detects.",
    ),
    user: dict = Depends(require_tech_or_above),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    # ── validate content-type ────────────────────────────────────
    content_type = (file.content_type or "").lower().strip()
    if content_type not in ALLOWED_AUDIO_MIMES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "UNSUPPORTED_CONTENT_TYPE",
                "message": f"Content-type {content_type!r} is not "
                            f"supported. Allowed: {sorted(ALLOWED_AUDIO_MIMES)}.",
            },
        )

    # ── read bytes + validate size ───────────────────────────────
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EMPTY_FILE",
                "message": "Uploaded file is empty.",
            },
        )
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "AUDIO_TOO_LARGE",
                "message": f"Audio exceeds the {MAX_AUDIO_BYTES // (1024 * 1024)} MB cap.",
            },
        )

    # ── invoke Whisper via reused helper ─────────────────────────
    result = await _whisper_transcribe(
        data,
        filename=file.filename or "memo.webm",
        content_type=content_type,
        language=language,
    )

    # ── map helper errors → HTTP surface ─────────────────────────
    err = result.get("error")
    if err == "voice_provider_disabled":
        raise HTTPException(
            status_code=500,
            detail={
                "code": "WHISPER_CONFIG_ERROR",
                "message": "Whisper provider is not configured on "
                            "the server. Ask an admin to set the API key.",
            },
        )
    if err in ("whisper_error", "whisper_empty"):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "WHISPER_UPSTREAM_ERROR",
                "message": "Whisper couldn't transcribe this audio. "
                            "Please try again.",
                "reason": result.get("reason", "")[:200],
            },
        )
    if err:
        # Defence-in-depth: unknown error surface.
        raise HTTPException(
            status_code=502,
            detail={
                "code": "WHISPER_UPSTREAM_ERROR",
                "message": "Unexpected transcription error.",
                "reason": str(err)[:200],
            },
        )

    # ── happy path ───────────────────────────────────────────────
    return {
        "transcript": result.get("text") or "",
        "language": language,
        "duration_sec": None,  # See module docstring — ruling a1.
        "model": WHISPER_MODEL,
    }
