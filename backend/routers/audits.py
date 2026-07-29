"""Feb-2026 — POST /api/audits + GET /api/audits.

Zapier-fed inspection-audit receiver. Accepts arbitrary JSON payloads
from the user's inspection app via a Zap that posts to
``/api/audits`` with the shared secret header. We persist the raw
payload verbatim, extract email/name if the payload has any
recognizable variant, and best-effort link to an existing customer.

Security posture
----------------
- Auth is a simple shared-secret header equality check against
  ``LUMINO_ZAPIER_SHARED_SECRET`` (already provisioned for the
  Zapier bridge). No HMAC / timestamp / replay protection — this
  endpoint is idempotent enough that a replay only creates a
  duplicate audit row, and the Zap can be rotated at any time.
- Fail-closed when ``LUMINO_ZAPIER_SHARED_SECRET`` is empty → 503.
- Body size cap 1 MB to prevent memory-abuse.

The GET side is admin-only and never accepts the shared secret.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import db
from utils import require_admin

router = APIRouter()
log = logging.getLogger("audits")

_MAX_BODY_BYTES = 1_048_576  # 1 MB


# ── Response models (for openapi.json clarity) ─────────────────────
class AuditPostResponse(BaseModel):
    ok: bool
    audit_id: str
    linked_customer_id: Optional[str] = None
    match_type: Optional[str] = None  # "email" | "name" | None


class AuditItem(BaseModel):
    id: str
    received_at: datetime
    raw_payload: Dict[str, Any]
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    linked_customer_id: Optional[str] = None
    linked_job_id: Optional[str] = None
    source: str
    tenant_id: Optional[str] = None


class AuditListResponse(BaseModel):
    items: List[AuditItem]
    total: int


# ── Helpers ─────────────────────────────────────────────────────────
def _shared_secret() -> str:
    v = (os.environ.get("LUMINO_ZAPIER_SHARED_SECRET") or "").strip()
    # Same placeholder guard as the Zapier bridge — treat REPLACE_ME_*
    # values as "not configured" so preview fails closed loudly.
    if v.startswith("REPLACE_ME_"):
        return ""
    return v


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Candidate keys — most-common first. Case is preserved as-is because
# Zap payloads sometimes only match snake_case AND camelCase; we
# scan both.
_EMAIL_KEYS = (
    "customer_email", "customerEmail", "email",
    "customerEmailAddress", "emailAddress",
)
_NAME_KEYS = (
    "customer_name", "customerName", "name",
    "customerFullName", "fullName",
)
_ENVELOPE_KEYS = ("data", "customer", "inspection", "payload")


def _pick(body: Dict[str, Any], keys) -> Optional[str]:
    for k in keys:
        v = body.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _extract_email(body: Dict[str, Any]) -> Optional[str]:
    """Look at top-level + one level of common envelopes.
    Return the first truthy string, lowercased."""
    hit = _pick(body, _EMAIL_KEYS)
    if not hit:
        for env in _ENVELOPE_KEYS:
            inner = body.get(env)
            if isinstance(inner, dict):
                hit = _pick(inner, _EMAIL_KEYS)
                if hit:
                    break
    return hit.lower() if hit else None


def _extract_name(body: Dict[str, Any]) -> Optional[str]:
    hit = _pick(body, _NAME_KEYS)
    if not hit:
        for env in _ENVELOPE_KEYS:
            inner = body.get(env)
            if isinstance(inner, dict):
                hit = _pick(inner, _NAME_KEYS)
                if hit:
                    break
    return hit


async def _match_customer(email: Optional[str], name: Optional[str]) -> tuple:
    """Return (linked_customer_id, tenant_id, match_type).
    match_type is "email", "name", or None.
    Ambiguous matches (>1 row) → None."""
    if email:
        # Case-insensitive equality on the email column. Anchored regex
        # avoids surface substring matches (e.g. "jane@x.com" matching
        # "jane@x.com.mx").
        pattern = f"^{_regex_escape(email)}$"
        rows = await db.customers.find(
            {"email": {"$regex": pattern, "$options": "i"}},
            {"_id": 0, "id": 1, "tenant_id": 1},
        ).to_list(3)
        if len(rows) == 1:
            r = rows[0]
            return r.get("id"), r.get("tenant_id"), "email"
        if len(rows) > 1:
            log.warning("audits: ambiguous email match for %r (n=%d) — "
                         "leaving unlinked", email, len(rows))
            return None, None, None
    if name:
        pattern = f"^{_regex_escape(name.strip())}$"
        rows = await db.customers.find(
            {"name": {"$regex": pattern, "$options": "i"}},
            {"_id": 0, "id": 1, "tenant_id": 1},
        ).to_list(3)
        if len(rows) == 1:
            r = rows[0]
            return r.get("id"), r.get("tenant_id"), "name"
        if len(rows) > 1:
            log.warning("audits: ambiguous name match for %r (n=%d) — "
                         "leaving unlinked", name, len(rows))
            return None, None, None
    return None, None, None


def _regex_escape(s: str) -> str:
    """Escape user-controlled string for use in a MongoDB $regex.
    Uses Python's re.escape which produces PCRE-safe output."""
    import re as _re
    return _re.escape(s)


def _redact_for_log(body: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow-redact obvious secret-shaped values before logging.
    Never mutates the caller's dict."""
    banned_prefixes = ("sk_", "whsec_", "rk_", "Bearer ", "AKIA")
    out: Dict[str, Any] = {}
    for k, v in (body or {}).items():
        if isinstance(v, str):
            if k.lower() == "authorization" or any(v.startswith(p) for p in banned_prefixes):
                out[k] = f"<redacted len={len(v)}>"
                continue
        out[k] = v
    return out


# ── POST /audits — Zap-signed receiver ─────────────────────────────
@router.post("/audits", response_model=AuditPostResponse)
async def receive_audit(request: Request):
    """Zapier-fed inspection audit receiver.

    Auth: header ``x-zapier-shared-secret`` must equal env
    ``LUMINO_ZAPIER_SHARED_SECRET``.

    Body: any JSON object (max 1 MB). Persisted verbatim to the
    ``audits`` collection with a best-effort customer link.
    """
    # 1. Auth — same fail-closed pattern as the Zapier bridge.
    expected = _shared_secret()
    if not expected:
        return JSONResponse(status_code=503, content={"error": "not_configured"})
    got = (request.headers.get("x-zapier-shared-secret") or "").strip()
    if not got or got != expected:
        return JSONResponse(status_code=401, content={"error": "unauthorized"})

    # 2. Size cap — check Content-Length header first, then bounded read.
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > _MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"error": "too_large"})
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"error": "too_large"})

    # 3. Parse JSON — must be an object.
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"error": "invalid_json"})
    if not isinstance(parsed, dict):
        return JSONResponse(status_code=400, content={"error": "not_json_object"})

    # 4. Extract customer fields (permissive, envelope-aware).
    email = _extract_email(parsed)
    name = _extract_name(parsed)

    # 5. Match against customers collection.
    linked_customer_id, tenant_id, match_type = await _match_customer(email, name)

    # 6. Persist.
    audit_id = uuid.uuid4().hex
    doc = {
        "id": audit_id,
        "received_at": _now(),
        "raw_payload": parsed,
        "customer_email": email,
        "customer_name": name,
        "linked_customer_id": linked_customer_id,
        "linked_job_id": None,
        "source": "zapier",
        "tenant_id": tenant_id,
    }
    try:
        await db.audits.insert_one(dict(doc))
    except Exception as exc:                                          # noqa: BLE001
        log.error("audits: insert failed audit_id=%s err=%s",
                    audit_id, type(exc).__name__)
        return JSONResponse(status_code=500,
                             content={"error": "persist_failed"})

    log.info("audits: received id=%s linked=%s match_type=%s payload_keys=%s",
              audit_id, bool(linked_customer_id), match_type,
              sorted(_redact_for_log(parsed).keys())[:20])

    return AuditPostResponse(
        ok=True,
        audit_id=audit_id,
        linked_customer_id=linked_customer_id,
        match_type=match_type,
    )


# ── GET /audits — admin read side ──────────────────────────────────
@router.get("/audits", response_model=AuditListResponse)
async def list_audits(
    limit: int = 50,
    offset: int = 0,
    linked_customer_id: Optional[str] = None,
    has_link: Optional[bool] = None,
    _admin: dict = Depends(require_admin),
):
    """Admin-only paginated read side. Sorted by received_at desc."""
    limit = max(1, min(200, int(limit)))
    offset = max(0, int(offset))
    q: Dict[str, Any] = {}
    if linked_customer_id:
        q["linked_customer_id"] = linked_customer_id
    if has_link is True:
        q["linked_customer_id"] = {"$ne": None}
    elif has_link is False:
        q["linked_customer_id"] = None
    total = await db.audits.count_documents(q)
    rows = await (
        db.audits.find(q, {"_id": 0})
        .sort("received_at", -1)
        .skip(offset)
        .limit(limit)
        .to_list(limit)
    )
    return {"items": rows, "total": total}
