"""Phase 40 · Idempotency-key middleware helper.

When a client sends `X-Idempotency-Key: <uuid>` on a mutating endpoint,
we cache the first response in `idempotency_keys` and short-circuit
duplicate replays for 24 hours. Enables offline mobile clients to
safely retry a queued write without double-billing (e.g. two invoice
creations on the same submit).

Only endpoints that opt in (by calling `check_and_reserve` +
`store_response`) participate — everything else remains fire-and-forget.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any, Optional, Tuple

from fastapi import Request

from config import db
from utils import now_iso, new_id

TTL_SECONDS = 24 * 60 * 60  # 24h


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
    # Expired? Treat as new.
    if row.get("expires_at") and row["expires_at"] < now_iso():
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
    from datetime import datetime, timezone
    expires = (datetime.now(timezone.utc)
                + timedelta(seconds=TTL_SECONDS)).isoformat()
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "key": key,
        "endpoint": endpoint,
        "body_fingerprint": _fingerprint(body),
        "response": response,
        "first_seen_at": now_iso(),
        "expires_at": expires,
    }
    # Upsert on (tenant_id, key, endpoint) so a rapid double-hit within
    # the same request doesn't insert duplicates.
    await db.idempotency_keys.update_one(
        {"tenant_id": tenant_id, "key": key, "endpoint": endpoint},
        {"$setOnInsert": doc},
        upsert=True,
    )
