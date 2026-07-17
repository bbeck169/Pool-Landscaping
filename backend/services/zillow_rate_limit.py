"""Phase 56.9b Steps 1-3 — Zillow rate-limit + budget guard + cache service.

Pure library — does NOT touch endpoint RBAC (that's Step 8, held for
the next session). Callers use `check_and_charge(...)` to gate a
lookup, `read_cache(...)` to short-circuit paid API calls, and
`write_cache(...)` to memoize a fresh response.

Collections (created lazily on first insert; TTL indexes ensured on
first `ensure_indexes()`):
  * `zillow_usage`  — one row per counted call
  * `zillow_cache`  — one row per unique address_hash
  * `zillow_audit`  — super_admin budget-override events
"""
import hashlib
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import db, logger

# ─── caps + budget defaults (per spec) ────────────────────────────────
TECH_DAILY_CAP = 20
TECH_MONTHLY_CAP = 200
TENANT_MONTHLY_BUDGET_DEFAULT = 1000
BUDGET_WARN_THRESHOLD = 0.90  # ≥90 % triggers X-Zillow-Budget-Warning
CACHE_TTL_DAYS = 30


def _now():
    return datetime.now(timezone.utc)


def _iso(dt=None):
    return (dt or _now()).astimezone(timezone.utc).isoformat()


def _month_key(dt=None):
    return (dt or _now()).strftime("%Y-%m")


def _day_key(dt=None):
    return (dt or _now()).strftime("%Y-%m-%d")


def normalize_address(addr: str) -> str:
    """Deterministic address normalization for cache/hash consistency."""
    if not addr:
        return ""
    s = re.sub(r"\s+", " ", addr.strip().lower())
    s = re.sub(r"[^\w\s,-]", "", s)
    return s


def address_hash(addr: str) -> str:
    return hashlib.sha256(normalize_address(addr).encode("utf-8")).hexdigest()


def is_super_admin(user: dict) -> bool:
    return (user or {}).get("role") == "super_admin"


def is_admin_or_above(user: dict) -> bool:
    r = (user or {}).get("role")
    return r in ("admin", "super_admin")


async def ensure_indexes():
    """Idempotent — called on first request path. TTLs auto-clean old rows."""
    try:
        await db.zillow_usage.create_index("ts")
        await db.zillow_usage.create_index([("tenant_id", 1), ("user_id", 1), ("ts", -1)])
        await db.zillow_cache.create_index([("address_hash", 1), ("cached_at", 1)])
        # 30-day TTL on cache rows.
        await db.zillow_cache.create_index(
            "cached_at_dt", expireAfterSeconds=CACHE_TTL_DAYS * 24 * 3600
        )
        await db.zillow_audit.create_index("ts")
    except Exception as e:
        logger.warning(f"[56.9b] ensure_indexes: {e}")


async def _tenant_budget(tenant: dict) -> int:
    """Tenant may override the default via `tenant.zillow_monthly_budget`."""
    v = (tenant or {}).get("zillow_monthly_budget")
    try:
        return int(v) if v else TENANT_MONTHLY_BUDGET_DEFAULT
    except (TypeError, ValueError):
        return TENANT_MONTHLY_BUDGET_DEFAULT


async def _current_usage(tenant_id: str, user_id: str) -> dict:
    """Read-only counts for the current day + month for this user, and
    the tenant's total for the current month."""
    day = _day_key()
    month = _month_key()
    day_start = f"{day}T00:00:00+00:00"
    month_start = f"{month}-01T00:00:00+00:00"

    tech_today = await db.zillow_usage.count_documents(
        {"tenant_id": tenant_id, "user_id": user_id, "ts": {"$gte": day_start}}
    )
    tech_month = await db.zillow_usage.count_documents(
        {"tenant_id": tenant_id, "user_id": user_id, "ts": {"$gte": month_start}}
    )
    tenant_month = await db.zillow_usage.count_documents(
        {"tenant_id": tenant_id, "ts": {"$gte": month_start}}
    )
    return {
        "tech_today": tech_today,
        "tech_month": tech_month,
        "tenant_month": tenant_month,
        "tech_daily_cap": TECH_DAILY_CAP,
        "tech_monthly_cap": TECH_MONTHLY_CAP,
    }


async def check_caps(user: dict, tenant: dict) -> dict:
    """Read-only cap check + budget check. Returns:
        {
          allowed: bool,
          reason: "tech_daily_cap"|"tech_monthly_cap"|"tenant_budget_exhausted"|None,
          usage: {...},
          tenant_budget: int, tenant_used: int, tenant_pct: float,
          budget_warning: bool,     # ≥90 %
          reset_at: iso str | None, # tomorrow 00:00 UTC for daily cap
        }
    Super_admin + admin: no per-user cap. Super_admin ALSO bypasses
    tenant-budget when `?override_budget=true` is passed (caller
    handles that flag — see `apply_override`).
    """
    await ensure_indexes()
    tenant_id = tenant["id"]
    user_id = user["id"]
    usage = await _current_usage(tenant_id, user_id)
    budget = await _tenant_budget(tenant)
    tenant_used = usage["tenant_month"]
    pct = tenant_used / budget if budget else 0.0
    out = {
        "allowed": True, "reason": None, "usage": usage,
        "tenant_budget": budget, "tenant_used": tenant_used, "tenant_pct": round(pct, 4),
        "budget_warning": pct >= BUDGET_WARN_THRESHOLD, "reset_at": None,
    }
    role = (user or {}).get("role")
    # Per-user caps only for role=technician.
    if role == "technician":
        if usage["tech_today"] >= TECH_DAILY_CAP:
            tomorrow = (_now() + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            out["allowed"] = False
            out["reason"] = "tech_daily_cap"
            out["reset_at"] = _iso(tomorrow)
            return out
        if usage["tech_month"] >= TECH_MONTHLY_CAP:
            first_of_next_month = (_now().replace(day=28) + timedelta(days=4)).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            out["allowed"] = False
            out["reason"] = "tech_monthly_cap"
            out["reset_at"] = _iso(first_of_next_month)
            return out
    # Tenant budget guard applies to everyone EXCEPT super_admin
    # with override (caller decides via apply_override).
    if tenant_used >= budget:
        out["allowed"] = False
        out["reason"] = "tenant_budget_exhausted"
    return out


async def log_call(user: dict, tenant: dict, endpoint: str, address: str,
                   cost_units: int = 1) -> None:
    """Insert a row into `zillow_usage`. Idempotent per call."""
    ah = address_hash(address) if address else None
    await db.zillow_usage.insert_one({
        "tenant_id": tenant["id"],
        "user_id": user["id"],
        "endpoint": endpoint,
        "address_hash": ah,
        "ts": _iso(),
        "cost_units": cost_units,
    })


async def audit_override(user: dict, tenant: dict, endpoint: str, address: str,
                         tenant_used: int, tenant_budget: int) -> str:
    """Write a `zillow_budget_override` audit event when super_admin
    passes `?override_budget=true` against a saturated budget."""
    import uuid
    aid = str(uuid.uuid4())
    await db.zillow_audit.insert_one({
        "id": aid,
        "event": "zillow_budget_override",
        "tenant_id": tenant["id"],
        "user_id": user["id"],
        "endpoint": endpoint,
        "address_hash": address_hash(address) if address else None,
        "tenant_used_at_override": tenant_used,
        "tenant_budget_at_override": tenant_budget,
        "ts": _iso(),
    })
    return aid


async def read_cache(address: str) -> Optional[dict]:
    ah = address_hash(address)
    row = await db.zillow_cache.find_one({"address_hash": ah}, {"_id": 0})
    if not row:
        return None
    # Belt-and-suspenders TTL check (in case index is late).
    ts = row.get("cached_at")
    if ts:
        try:
            cached_dt = datetime.fromisoformat(ts)
            if _now() - cached_dt > timedelta(days=CACHE_TTL_DAYS):
                return None
        except Exception:
            pass
    return row.get("data")


async def write_cache(address: str, data: dict) -> None:
    ah = address_hash(address)
    now = _now()
    await db.zillow_cache.update_one(
        {"address_hash": ah},
        {"$set": {
            "address_hash": ah,
            "data": data,
            "cached_at": _iso(now),
            "cached_at_dt": now,
        }},
        upsert=True,
    )


async def apply_override_or_fail(caps: dict, user: dict, tenant: dict,
                                 endpoint: str, address: str,
                                 override_budget: bool) -> dict:
    """If caps.allowed is False because of `tenant_budget_exhausted`
    AND user is super_admin AND override_budget is True, unblock the
    call AND write the audit event. Otherwise return caps unchanged.

    Never overrides tech per-user caps.
    """
    if caps["allowed"]:
        return caps
    if caps.get("reason") == "tenant_budget_exhausted" and is_super_admin(user) and override_budget:
        aid = await audit_override(
            user, tenant, endpoint, address,
            caps["tenant_used"], caps["tenant_budget"],
        )
        caps = {**caps, "allowed": True, "reason": None, "override_audit_id": aid}
    return caps


def response_headers(caps: dict) -> dict:
    """Extra HTTP headers to set on a 200 response (spec Step 2)."""
    h = {}
    if caps.get("budget_warning"):
        h["X-Zillow-Budget-Warning"] = "1"
    h["X-Zillow-Tech-Today"] = str(caps["usage"]["tech_today"])
    h["X-Zillow-Tech-Month"] = str(caps["usage"]["tech_month"])
    h["X-Zillow-Tenant-Used"] = str(caps["tenant_used"])
    h["X-Zillow-Tenant-Budget"] = str(caps["tenant_budget"])
    return h
