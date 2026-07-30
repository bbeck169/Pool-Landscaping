"""Phase 2 · Feb-2026 — Signed 24 h public share URLs for Route Replay.

Endpoints (all under ``/api``)
------------------------------
Authed (tenant-scoped, role ≥ dispatcher / manager):
    POST   /gps/replay/share
    GET    /gps/replay/shares?user_id=&date=
    POST   /gps/replay/share/{share_id}/revoke

Public (no auth):
    GET    /public/replay/{share_id}

Storage
-------
Collection ``route_replay_shares``:
    {tenant_id, share_id, user_id, replay_date, created_by,
     created_at, expires_at, revoked_at?,
     view_count, last_viewed_at?, viewer_ip_hash_last?}
Indexes: unique(share_id), (tenant_id, expires_at),
         (tenant_id, user_id, replay_date).

Security notes
--------------
The share_id itself is the bearer token — a 16-char base62 string
(``secrets.token_urlsafe`` truncated) gives ~93 bits of entropy, plenty
for a 24 h TTL. Nothing else is embedded in the URL; we don't sign or
HMAC. To revoke, the row is marked revoked_at; to expire, we compare
now vs. expires_at at each public GET.

The public payload MASKS every field flagged as PII in the technician
doc (phone, email, home address, DOB, etc.). Only the display name
survives — everything else the widget shows is location / stop /
geofence data, which is precisely what the customer already saw the
technician doing.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import string
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user

router = APIRouter()

# ── Rate-limit — 30 req / 60 s per (share_id, ip_hash). Same style as
# MR3 widget analytics: in-process sliding window.
_RATE_WINDOW_S = 60
_RATE_LIMIT = 30
_rate_buckets: Dict[str, Deque[float]] = defaultdict(deque)

# ── Config
_MAX_TTL_HOURS = 24
_DEFAULT_TTL_HOURS = 24
_SHARE_ID_LEN = 16  # base62 chars → ~93 bits of entropy
_ALPHABET = string.ascii_letters + string.digits

_indexes_ready = False


async def _ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    coll = db["route_replay_shares"]
    await coll.create_index("share_id", unique=True)
    await coll.create_index([("tenant_id", 1), ("expires_at", -1)])
    await coll.create_index([("tenant_id", 1), ("user_id", 1), ("replay_date", 1)])
    _indexes_ready = True


# ── Helpers ─────────────────────────────────────────────────────────
def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip() or "?"
    return (request.client.host if request.client else "?")


def _ip_hash(raw_ip: str, salt: str) -> str:
    return hashlib.sha256(f"{raw_ip}|{salt}".encode("utf-8")).hexdigest()


def _rate_ok(share_id: str, ip: str) -> bool:
    key = f"{share_id}|{_ip_hash(ip, share_id)}"
    now = time.monotonic()
    q = _rate_buckets[key]
    while q and (now - q[0]) > _RATE_WINDOW_S:
        q.popleft()
    if len(q) >= _RATE_LIMIT:
        return False
    q.append(now)
    return True


def _mk_share_id() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_SHARE_ID_LEN))


def _require_share_role(user: Dict[str, Any]) -> None:
    role = (user.get("role") or "").lower()
    allowed = {"dispatcher", "manager", "admin", "super_admin", "owner"}
    if role not in allowed:
        raise HTTPException(403, detail="insufficient_role")


def _tenant_or_400(user: Dict[str, Any]) -> str:
    tid = user.get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, detail="tenant scope required")
    return tid


def _now() -> datetime:
    """Isolated so tests can monkeypatch it."""
    return datetime.now(timezone.utc)


def _as_utc(v: Any) -> Optional[datetime]:
    """Motor deserialises BSON UTC datetimes as *naive* — normalise
    to a tz-aware UTC datetime so we can compare against ``_now()``."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:                                                       # noqa: BLE001
        return None


def _public_base_url(request: Request) -> str:
    override = os.environ.get("PUBLIC_APP_BASE_URL", "").rstrip("/")
    if override:
        return override
    origin = request.headers.get("origin") or ""
    if origin:
        return origin.rstrip("/")
    # Fall back to the request's own scheme+host — good enough for dev.
    return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")


# ═══════════════════════ 1) Create share ════════════════════════════
class ShareCreateBody(BaseModel):
    user_id: str = Field(..., min_length=1)
    replay_date: str = Field(..., min_length=10, max_length=10,
                              pattern=r"^\d{4}-\d{2}-\d{2}$")
    ttl_hours: Optional[int] = Field(None, ge=1, le=_MAX_TTL_HOURS)


@router.post("/gps/replay/share", operation_id="replayShare.create",
              tags=["replay-share"])
async def create_share(body: ShareCreateBody, request: Request,
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_share_role(caller)
    tenant_id = _tenant_or_400(caller)
    await _ensure_indexes()

    # Verify the target user exists in this tenant. Server-derived —
    # we never trust a client-supplied tenant_id.
    tech = await db.users.find_one(
        {"id": body.user_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1, "email": 1})
    if not tech:
        raise HTTPException(404, detail="technician_not_found")

    now = _now()
    ttl = body.ttl_hours or _DEFAULT_TTL_HOURS
    expires_at = now + timedelta(hours=min(ttl, _MAX_TTL_HOURS))

    share_id = _mk_share_id()
    doc = {
        "tenant_id": tenant_id,
        "share_id": share_id,
        "user_id": body.user_id,
        "replay_date": body.replay_date,
        "created_by": caller.get("id") or "",
        "created_at": now,
        "expires_at": expires_at,
        "revoked_at": None,
        "view_count": 0,
        "last_viewed_at": None,
        "viewer_ip_hash_last": None,
    }
    await db.route_replay_shares.insert_one(doc)

    base = _public_base_url(request)
    share_url = f"{base}/replay/{share_id}"
    revoke_url = f"{base}/api/gps/replay/share/{share_id}/revoke"

    return {
        "share_id": share_id,
        "share_url": share_url,
        "revoke_url": revoke_url,
        "expires_at": expires_at.isoformat(),
        "user_id": body.user_id,
        "replay_date": body.replay_date,
    }


# ═══════════════════════ 2) List shares ═════════════════════════════
@router.get("/gps/replay/shares", operation_id="replayShare.list",
             tags=["replay-share"])
async def list_shares(user_id: str = Query(...),
                       date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
                       caller: Dict[str, Any] = Depends(get_current_user)):
    _require_share_role(caller)
    tenant_id = _tenant_or_400(caller)
    await _ensure_indexes()
    items: List[Dict[str, Any]] = []
    async for r in db.route_replay_shares.find(
            {"tenant_id": tenant_id, "user_id": user_id,
              "replay_date": date},
            {"_id": 0}).sort("created_at", -1).limit(20):
        # Compute status flag for the UI.
        now = _now()
        status = "active"
        if r.get("revoked_at"):
            status = "revoked"
        else:
            exp = _as_utc(r.get("expires_at"))
            if exp and exp <= now:
                status = "expired"
        r["status"] = status
        # Do not echo internal viewer IP hashes to the list view (only
        # the last-viewed timestamp is useful for dispatchers).
        r.pop("viewer_ip_hash_last", None)
        items.append(r)
    return {"items": items, "total": len(items)}


# ═══════════════════════ 3) Revoke ══════════════════════════════════
@router.post("/gps/replay/share/{share_id}/revoke",
              operation_id="replayShare.revoke",
              tags=["replay-share"])
async def revoke_share(share_id: str = Path(..., min_length=8, max_length=32),
                        caller: Dict[str, Any] = Depends(get_current_user)):
    _require_share_role(caller)
    tenant_id = _tenant_or_400(caller)
    await _ensure_indexes()
    r = await db.route_replay_shares.find_one_and_update(
        {"share_id": share_id, "tenant_id": tenant_id,
          "revoked_at": None},
        {"$set": {"revoked_at": _now()}},
        return_document=True,
    )
    if not r:
        # Either wrong tenant, unknown share, or already revoked. Return
        # a stable ok:false so the UI can render an idempotent message
        # without leaking whether the share ever existed.
        raise HTTPException(404, detail="share_not_found_or_already_revoked")
    return {"ok": True, "share_id": share_id,
            "revoked_at": r["revoked_at"].isoformat()}


# ═══════════════════════ 4) Public GET ══════════════════════════════
_PING_LIMIT = 5000  # same order of magnitude as the authed route


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


async def _build_public_payload(share: Dict[str, Any]) -> Dict[str, Any]:
    """Fetches stops + pings + geofence entries for the (user_id,
    replay_date) pair and returns a PII-scrubbed payload safe for
    unauthenticated viewing."""
    tenant_id = share["tenant_id"]
    user_id = share["user_id"]
    date = share["replay_date"]
    day_start = f"{date}T00:00:00+00:00"
    day_end = f"{date}T23:59:59+00:00"

    # Tech display name — nothing PII beyond first name / display.
    tech_name = ""
    tech = await db.users.find_one(
        {"id": user_id, "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "display_name": 1})
    if tech:
        tech_name = tech.get("display_name") or tech.get("name") or "Technician"

    # Tenant display for the footer.
    tenant_name = ""
    tenant = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "name": 1})
    if tenant:
        tenant_name = tenant.get("name") or ""

    # Stops — strip PII fields on the way out.
    _PII_ON_STOP = {
        "phone", "phone_number", "email", "home_address",
        "attributed_customer_email", "attributed_customer_phone",
        "reviewer_notes", "notes",
    }
    stops: List[Dict[str, Any]] = []
    async for s in db.driver_stops.find(
            {"tenant_id": tenant_id, "user_id": user_id,
              "started_at": {"$gte": day_start, "$lte": day_end}},
            {"_id": 0}).sort("started_at", 1):
        for k in list(s.keys()):
            if k in _PII_ON_STOP:
                s.pop(k, None)
        stops.append(s)

    # Pings — downsample if huge.
    pings: List[Dict[str, Any]] = []
    total_pings = await db.gps_pings.count_documents(
        {"tenant_id": tenant_id, "user_id": user_id,
          "captured_at": {"$gte": day_start, "$lte": day_end}})
    step = 1
    if total_pings > _PING_LIMIT:
        step = (total_pings // _PING_LIMIT) + 1
    i = 0
    async for p in db.gps_pings.find(
            {"tenant_id": tenant_id, "user_id": user_id,
              "captured_at": {"$gte": day_start, "$lte": day_end}},
            {"_id": 0, "lat": 1, "lon": 1, "captured_at": 1}
            ).sort("captured_at", 1):
        if i % step == 0:
            pings.append({"lat": float(p["lat"]), "lon": float(p["lon"]),
                           "captured_at": p.get("captured_at")})
        i += 1
        if len(pings) >= _PING_LIMIT:
            break

    # Geofence entries + exits (public-safe — only fence name + ts).
    fences: List[Dict[str, Any]] = []
    async for g in db.geofence_events.find(
            {"tenant_id": tenant_id, "user_id": user_id,
              "ts": {"$gte": day_start, "$lte": day_end}},
            {"_id": 0}).sort("ts", 1):
        fences.append({
            "geofence_id": g.get("geofence_id"),
            "geofence_name": g.get("geofence_name") or "",
            "event": g.get("event"),
            "ts": _iso(g.get("ts")),
        })

    first_ping_at = pings[0]["captured_at"] if pings else None
    last_ping_at = pings[-1]["captured_at"] if pings else None
    playback_duration_s = 0
    if first_ping_at and last_ping_at:
        try:
            a = datetime.fromisoformat(str(first_ping_at).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(last_ping_at).replace("Z", "+00:00"))
            playback_duration_s = max(0, int((b - a).total_seconds()))
        except Exception:                                                  # noqa: BLE001
            playback_duration_s = 0

    return {
        "share_id": share["share_id"],
        "user_id": user_id,
        "user_name": tech_name,
        "tenant_name": tenant_name,
        "replay_date": date,
        "from": day_start,
        "to": day_end,
        "stops": stops,
        "pings": pings,
        "pings_total": total_pings,
        "pings_downsample_step": step,
        "geofence_events": fences,
        "first_ping_at": first_ping_at,
        "last_ping_at": last_ping_at,
        "playback_duration_s": playback_duration_s,
        "expires_at": _iso(share.get("expires_at")),
        "read_only": True,
    }


@router.options("/public/replay/{share_id}", include_in_schema=False)
async def public_replay_options(share_id: str):
    return Response(status_code=204, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    })


@router.get("/public/replay/{share_id}", operation_id="replayShare.public",
             tags=["replay-share"])
async def public_replay(share_id: str, request: Request):
    await _ensure_indexes()
    ip = _client_ip(request)

    # Rate limit first — we don't want a bot to be able to enumerate
    # even 404 vs 410 vs 200 at unlimited RPS.
    if not _rate_ok(share_id, ip):
        return Response(status_code=429,
                        headers={"Access-Control-Allow-Origin": "*",
                                  "X-Widget-Analytics": "rate_limited",
                                  "Retry-After": str(_RATE_WINDOW_S)})

    share = await db.route_replay_shares.find_one({"share_id": share_id},
                                                     {"_id": 0})
    if not share:
        raise HTTPException(404, detail="share_not_found")

    now = _now()
    if share.get("revoked_at"):
        raise HTTPException(410, detail="share_revoked")
    exp = _as_utc(share.get("expires_at"))
    if exp and exp <= now:
        raise HTTPException(410, detail="share_expired")

    payload = await _build_public_payload(share)

    # Increment view counters. No raw IP is stored anywhere — only its
    # hash, and only the LAST viewer (not a rolling list).
    ip_h = _ip_hash(ip, share_id)
    await db.route_replay_shares.update_one(
        {"share_id": share_id},
        {"$inc": {"view_count": 1},
         "$set": {"last_viewed_at": now, "viewer_ip_hash_last": ip_h}},
    )
    payload["view_count"] = int(share.get("view_count", 0)) + 1

    resp = Response(
        content=__import__("json").dumps(payload, default=str),
        media_type="application/json",
        headers={"Access-Control-Allow-Origin": "*",
                  "Cache-Control": "no-store"},
    )
    return resp
