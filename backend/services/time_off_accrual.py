"""
Phase 40 (Feb-2026) — Time-off accrual computation.

Business rules (aquaterra default policy):
    * 1 hour of paid sick leave per 30 hours worked.
    * Annual cap: 24 hours per year (rolling YTD, resets Jan 1).
    * 90-day new-hire waiting period before USING accrued balance.
      Accrual still happens during the window.

The service is intentionally a pure function of the timesheet ledger
so we do not have to run a scheduled job — every call to
``compute_balance()`` recomputes YTD from ``db.time_entries``. Volume
is small enough (< 20k rows per tenant per year) that on-read is
cheap. If that changes we can trivially memoise per user_id + day.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Optional

DEFAULT_POLICY: dict[str, Any] = {
    "accrual_numerator": 1,
    "accrual_denominator": 30,
    "annual_cap_hours": 24,
    "waiting_period_days": 90,
    "active": True,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _year_start(dt: datetime) -> datetime:
    return datetime(dt.year, 1, 1, tzinfo=timezone.utc)


def _minutes_between(a: datetime, b: datetime) -> int:
    delta = b - a
    return max(0, int(delta.total_seconds() // 60))


def _sum_break_minutes(breaks: list[dict[str, Any]] | None) -> int:
    total = 0
    for b in breaks or []:
        start = b.get("start"); end = b.get("end")
        if isinstance(start, datetime) and isinstance(end, datetime):
            total += _minutes_between(start, end)
    return total


async def sum_worked_hours_ytd(db, tenant_id: str, user_id: str, now: Optional[datetime] = None) -> float:
    """Sum shifts closed since Jan 1 of the current year."""
    now = now or _now()
    year_start = _year_start(now)
    total_minutes = 0
    async for e in db.time_entries.find({
        "tenant_id": tenant_id,
        "user_id": user_id,
        "clock_out_at": {"$ne": None, "$gte": year_start},
    }):
        clock_in = e.get("clock_in_at")
        clock_out = e.get("clock_out_at")
        if not (isinstance(clock_in, datetime) and isinstance(clock_out, datetime)):
            continue
        # Some legacy rows were persisted as naive UTC — coerce so the
        # tz-aware ``year_start`` comparison below doesn't blow up.
        if clock_in.tzinfo is None:
            clock_in = clock_in.replace(tzinfo=timezone.utc)
        if clock_out.tzinfo is None:
            clock_out = clock_out.replace(tzinfo=timezone.utc)
        # Only count minutes falling inside the YTD window.
        window_start = max(clock_in, year_start)
        total_minutes += _minutes_between(window_start, clock_out) - _sum_break_minutes(e.get("breaks"))
    return round(total_minutes / 60.0, 2)


async def get_policy(db, tenant_id: str) -> dict[str, Any]:
    doc = await db.time_off_policies.find_one({"tenant_id": tenant_id})
    if doc:
        # Merge in defaults so partial policies never break math.
        merged = {**DEFAULT_POLICY, **{k: v for k, v in doc.items() if k in DEFAULT_POLICY}}
        merged["id"] = doc.get("id")
        merged["tenant_id"] = tenant_id
        merged["updated_at"] = doc.get("updated_at")
        merged["updated_by"] = doc.get("updated_by")
        return merged
    return {**DEFAULT_POLICY, "tenant_id": tenant_id, "id": None}


def _hire_date(user: dict[str, Any]) -> datetime:
    """Fall back to created_at if hire_date is missing so old accounts aren't stuck."""
    for key in ("hire_date", "hired_on", "start_date"):
        v = user.get(key)
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if isinstance(v, str):
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    created = user.get("created_at")
    if isinstance(created, datetime):
        return created if created.tzinfo else created.replace(tzinfo=timezone.utc)
    if isinstance(created, str):
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return _now()


def waiting_period_remaining_days(user: dict[str, Any], policy: dict[str, Any], now: Optional[datetime] = None) -> int:
    now = now or _now()
    hire = _hire_date(user)
    elapsed = (now - hire).days
    remaining = int(policy.get("waiting_period_days", 90)) - elapsed
    return max(0, remaining)


async def used_hours_ytd(db, tenant_id: str, user_id: str, now: Optional[datetime] = None) -> float:
    """Sum approved time-off hours in the current YTD window."""
    now = now or _now()
    year_start = _year_start(now)
    total = 0.0
    async for r in db.time_off_requests.find({
        "tenant_id": tenant_id,
        "user_id": user_id,
        "status": "approved",
        "from_date": {"$gte": year_start.date().isoformat()},
    }):
        total += float(r.get("hours") or 0)
    return round(total, 2)


async def compute_balance(db, tenant_id: str, user: dict[str, Any], now: Optional[datetime] = None) -> dict[str, Any]:
    """Return the full balance snapshot for a user."""
    now = now or _now()
    policy = await get_policy(db, tenant_id)
    worked = await sum_worked_hours_ytd(db, tenant_id, user["id"], now=now)
    used = await used_hours_ytd(db, tenant_id, user["id"], now=now)

    num = int(policy.get("accrual_numerator", 1))
    den = max(1, int(policy.get("accrual_denominator", 30)))
    cap = float(policy.get("annual_cap_hours", 24))

    accrued_uncapped = (worked * num) / den
    # Cap applies to accrued_ytd (before subtracting used). Used doesn't
    # free up cap headroom — matches Odoo's "annual entitlement" model.
    accrued = round(min(accrued_uncapped, cap), 2)
    available = round(max(0.0, accrued - used), 2)

    waiting_days = waiting_period_remaining_days(user, policy, now=now)
    return {
        "user_id": user["id"],
        "ytd_year": now.year,
        "worked_hours_ytd": worked,
        "accrued_hours_ytd": accrued,
        "accrued_uncapped_hours_ytd": round(accrued_uncapped, 2),
        "used_hours_ytd": used,
        "available_hours": available,
        "annual_cap_hours": cap,
        "waiting_period_remaining_days": waiting_days,
        "can_use_balance": waiting_days == 0,
        "policy": {
            "accrual_numerator": num,
            "accrual_denominator": den,
            "annual_cap_hours": cap,
            "waiting_period_days": int(policy.get("waiting_period_days", 90)),
        },
    }
