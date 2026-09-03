"""K36 · Mobile crash telemetry ingest.

`POST /api/telemetry/mobile-crash` — accepts a crash payload from
`mobile/src/utils/crashReporter.ts`. Unauthenticated (crashing devices
may already be logged out), rate-limited to 60 req/min/IP via a
TTL-indexed Mongo counter (same pattern as
`services/reviews_rate_limit.py`).

Payload shape (contract with mobile crashReporter.ts)::

    {
      "crash": {
        "ts": int,                # ms epoch
        "message": str,
        "stack": str | None,
        "componentStack": str | None,
        "platform": "ios" | "android" | "web",
        "osVersion": str | None
      },
      "nav": [{ "ts": int, "route": str, "extra": {...}? }, ...],   # last 20
      "api": [{ "ts": int, "method": str, "path": str,
                "status": int?, "ms": int?, "errorKind": str?,
                "errorMsg": str? }, ...],                            # last 20
      "platform": str,
      "os_version": str | None,
      "captured_at": int
    }

Persisted collection: ``mobile_crash_reports``. Every field is
length-capped so a runaway crash loop can't blow up the docstore.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from config import db, logger
from utils import new_id, now_iso

router = APIRouter(tags=["Telemetry"])

# ── length caps ────────────────────────────────────────────────────
_MSG_CAP = 500
_STACK_CAP = 8_000
_COMPONENT_STACK_CAP = 4_000
_ROUTE_CAP = 200
_PATH_CAP = 500
_ERR_MSG_CAP = 300
_MAX_NAV = 20
_MAX_API = 20

# ── rate limit ─────────────────────────────────────────────────────
_MAX_PER_MINUTE = 60
_RATE_TTL_SECONDS = 300
_RATE_INDEX_ENSURED = False


def _clip(v: Any, n: int) -> Optional[str]:
    if v is None:
        return None
    s = str(v)
    return s if len(s) <= n else s[:n]


def _client_ip(request: Request) -> str:
    """Best-effort client IP, honoring the standard proxy header."""
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return ""


async def _ensure_rate_index() -> None:
    global _RATE_INDEX_ENSURED
    if _RATE_INDEX_ENSURED:
        return
    try:
        await db.mobile_crash_rate.create_index(
            "bucket_dt", expireAfterSeconds=_RATE_TTL_SECONDS,
        )
        await db.mobile_crash_rate.create_index(
            [("ip", 1), ("bucket_iso", 1)],
        )
        _RATE_INDEX_ENSURED = True
    except Exception as e:
        logger.warning(f"[mobile_crash_rate] index setup partial: {e}")


async def _check_rate(ip: str) -> tuple[bool, int]:
    """Return ``(allowed, count_after_charge)``. Fail-open on Mongo errors."""
    await _ensure_rate_index()
    try:
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        bucket_iso = now.isoformat()
        count = await db.mobile_crash_rate.count_documents({
            "ip": ip, "bucket_iso": bucket_iso,
        })
        if count >= _MAX_PER_MINUTE:
            return False, count
        await db.mobile_crash_rate.insert_one({
            "ip": ip, "bucket_iso": bucket_iso, "bucket_dt": now,
        })
        return True, count + 1
    except Exception as e:
        logger.warning(f"[mobile_crash_rate] check failed: {e}")
        return True, 0


# ── payload models ─────────────────────────────────────────────────
class CrashCore(BaseModel):
    ts: Optional[int] = None
    message: str = Field(..., min_length=1)
    stack: Optional[str] = None
    componentStack: Optional[str] = None
    platform: Optional[str] = None
    osVersion: Optional[str] = None


class NavCrumbIn(BaseModel):
    ts: Optional[int] = None
    route: str
    extra: Optional[Dict[str, Any]] = None


class ApiCrumbIn(BaseModel):
    ts: Optional[int] = None
    method: str
    path: str
    status: Optional[int] = None
    ms: Optional[int] = None
    errorKind: Optional[str] = None
    errorMsg: Optional[str] = None


class MobileCrashIn(BaseModel):
    crash: CrashCore
    nav: Optional[List[NavCrumbIn]] = None
    api: Optional[List[ApiCrumbIn]] = None
    platform: Optional[str] = None
    os_version: Optional[str] = None
    captured_at: Optional[int] = None


def _sanitize_nav(nav: Optional[List[NavCrumbIn]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in (nav or [])[-_MAX_NAV:]:
        out.append({
            "ts": int(c.ts) if c.ts is not None else None,
            "route": _clip(c.route, _ROUTE_CAP) or "",
            "extra": c.extra if isinstance(c.extra, dict) else None,
        })
    return out


def _sanitize_api(api: Optional[List[ApiCrumbIn]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in (api or [])[-_MAX_API:]:
        out.append({
            "ts": int(c.ts) if c.ts is not None else None,
            "method": _clip(c.method, 12) or "GET",
            "path": _clip(c.path, _PATH_CAP) or "",
            "status": int(c.status) if isinstance(c.status, int) else None,
            "ms": int(c.ms) if isinstance(c.ms, int) else None,
            "error_kind": _clip(c.errorKind, 20),
            "error_msg": _clip(c.errorMsg, _ERR_MSG_CAP),
        })
    return out


@router.post("/telemetry/mobile-crash", operation_id="telemetry.mobile_crash")
async def ingest_mobile_crash(body: MobileCrashIn, request: Request):
    """Accept a mobile crash + trailing breadcrumbs. Anonymous OK."""
    ip = _client_ip(request)
    allowed, count = await _check_rate(ip)
    if not allowed:
        # 429 is the correct signal; the mobile client already treats
        # any non-2xx as a soft-fail and moves on.
        logger.warning(
            f"[telemetry/mobile-crash] rate-limited ip={ip} count={count}",
        )
        raise HTTPException(429, "Too many crash reports — try again shortly")

    row = {
        "id": new_id(),
        "ip": ip or None,
        "user_agent": _clip(request.headers.get("user-agent"), 500),
        "platform": _clip(body.platform or body.crash.platform, 20),
        "os_version": _clip(body.os_version or body.crash.osVersion, 40),
        "message": _clip(body.crash.message, _MSG_CAP) or "",
        "stack": _clip(body.crash.stack, _STACK_CAP),
        "component_stack": _clip(body.crash.componentStack, _COMPONENT_STACK_CAP),
        "crash_ts": int(body.crash.ts) if body.crash.ts is not None else None,
        "captured_at_ms": int(body.captured_at) if body.captured_at is not None else None,
        "nav": _sanitize_nav(body.nav),
        "api": _sanitize_api(body.api),
        "created_at": now_iso(),
    }
    try:
        await db.mobile_crash_reports.insert_one(row)
    except Exception as e:  # pragma: no cover — best-effort
        logger.warning(f"[telemetry/mobile-crash] insert failed: {e}")
        raise HTTPException(500, "Failed to record crash")

    logger.warning(
        "[telemetry/mobile-crash] ingested id=%s platform=%s os=%s msg=%r nav=%d api=%d ip=%s",
        row["id"], row["platform"], row["os_version"],
        (row["message"] or "")[:120],
        len(row["nav"] or []), len(row["api"] or []), ip or "-",
    )
    return {"ok": True, "id": row["id"]}
