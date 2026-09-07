"""Phase I1.7.d · Feb-2026 — tenant_provider_health persistence.

Schema (indexed on ``(tenant_id, provider_key)``):

  {
    tenant_id: str,
    provider_key: str,          # e.g. "ai_openai", "maps_google", ...
    status: "ok" | "failed" | "unknown",
    checked_at: iso8601,
    last_error: Optional[str],   # short public string, no secrets
    consecutive_failures: int,   # resets to 0 on success
    last_ok_at: Optional[iso8601],
    updated_at: iso8601,
  }
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


HEALTH_COLLECTION = "tenant_provider_health"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_db():
    from config import db
    return db


async def record_probe(
    *, tenant_id: str, provider_key: str,
    ok: bool, message: str = "",
    db=None,
) -> Dict[str, Any]:
    """Idempotent upsert. Increments ``consecutive_failures`` on
    failure and resets it on success. Never stores secret material —
    callers are responsible for redacting ``message``.
    """
    if db is None:
        db = _default_db()
    now = _now_iso()
    existing = await db[HEALTH_COLLECTION].find_one(
        {"tenant_id": tenant_id, "provider_key": provider_key},
        {"_id": 0, "consecutive_failures": 1, "last_ok_at": 1},
    )
    prev_fail = int((existing or {}).get("consecutive_failures", 0) or 0)
    if ok:
        status = "ok"
        consecutive = 0
        last_ok = now
        last_err = None
    else:
        status = "failed"
        consecutive = prev_fail + 1
        last_ok = (existing or {}).get("last_ok_at")
        last_err = (message or "")[:200]  # cap length; upstream must redact
    set_fields: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "provider_key": provider_key,
        "status": status,
        "checked_at": now,
        "last_error": last_err,
        "consecutive_failures": consecutive,
        "last_ok_at": last_ok,
        "updated_at": now,
    }
    await db[HEALTH_COLLECTION].update_one(
        {"tenant_id": tenant_id, "provider_key": provider_key},
        {"$set": set_fields, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return set_fields


async def upsert_health(
    *, tenant_id: str, provider_key: str,
    status: str, message: str = "",
    db=None,
) -> Dict[str, Any]:
    """Explicit setter (used by tests). ``status`` is one of
    ``ok|failed|unknown``. Does NOT mutate ``consecutive_failures`` —
    that's ``record_probe``'s job.
    """
    if db is None:
        db = _default_db()
    now = _now_iso()
    set_fields: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "provider_key": provider_key,
        "status": status,
        "checked_at": now,
        "last_error": (message or None) if status != "ok" else None,
        "updated_at": now,
    }
    await db[HEALTH_COLLECTION].update_one(
        {"tenant_id": tenant_id, "provider_key": provider_key},
        {"$set": set_fields, "$setOnInsert": {
            "created_at": now,
            "consecutive_failures": 0 if status == "ok" else 1,
        }},
        upsert=True,
    )
    return set_fields


async def get_health(
    *, tenant_id: str, provider_key: str, db=None,
) -> Optional[Dict[str, Any]]:
    if db is None:
        db = _default_db()
    return await db[HEALTH_COLLECTION].find_one(
        {"tenant_id": tenant_id, "provider_key": provider_key},
        {"_id": 0},
    )


async def get_health_map_for_tenant(
    *, tenant_id: str, db=None,
) -> Dict[str, Dict[str, Any]]:
    """Return ``{provider_key: row}`` for every provider tracked
    for this tenant. Used by ``GET /integrations`` to hydrate health
    dots without N round-trips.
    """
    if db is None:
        db = _default_db()
    out: Dict[str, Dict[str, Any]] = {}
    async for row in db[HEALTH_COLLECTION].find(
        {"tenant_id": tenant_id}, {"_id": 0}
    ):
        pk = row.get("provider_key")
        if pk:
            out[pk] = row
    return out


async def list_connected_provider_keys_for_tenant(
    *, tenant_id: str, db=None,
) -> List[str]:
    """Return the list of provider keys the tenant has a persisted
    secret / OAuth token / metadata sidecar for. Used by the cron
    to decide which providers to probe for each tenant.

    Combines:
      * ``tenant_secrets``      — sms/email/ai/maps/payments-byo BYO keys
      * ``tenant_ai_provider``  — AI meta rows (defensive)
      * ``tenant_maps_provider``
      * ``tenant_payments_provider``
      * ``tenant_calendars_technician_links`` — per-tech OAuth for calendars
    """
    if db is None:
        db = _default_db()
    keys: set[str] = set()
    async for row in db["tenant_secrets"].find(
        {"tenant_id": tenant_id}, {"_id": 0, "provider_key": 1},
    ):
        pk = row.get("provider_key")
        if pk:
            keys.add(pk)
    # Calendars store per-technician links, no top-level secret row —
    # infer from the link collection.
    try:
        async for row in db["tenant_calendars_technician_links"].find(
            {"tenant_id": tenant_id}, {"_id": 0, "provider_key": 1},
        ):
            pk = row.get("provider_key")
            if pk:
                keys.add(pk)
    except Exception:
        pass
    return sorted(keys)


async def ensure_indexes(db=None) -> None:
    if db is None:
        db = _default_db()
    await db[HEALTH_COLLECTION].create_index(
        [("tenant_id", 1), ("provider_key", 1)], unique=True,
    )
