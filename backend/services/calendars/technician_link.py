"""Phase I1.7.c.3 · Feb-2026 — Per-technician calendar OAuth link store.

Persists ``(tenant_id, technician_user_id, provider_key)`` rows in
Mongo. Access/refresh tokens are stored encrypted-at-rest via
``services.secrets`` — this module ONLY persists the plaintext
metadata (calendar_id, connected_email, sync_token, expires_at).

Secret key convention::

    services.secrets.put_secret(
        tenant_id, f"{provider_key}:{technician_user_id}",
        json.dumps({"access_token": ..., "refresh_token": ...}),
        ...
    )
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from services.secrets import get_secret, put_secret, remove_secret
from services.secrets.models import ConnectionType

from ._helpers import now_iso
from .models import (
    TechnicianCalendarLinkSummary,
)


COLLECTION = "technician_calendar_link"


def _default_db():
    from config import db
    return db


def _secret_key(provider_key: str, technician_user_id: str) -> str:
    return f"{provider_key}:{technician_user_id}"


async def ensure_indexes(db=None) -> None:
    if db is None:
        db = _default_db()
    await db[COLLECTION].create_index(
        [("tenant_id", 1), ("technician_user_id", 1), ("provider_key", 1)],
        unique=True, name="tcl_tenant_tech_provider_uniq",
    )


async def upsert_link(
    *, tenant_id: str, technician_user_id: str,
    provider_key: str, provider: str,
    tokens: Dict[str, Any],
    connected_email: Optional[str] = None,
    calendar_id: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """Persist a per-technician link. Tokens are pushed through the
    encrypted secrets store; the plaintext row keeps only the
    non-secret metadata + a masked ``last_4`` on the access token.
    """
    if db is None:
        db = _default_db()
    access = str(tokens.get("access_token") or "")
    refresh = tokens.get("refresh_token")
    expires_at = tokens.get("expires_at")
    blob = json.dumps({
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": expires_at,
    }, separators=(",", ":"))
    await put_secret(
        tenant_id,
        _secret_key(provider_key, technician_user_id),
        blob,
        connection_type=ConnectionType.OAUTH,
        connected_account_id=connected_email,
        mask_source=access,
        db=db,
    )
    now = now_iso()
    set_fields: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "technician_user_id": technician_user_id,
        "provider_key": provider_key,
        "provider": provider,
        "connected_email": connected_email,
        "calendar_id": calendar_id or "primary",
        "expires_at": expires_at,
        "updated_at": now,
    }
    await db[COLLECTION].update_one(
        {"tenant_id": tenant_id, "technician_user_id": technician_user_id,
            "provider_key": provider_key},
        {"$set": set_fields,
            "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now,
                             "sync_token": None}},
        upsert=True,
    )
    row = await db[COLLECTION].find_one(
        {"tenant_id": tenant_id, "technician_user_id": technician_user_id,
            "provider_key": provider_key}, {"_id": 0},
    )
    return row or {}


async def get_link(
    *, tenant_id: str, technician_user_id: str,
    provider_key: str, db=None,
) -> Optional[Dict[str, Any]]:
    if db is None:
        db = _default_db()
    return await db[COLLECTION].find_one(
        {"tenant_id": tenant_id, "technician_user_id": technician_user_id,
            "provider_key": provider_key}, {"_id": 0},
    )


async def get_tokens_for(
    *, tenant_id: str, technician_user_id: str,
    provider_key: str, db=None,
) -> Optional[Dict[str, Any]]:
    """Decrypt + return the token JSON blob. Adapters use this on
    every push/pull. Never crosses the HTTP boundary."""
    pt = await get_secret(
        tenant_id, _secret_key(provider_key, technician_user_id), db=db,
    )
    if not pt:
        return None
    try:
        return json.loads(pt)
    except Exception:
        return None


async def remove_link(
    *, tenant_id: str, technician_user_id: str,
    provider_key: str, db=None,
) -> bool:
    if db is None:
        db = _default_db()
    res = await db[COLLECTION].delete_one(
        {"tenant_id": tenant_id, "technician_user_id": technician_user_id,
            "provider_key": provider_key},
    )
    await remove_secret(
        tenant_id, _secret_key(provider_key, technician_user_id), db=db,
    )
    return res.deleted_count > 0


async def list_links_for_tenant(
    *, tenant_id: str, provider_key: Optional[str] = None,
    db=None,
) -> List[Dict[str, Any]]:
    if db is None:
        db = _default_db()
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if provider_key:
        q["provider_key"] = provider_key
    out: List[Dict[str, Any]] = []
    async for row in db[COLLECTION].find(q, {"_id": 0}):
        out.append(row)
    return out


async def update_sync_token(
    *, tenant_id: str, technician_user_id: str,
    provider_key: str, next_token: Optional[str],
    db=None,
) -> None:
    if db is None:
        db = _default_db()
    await db[COLLECTION].update_one(
        {"tenant_id": tenant_id, "technician_user_id": technician_user_id,
            "provider_key": provider_key},
        {"$set": {"sync_token": next_token, "updated_at": now_iso()}},
    )


def summary_from_row(
    row: Dict[str, Any], *,
    technician_name: Optional[str] = None,
    technician_email: Optional[str] = None,
) -> TechnicianCalendarLinkSummary:
    return TechnicianCalendarLinkSummary(
        technician_user_id=row.get("technician_user_id", ""),
        technician_name=technician_name,
        technician_email=technician_email,
        provider_key=row.get("provider_key", ""),
        provider=row.get("provider", ""),
        connected=bool(row.get("expires_at") or row.get("calendar_id")),
        connected_email=row.get("connected_email"),
        calendar_id=row.get("calendar_id"),
        last_synced_at=row.get("last_synced_at"),
        updated_at=row.get("updated_at"),
    )
