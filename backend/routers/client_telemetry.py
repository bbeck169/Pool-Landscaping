"""
Feb-2026 · Diag-Timeout Task 2 — client-side timeout telemetry.

Ambient signal for the "Request timed out — check your connection
and try again." toast that fires from ``api.js`` after 30s. When the
toast triggers the frontend POSTs the offending request context
here; we persist to ``db.client_timeout_events`` with a 30-day TTL
so operators can correlate with the server-side ``slow_request``
log lines (matched via ``X-Request-Id``).

Behaviour contract:
  * Auth required (any role) — anonymous timeouts don't POST.
  * Rate-limited to 1 write / sec / user (defence against a
    runaway loop in the frontend). The 21st write in a minute is a
    no-op with a 429.
  * Killswitch: ``TIMEOUT_TELEMETRY_KILLSWITCH=1`` makes the
    endpoint a 204 no-op without hitting Mongo — for instant
    on/off via ``ops env-patch`` if the write volume gets noisy.
  * TTL index ``created_at`` @ 30 days ensures bounded storage.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user

logger = logging.getLogger("routers.client_telemetry")
router = APIRouter(tags=["client-telemetry"])


_RATE_LIMIT_WINDOW_SEC = 1
_KILLSWITCH_ENV = "TIMEOUT_TELEMETRY_KILLSWITCH"

# Bucket paths so cardinality doesn't explode across ``/customers/{uuid}``
# style URLs. Mirrors the middleware bucketing on the server side so a
# client telemetry row and a server slow-request log line share the
# same ``path`` value.
_UUID_RX = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_NUM_RX = re.compile(r"/\d{2,}")


def _bucket(path: str) -> str:
    p = (path or "").split("?", 1)[0]
    p = _UUID_RX.sub("/:uuid", p)
    p = _NUM_RX.sub("/:num", p)
    return p[:200]


class TimeoutTelemetryIn(BaseModel):
    request_url: str = Field(..., max_length=2000)
    request_method: str = Field(..., max_length=10)
    started_at: Optional[str] = Field(None, max_length=64)
    ended_at: Optional[str] = Field(None, max_length=64)
    duration_ms: Optional[int] = Field(None, ge=0, le=600_000)
    route_path: Optional[str] = Field(None, max_length=200)
    user_agent: Optional[str] = Field(None, max_length=500)
    request_id: Optional[str] = Field(None, max_length=64)
    app_version: Optional[str] = Field(None, max_length=64)


def _killswitch_on() -> bool:
    return (os.environ.get(_KILLSWITCH_ENV) or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


async def _rate_limited(user_id: str) -> bool:
    """Return True when the user has posted a telemetry event in the
    last second — enforces the 1 write/sec cap."""
    from datetime import timedelta
    since = (datetime.now(tz=timezone.utc)
              - timedelta(seconds=_RATE_LIMIT_WINDOW_SEC)).isoformat()
    return await db.client_timeout_events.count_documents(
        {"user_id": user_id, "created_at": {"$gte": since}},
        limit=1,
    ) > 0


async def ensure_client_timeout_indexes() -> None:
    """Idempotent index setup — TTL on ``created_at`` for auto
    expiry + one lookup index for the read side (deferred admin UI).
    Called from ``server.py`` boot."""
    try:
        await db.client_timeout_events.create_index(
            [("created_at", 1)],
            name="client_timeout_events_ttl",
            expireAfterSeconds=30 * 24 * 60 * 60,   # 30 days
            background=True,
        )
        await db.client_timeout_events.create_index(
            [("tenant_id", 1), ("created_at", -1)],
            name="client_timeout_events_lookup",
            background=True,
        )
    except Exception:  # pragma: no cover
        logger.exception("client_timeout_events index setup failed")


@router.post("/admin/client-telemetry/timeout", status_code=201)
async def report_timeout(
    body: TimeoutTelemetryIn,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Record a client-side 30s-timeout event. Rate-limited + gated
    by the killswitch env var. Fire-and-forget from the client's
    perspective — always returns 201 unless the killswitch is on
    (returns 204) or the caller hit the rate limit (429)."""
    if _killswitch_on():
        return {"skipped": "killswitch"}

    user_id = user.get("id") or user.get("_id") or ""
    if not user_id:
        raise HTTPException(401, "authentication required")

    if await _rate_limited(user_id):
        raise HTTPException(429, "rate limited — try again in a second")

    doc = {
        "user_id": user_id,
        "tenant_id": user.get("tenant_id") or "",
        "role": user.get("role") or "",
        "request_url": body.request_url[:2000],
        "request_method": (body.request_method or "").upper()[:10],
        "path_bucket": _bucket(body.request_url),
        "started_at": body.started_at,
        "ended_at": body.ended_at,
        "duration_ms": int(body.duration_ms or 0),
        "route_path": (body.route_path or "")[:200],
        "user_agent": (body.user_agent or "")[:500],
        "request_id": (body.request_id or "")[:64],
        "app_version": (body.app_version or "")[:64],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    try:
        await db.client_timeout_events.insert_one(doc)
    except Exception:  # pragma: no cover
        logger.exception("client_timeout_events insert failed")
        raise HTTPException(500, "telemetry persistence failed")

    # Also emit a WARN line so the ambient log stream can catch it
    # even before we build the admin read-side.
    logger.warning(
        "client_timeout_reported user=%s tenant=%s method=%s "
        "path=%s duration_ms=%s request_id=%s",
        user_id, doc["tenant_id"], doc["request_method"],
        doc["path_bucket"], doc["duration_ms"],
        doc["request_id"] or "-",
    )
    return {"ok": True}
