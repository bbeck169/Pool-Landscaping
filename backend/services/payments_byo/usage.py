"""Phase I1.7.d · Feb-2026 — Payments-BYO usage tracking + monthly cap.

Two collections:

  ``tenant_payments_provider``
      Sidecar metadata (``monthly_request_cap``, non-secret extras)
      stored plaintext so cap-checks avoid decrypting on every call.

  ``tenant_payments_usage``
      One row per ``(tenant_id, provider_short, period_yyyymm)`` with
      per-op counters: ``charge_count``, ``refund_count`` and
      ``ops_total`` (sum of both).

Cap semantics (identical to AI/Maps/Calendars):
  * ``monthly_request_cap = None`` → UNLIMITED.
  * ``monthly_request_cap = 0``     → BLOCK ALL.
  * ``monthly_request_cap > 0``     → hard block at ``ops_total >= cap``,
                                       soft warn at ``ops_total >= 0.8*cap``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._helpers import current_period_yyyymm, now_iso
from .models import TenantPaymentsUsageCapExceeded


PROVIDER_META_COLLECTION = "tenant_payments_provider"
USAGE_COLLECTION = "tenant_payments_usage"

SOFT_WARN_RATIO = 0.8


def _default_db():
    from config import db
    return db


# ── Provider metadata (cap + extras) ─────────────────────────────
async def upsert_provider_meta(
    *, tenant_id: str, provider: str,
    monthly_request_cap: Optional[int] = None,
    extras: Optional[Dict[str, Any]] = None,
    db=None,
) -> Dict[str, Any]:
    if db is None:
        db = _default_db()
    set_fields: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "provider": provider,
        "monthly_request_cap": monthly_request_cap,
        "extras": dict(extras or {}),
        "updated_at": now_iso(),
    }
    await db[PROVIDER_META_COLLECTION].update_one(
        {"tenant_id": tenant_id, "provider": provider},
        {"$set": set_fields, "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )
    return set_fields


async def get_provider_meta(
    *, tenant_id: str, provider: str, db=None,
) -> Optional[Dict[str, Any]]:
    if db is None:
        db = _default_db()
    return await db[PROVIDER_META_COLLECTION].find_one(
        {"tenant_id": tenant_id, "provider": provider},
        {"_id": 0},
    )


async def remove_provider_meta(
    *, tenant_id: str, provider: str, db=None,
) -> bool:
    if db is None:
        db = _default_db()
    res = await db[PROVIDER_META_COLLECTION].delete_one(
        {"tenant_id": tenant_id, "provider": provider}
    )
    return res.deleted_count > 0


# ── Usage tracking ───────────────────────────────────────────────
async def record_op(
    *, tenant_id: str, provider: str, op: str,
    period_yyyymm: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """Atomically increment the per-op counter. ``op`` is "charge" or "refund"."""
    if db is None:
        db = _default_db()
    period = period_yyyymm or current_period_yyyymm()
    field = "charge_count" if op == "charge" else "refund_count"
    await db[USAGE_COLLECTION].update_one(
        {"tenant_id": tenant_id, "provider": provider, "period_yyyymm": period},
        {
            "$inc": {field: 1, "ops_total": 1},
            "$set": {"updated_at": now_iso()},
            "$setOnInsert": {"created_at": now_iso()},
        },
        upsert=True,
    )
    row = await db[USAGE_COLLECTION].find_one(
        {"tenant_id": tenant_id, "provider": provider, "period_yyyymm": period},
        {"_id": 0},
    )
    return row or {}


async def get_usage_row(
    *, tenant_id: str, provider: str,
    period_yyyymm: Optional[str] = None,
    db=None,
) -> Optional[Dict[str, Any]]:
    if db is None:
        db = _default_db()
    period = period_yyyymm or current_period_yyyymm()
    return await db[USAGE_COLLECTION].find_one(
        {"tenant_id": tenant_id, "provider": provider, "period_yyyymm": period},
        {"_id": 0},
    )


async def get_all_usage_rows(
    *, tenant_id: str,
    period_yyyymm: Optional[str] = None,
    db=None,
) -> List[Dict[str, Any]]:
    if db is None:
        db = _default_db()
    period = period_yyyymm or current_period_yyyymm()
    out: List[Dict[str, Any]] = []
    async for row in db[USAGE_COLLECTION].find(
        {"tenant_id": tenant_id, "period_yyyymm": period},
        {"_id": 0},
    ):
        out.append(row)
    return out


# ── Cap enforcement ──────────────────────────────────────────────
def _compute_status(*, used: int, cap: Optional[int]) -> str:
    if cap is None:
        return "ok"
    if cap <= 0:
        return "blocked"
    if used >= cap:
        return "blocked"
    if used >= int(cap * SOFT_WARN_RATIO):
        return "warn"
    return "ok"


async def enforce_cap_or_raise(
    *, tenant_id: str, provider: str, db=None,
) -> Dict[str, Any]:
    meta = await get_provider_meta(tenant_id=tenant_id, provider=provider, db=db)
    cap: Optional[int] = None
    if meta is not None:
        raw_cap = meta.get("monthly_request_cap")
        cap = int(raw_cap) if raw_cap is not None else None
    row = await get_usage_row(tenant_id=tenant_id, provider=provider, db=db)
    used = int((row or {}).get("ops_total", 0) or 0)
    status = _compute_status(used=used, cap=cap)
    if status == "blocked":
        raise TenantPaymentsUsageCapExceeded(provider=provider, cap=int(cap or 0), used=used)
    return {"used": used, "cap": cap, "status": status}
