"""Phase 54h-a · Aug-2026 — Supplier session store.

Wraps the ``supplier_sessions`` collection with a thin async API
used by:

  * ``POST /api/suppliers/{slug}/sessions`` — operator uploads cookies
    obtained via the Phase 54h-b bookmarklet.
  * ``GET  /api/suppliers/{slug}/sessions/status`` — banner countdown.
  * ``DELETE /api/suppliers/{slug}/sessions`` — force re-challenge.
  * Connectors (Pool360 / SiteOne / Heritage) call
    ``get_active_session`` before their scripted login as a
    rehydration attempt.

Encryption: reuses the SAME ``services.suppliers.crypto`` Fernet key
that guards ``supplier_credentials``. No new key namespace.

Session shape stored in Mongo:
  * ``id``                       — uuid
  * ``tenant_id``                — tenant guard
  * ``supplier_slug``            — one row per tenant per supplier
  * ``encrypted_cookies``        — Fernet-wrapped JSON string
  * ``expires_at``               — ISO string, TTL = 30 min by default
  * ``established_at``           — ISO of upload
  * ``established_by_user_id``   — operator audit trail
  * ``created_at`` / ``updated_at``
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db, logger
from services.suppliers.crypto import decrypt, encrypt


DEFAULT_TTL_MINUTES = 30
_INDEX_ENSURED = False


def _now() -> datetime: return datetime.now(timezone.utc)
def _now_iso() -> str: return _now().isoformat()


async def ensure_index() -> None:
    """Idempotent — unique on (tenant_id, supplier_slug). Called
    lazily from every helper on first hit so the collection is safe
    to use even before the boot-time seed runs."""
    global _INDEX_ENSURED
    if _INDEX_ENSURED:
        return
    try:
        await db.supplier_sessions.create_index(
            [("tenant_id", 1), ("supplier_slug", 1)],
            unique=True, name="tenant_slug_uniq",
        )
        _INDEX_ENSURED = True
    except Exception as e:                                        # noqa: BLE001
        logger.warning(f"[supplier_sessions] ensure_index failed: {e}")


async def upsert_session(
    tenant_id: str,
    supplier_slug: str,
    cookies: List[Dict[str, Any]],
    user_id: Optional[str] = None,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> Dict[str, Any]:
    """Encrypt + upsert. Returns ``{expires_at, cookie_count}``."""
    await ensure_index()
    if not isinstance(cookies, list):
        raise ValueError("cookies must be a list of cookie dicts")
    encrypted = encrypt(json.dumps(cookies))
    now = _now()
    expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat()
    now_iso = now.isoformat()
    existing = await db.supplier_sessions.find_one(
        {"tenant_id": tenant_id, "supplier_slug": supplier_slug},
        {"_id": 0, "id": 1, "created_at": 1},
    )
    doc = {
        "tenant_id": tenant_id,
        "supplier_slug": supplier_slug,
        "encrypted_cookies": encrypted,
        "expires_at": expires_at,
        "established_at": now_iso,
        "established_by_user_id": user_id,
        "updated_at": now_iso,
    }
    if existing:
        doc["id"] = existing["id"]
        doc["created_at"] = existing.get("created_at") or now_iso
        await db.supplier_sessions.update_one(
            {"tenant_id": tenant_id, "supplier_slug": supplier_slug},
            {"$set": doc},
        )
    else:
        doc["id"] = uuid.uuid4().hex
        doc["created_at"] = now_iso
        await db.supplier_sessions.insert_one(doc)
    return {"expires_at": expires_at, "cookie_count": len(cookies)}


async def get_active_session(
    tenant_id: str, supplier_slug: str,
) -> Optional[List[Dict[str, Any]]]:
    """Return the decrypted cookie list if a row exists and hasn't
    expired. Returns ``None`` in every other case (missing row,
    expired row, decrypt failure — the caller falls through to the
    scripted login flow)."""
    await ensure_index()
    row = await db.supplier_sessions.find_one(
        {"tenant_id": tenant_id, "supplier_slug": supplier_slug},
        {"_id": 0},
    )
    if not row:
        return None
    if not _still_valid(row.get("expires_at")):
        return None
    plain = decrypt(row.get("encrypted_cookies"))
    if not plain:
        return None
    try:
        cookies = json.loads(plain)
    except (ValueError, TypeError):
        return None
    return cookies if isinstance(cookies, list) else None


async def session_status(
    tenant_id: str, supplier_slug: str,
) -> Dict[str, Any]:
    """Shape returned by ``GET .../sessions/status``. Always safe
    to call — never raises for the missing-row case."""
    await ensure_index()
    row = await db.supplier_sessions.find_one(
        {"tenant_id": tenant_id, "supplier_slug": supplier_slug},
        {"_id": 0, "expires_at": 1},
    )
    if not row or not _still_valid(row.get("expires_at")):
        return {"has_active_session": False,
                "expires_at": None, "minutes_remaining": None}
    expires_at = row["expires_at"]
    remaining = max(0, int(
        (_parse_iso(expires_at) - _now()).total_seconds() // 60,
    ))
    return {"has_active_session": True,
             "expires_at": expires_at,
             "minutes_remaining": remaining}


async def delete_session(
    tenant_id: str, supplier_slug: str,
) -> int:
    """Idempotent — returns the number of rows deleted (0 or 1)."""
    await ensure_index()
    result = await db.supplier_sessions.delete_one(
        {"tenant_id": tenant_id, "supplier_slug": supplier_slug},
    )
    return int(getattr(result, "deleted_count", 0) or 0)


# ─── Internal helpers ───────────────────────────────────────────────────
def _parse_iso(s: Optional[str]) -> datetime:
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _still_valid(expires_at: Optional[str]) -> bool:
    return _parse_iso(expires_at) > _now()
