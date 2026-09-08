"""Phase 40 · Idempotency-key middleware helper.

When a client sends `X-Idempotency-Key: <uuid>` on a mutating endpoint,
we cache the first response in `idempotency_keys` and short-circuit
duplicate replays for 48 hours (Phase O4 — bumped from 24h so a weekend
tech coming back online after ~40h of accumulated writes still hits the
cached responses instead of double-triggering side effects).

Only endpoints that opt in (by calling `check_and_reserve` +
`store_response`) participate — everything else remains fire-and-forget.

Phase O4 · Feb-2026 — Backend Idempotency Sprint hardened this helper:
  * TTL bumped 24h → 48h (constant below).
  * ``expires_at`` is now persisted as a real ``datetime`` so the
    Mongo TTL index (created by
    ``services.migrations.idempotency_keys_indexes``) can auto-GC
    expired rows.
  * Unique compound index on ``(tenant_id, key, endpoint)`` closes
    the race window in ``store_response``'s upsert.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

from fastapi import Request

from config import db
from utils import now_iso, new_id

# Phase O4 · Feb-2026 — bumped from 24h to 48h to cover weekend tech
# offline windows without pushing so far out that body-fingerprint
# staleness becomes a real risk.
# Mobile Phase 2 · Feb-2026 — bumped again 48h → 72h. Confirmed by
# the mobile agent as the longest realistic offline window a field
# tech accumulates (Fri-morning outage → Mon-morning reconnect).
# The 72h ceiling still keeps body-fingerprint staleness inside the
# tolerable band because writes older than that are dominated by
# schema drift risks the mobile client's own upgrade-check catches.
TTL_SECONDS = 72 * 60 * 60


def _fingerprint(body: Any) -> str:
    try:
        s = json.dumps(body or {}, sort_keys=True, default=str)
    except Exception:
        s = repr(body)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


async def replay_or_reserve(
    request: Request, tenant_id: str, endpoint: str, body: Any,
) -> Tuple[Optional[str], Optional[Any]]:
    """Look up the incoming `X-Idempotency-Key`. Returns `(key, cached_response)`.

    * `(None, None)`  → no header; caller should proceed normally.
    * `(key, None)`   → new key; caller should execute and then call
      `store_response(key, endpoint, tenant_id, response, body)`.
    * `(key, resp)`   → cached response; caller should return it as-is.
    """
    key = (request.headers.get("X-Idempotency-Key") or "").strip()
    if not key:
        return None, None
    fp = _fingerprint(body)
    row = await db.idempotency_keys.find_one(
        {"tenant_id": tenant_id, "key": key, "endpoint": endpoint},
        {"_id": 0},
    )
    if not row:
        return key, None
    # Expired? Treat as new. Guard both datetime + legacy ISO-string
    # rows written before the Phase O4 type migration.
    expires = row.get("expires_at")
    now = datetime.now(timezone.utc)
    is_expired = False
    if isinstance(expires, datetime):
        # Mongo returns tz-naive datetimes for pre-Motor writes on
        # some driver versions — coerce to utc for the comparison.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        is_expired = expires < now
    elif isinstance(expires, str) and expires:
        is_expired = expires < now.isoformat()
    if is_expired:
        await db.idempotency_keys.delete_one({"id": row["id"]})
        return key, None
    # Body must match — different body with same key is a client bug we
    # surface loudly rather than silently returning a stale response.
    if row.get("body_fingerprint") and row["body_fingerprint"] != fp:
        return key, {"error": "idempotency_key_body_mismatch",
                      "detail": "Same X-Idempotency-Key with a different body"}
    return key, row.get("response")


async def store_response(
    key: str, endpoint: str, tenant_id: str,
    response: Any, body: Any,
):
    if not key:
        return
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=TTL_SECONDS)
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "key": key,
        "endpoint": endpoint,
        "body_fingerprint": _fingerprint(body),
        "response": response,
        "first_seen_at": now_iso(),
        # Real datetime for the Mongo TTL index to reap on expiry.
        # See services/migrations/idempotency_keys_indexes.py.
        "expires_at": expires,
    }
    # Upsert on (tenant_id, key, endpoint) so a rapid double-hit within
    # the same request doesn't insert duplicates. The unique compound
    # index on this triple (added by the Phase O4 boot migration)
    # makes this race-safe under concurrent load — an insert loser
    # gets a DuplicateKey which we swallow silently.
    try:
        await db.idempotency_keys.update_one(
            {"tenant_id": tenant_id, "key": key, "endpoint": endpoint},
            {"$setOnInsert": doc},
            upsert=True,
        )
    except Exception:                                              # noqa: BLE001
        # Race loser — the winning writer's row is authoritative.
        # No-op; body_fingerprint mismatch on the next replay is the
        # only way this diverges, and that's already handled.
        pass
