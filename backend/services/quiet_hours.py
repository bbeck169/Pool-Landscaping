"""Feb-2026 · P34 — Automation quiet-hours core helpers.

Ships two pure helpers + a persistence primitive used by the SMS + email
adapters and the release worker:

  * :func:`is_within_send_window` — True if the tenant currently
    permits automated sends; False if the send should be deferred.
    Returns True unconditionally when the tenant hasn't enabled quiet
    hours (backward-compatible default).
  * :func:`next_send_window_open` — timezone-aware datetime for the
    next moment the window re-opens. Used to schedule deferred rows.
  * :func:`defer_send` — persists a payload into ``outbound_deferred``
    for later release.
  * :func:`claim_pending_batch` — atomic ``pending → releasing`` batch
    claim so a concurrent worker can never double-release the same row.

Overnight window semantics (locked with user):
  If ``end < start`` on the wall clock, the window spans midnight —
  i.e. sending is allowed FROM ``start`` on day N THROUGH ``end`` on
  day N+1. Example: start=20:00, end=02:00 means "may send between
  8pm and 2am the next day".
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import db, logger
from utils import new_id, now_iso


DEFAULT_START = "08:00"
DEFAULT_END = "20:00"
DEFAULT_TZ = "America/Phoenix"


def _parse_hhmm(s: str) -> dtime:
    """Strict HH:MM parser. Raises ValueError on invalid input."""
    if not isinstance(s, str) or len(s) != 5 or s[2] != ":":
        raise ValueError(f"invalid HH:MM: {s!r}")
    hh_s, mm_s = s.split(":", 1)
    hh, mm = int(hh_s), int(mm_s)
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"out-of-range HH:MM: {s!r}")
    return dtime(hh, mm)


def _resolve_tz(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TZ)


def _time_in_window(t: dtime, start: dtime, end: dtime) -> bool:
    """Given a local ``t``, is it inside the [start, end) window?
    Handles overnight windows where ``end < start`` (spans midnight).
    A window with start == end is treated as "always closed" — the
    caller should not persist that config (validator rejects it)."""
    if start == end:
        return False
    if start < end:
        return start <= t < end
    # Overnight window (spans midnight).
    return t >= start or t < end


async def _load_tenant(tenant_id: str) -> Optional[Dict[str, Any]]:
    return await db.tenants.find_one(
        {"id": tenant_id},
        {"_id": 0, "id": 1, "timezone": 1,
          "quiet_hours_enabled": 1,
          "quiet_hours_start": 1, "quiet_hours_end": 1,
          "quiet_hours_timezone": 1},
    )


def _resolve_config(tenant: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw tenant doc into ``{enabled, start, end, tz}``.
    Missing fields fall back to safe defaults; timezone falls back to
    the tenant's global timezone, then to ``DEFAULT_TZ``."""
    return {
        "enabled": bool(tenant.get("quiet_hours_enabled", False)),
        "start": tenant.get("quiet_hours_start") or DEFAULT_START,
        "end": tenant.get("quiet_hours_end") or DEFAULT_END,
        "tz": (tenant.get("quiet_hours_timezone")
                 or tenant.get("timezone")
                 or DEFAULT_TZ),
    }


async def is_within_send_window(
    tenant_id: str, now: Optional[datetime] = None,
) -> bool:
    """True if the tenant currently allows automated sends. Returns
    True unconditionally when quiet hours are disabled or the tenant
    is missing (fail-open for backward compat)."""
    tenant = await _load_tenant(tenant_id)
    if not tenant:
        return True
    cfg = _resolve_config(tenant)
    if not cfg["enabled"]:
        return True
    try:
        start = _parse_hhmm(cfg["start"])
        end = _parse_hhmm(cfg["end"])
    except ValueError:
        # Corrupt config → fail open (don't silently start dropping mail).
        logger.warning("[p34] tenant=%s corrupt quiet-hours config — allowing send",
                          tenant_id)
        return True
    tz = _resolve_tz(cfg["tz"])
    local = (now or datetime.now(tz=tz)).astimezone(tz)
    return _time_in_window(local.time(), start, end)


async def next_send_window_open(
    tenant_id: str, now: Optional[datetime] = None,
) -> datetime:
    """Return the next timezone-aware datetime the send window opens.
    If quiet hours are disabled → returns ``now`` (send immediately).
    If currently inside the window → also returns ``now``."""
    tenant = await _load_tenant(tenant_id)
    if not tenant:
        return now or datetime.now(tz=ZoneInfo(DEFAULT_TZ))
    cfg = _resolve_config(tenant)
    tz = _resolve_tz(cfg["tz"])
    ref = (now or datetime.now(tz=tz)).astimezone(tz)
    if not cfg["enabled"]:
        return ref
    try:
        start = _parse_hhmm(cfg["start"])
        end = _parse_hhmm(cfg["end"])
    except ValueError:
        return ref
    if _time_in_window(ref.time(), start, end):
        return ref
    # Not in window — find next start boundary.
    candidate = ref.replace(hour=start.hour, minute=start.minute,
                                 second=0, microsecond=0)
    if candidate <= ref:
        candidate = candidate + timedelta(days=1)
    return candidate


async def defer_send(
    tenant_id: str, channel: str, payload: Dict[str, Any],
    *, created_by: Optional[str] = None,
    scheduled_for: Optional[datetime] = None,
) -> str:
    """Persist an outbound send to ``outbound_deferred`` for release
    when the quiet-hours window re-opens. Returns the row id."""
    if scheduled_for is None:
        scheduled_for = await next_send_window_open(tenant_id)
    row = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "channel": channel,        # "sms" | "email"
        "payload": payload,
        "scheduled_for": scheduled_for.astimezone(ZoneInfo("UTC")).isoformat(),
        "created_at": now_iso(),
        "created_by": created_by,
        "released_at": None,
        "status": "pending",
    }
    await db.outbound_deferred.insert_one(row)
    logger.info("[p34] deferred send tenant=%s channel=%s id=%s scheduled_for=%s",
                    tenant_id, channel, row["id"], row["scheduled_for"])
    return row["id"]


async def claim_pending_batch(
    now_iso_str: str, limit: int = 100,
) -> list[Dict[str, Any]]:
    """Atomic claim of up to ``limit`` pending rows whose
    ``scheduled_for <= now``. Flips them to ``releasing`` so a
    concurrent worker cannot double-send.

    Returns the freshly-claimed rows (caller dispatches them then
    marks each ``sent`` or ``failed``)."""
    claimed: list[Dict[str, Any]] = []
    for _ in range(limit):
        row = await db.outbound_deferred.find_one_and_update(
            {"status": "pending", "scheduled_for": {"$lte": now_iso_str}},
            {"$set": {"status": "releasing",
                          "claimed_at": now_iso()}},
            return_document=True,   # motor: return the updated doc
        )
        if not row:
            break
        row.pop("_id", None)
        claimed.append(row)
    return claimed
