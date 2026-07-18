"""Ship 2 · Growth Playbook — one-call composition of T5.1 (route
valuation) + T6 (state market rates) into 3 scenarios:

    1) Today's route value (portfolio at current pricing)
    2) Market-median scenario (portfolio repriced to state market median)
    3) Churn breakeven (max additional churn the market scenario can
       absorb and still hit today's valuation)

All admin + super_admin only. Reuses the same defaults + math as
routers/pool_calculators.py so the numbers stay in lockstep.

Ship 3 · Item C: every playbook fetch writes a snapshot row to
`growth_playbook_snapshots` (2-year TTL). New GET history endpoint
surfaces recent snapshots for future chart rendering.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant
from routers.pool_calculators import (
    ROUTE_VALUATION_DEFAULTS, PRICING_DEFAULTS,
    _rv_defaults, _pricing_defaults, _VISITS_PER_MONTH, _lerp,
)
from services.service_price_market import BY_STATE, SERVICE_TYPES


router = APIRouter(prefix="/analysis", tags=["analysis"])


_SNAPSHOTS_INDEX_READY = False


async def _ensure_snapshot_indexes():
    """Idempotent TTL + query indexes on growth_playbook_snapshots."""
    global _SNAPSHOTS_INDEX_READY
    if _SNAPSHOTS_INDEX_READY:
        return
    try:
        # 2-year TTL on snapshot_at_dt (BSON date). String snapshot_at kept
        # separately for readable API output.
        await db.growth_playbook_snapshots.create_index(
            "snapshot_at_dt", expireAfterSeconds=63072000)
        await db.growth_playbook_snapshots.create_index(
            [("tenant_id", 1), ("snapshot_at_dt", -1)])
        _SNAPSHOTS_INDEX_READY = True
    except Exception as e:
        logger.warning(f"growth_playbook_snapshots index creation failed: {e}")


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    return user


# ─── Helpers ─────────────────────────────────────────────────────────
def _get_tenant_state(tenant: dict) -> tuple[str, bool]:
    """Return (state_code, fallback_used). Checks tenant fields in order:
      1. tenant.state_code (top-level)
      2. tenant.settings.state_code
      3. tenant.address.state / tenant.billing_address.state (2-char)
    Fallback = "AZ" (tenant is Pool & Landscaping of Vistancia).
    """
    if not tenant:
        return "AZ", True
    for k in ("state_code",):
        v = tenant.get(k)
        if v and isinstance(v, str) and len(v) == 2:
            return v.upper(), False
    settings = tenant.get("settings") or {}
    s = settings.get("state_code")
    if s and isinstance(s, str) and len(s) == 2:
        return s.upper(), False
    for k in ("address", "billing_address"):
        addr = tenant.get(k) or {}
        st = addr.get("state") if isinstance(addr, dict) else None
        if st and isinstance(st, str) and len(st) == 2:
            return st.upper(), False
    return "AZ", True


def _dominant_frequency(freq_counts: Dict[str, int]) -> tuple[str, str]:
    """Pick the most-common visit frequency in the portfolio → return
    (billing_frequency, matching_service_type_from_T6)."""
    mapping = {
        "weekly":    "weekly_pool_service",
        "biweekly":  "biweekly_pool_service",
        "bi-weekly": "biweekly_pool_service",
        "monthly":   "monthly_pool_service",
    }
    if not freq_counts:
        return "weekly", "weekly_pool_service"
    top = max(freq_counts.items(), key=lambda kv: kv[1])[0]
    return top, mapping.get(top, "weekly_pool_service")


def _compute_multiple(
    d: dict,
    density: str,
    churn_pct: float,
    contract_months: float,
) -> Dict[str, float]:
    """Mirror routers/pool_calculators.route_valuation multiple math so
    both endpoints stay in lockstep. Returns
    {multiple, density_factor, churn_factor, contract_factor, combined_factor}.
    """
    density_factor = float(d["density_weights"].get(density, 0.55))
    churn_factor = 1 - (max(0.0, churn_pct - d["churn_low_pct"])
                         / max(1e-6, (d["churn_high_pct"] - d["churn_low_pct"])))
    churn_factor = max(0.0, min(1.0, churn_factor))
    contract_factor = ((contract_months - d["contract_short_months"])
                       / max(1e-6, (d["contract_long_months"] - d["contract_short_months"])))
    contract_factor = max(0.0, min(1.0, contract_factor))
    combined = (density_factor + churn_factor + contract_factor) / 3.0
    return {
        "multiple": _lerp(d["multiple_min"], d["multiple_max"], combined),
        "density_factor": density_factor,
        "churn_factor": churn_factor,
        "contract_factor": contract_factor,
        "combined_factor": combined,
    }


def _solve_breakeven_churn(
    d: dict,
    density: str,
    contract_months: float,
    target_multiple: float,
) -> tuple[float, bool, bool]:
    """Solve for churn_new such that _compute_multiple(...) == target_multiple.
    Returns (churn_new_pct, saturated_low, saturated_high) — the saturated
    flags indicate the target could not be hit inside the churn window.
    saturated_low  → churn_factor pinned at 1.0 (churn_new = churn_low) —
                     target multiple STILL higher than what zero churn can produce.
    saturated_high → churn_factor pinned at 0.0 (churn_new = churn_high) —
                     target multiple STILL lower than max-churn multiple; you
                     have enormous headroom.
    """
    density_factor = float(d["density_weights"].get(density, 0.55))
    contract_factor = ((contract_months - d["contract_short_months"])
                       / max(1e-6, (d["contract_long_months"] - d["contract_short_months"])))
    contract_factor = max(0.0, min(1.0, contract_factor))

    span_multiple = d["multiple_max"] - d["multiple_min"]
    if span_multiple <= 0:
        return d["churn_high_pct"], False, True
    combined_target = (target_multiple - d["multiple_min"]) / span_multiple
    churn_factor_target = 3.0 * combined_target - density_factor - contract_factor

    saturated_low = churn_factor_target > 1.0
    saturated_high = churn_factor_target < 0.0
    churn_factor_target = max(0.0, min(1.0, churn_factor_target))
    # churn_factor = 1 - (churn - low) / (high - low)  → churn = low + (1 - cf) * (high - low)
    churn_new = d["churn_low_pct"] + (1.0 - churn_factor_target) \
                * (d["churn_high_pct"] - d["churn_low_pct"])
    return churn_new, saturated_low, saturated_high


# ─── Input model ─────────────────────────────────────────────────────
class GrowthPlaybookIn(BaseModel):
    # All fields optional — endpoint auto-pulls from the tenant if omitted.
    active_customers: Optional[int] = None
    avg_monthly_revenue_per_customer: Optional[float] = None
    dominant_frequency: Optional[str] = None
    state_code: Optional[str] = None
    density: Optional[str] = None
    churn_pct: Optional[float] = None
    contract_months: Optional[float] = None


# ─── POST /api/analysis/growth-playbook ──────────────────────────────
@router.post("/growth-playbook")
async def growth_playbook(
    body: GrowthPlaybookIn,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    d = _rv_defaults(tenant)
    p = _pricing_defaults(tenant)

    # ── Portfolio: active customers + median monthly revenue ────────
    if body.active_customers is None:
        cust_count = await db.customers.count_documents({
            "tenant_id": tenant["id"],
            "$or": [{"is_active": True}, {"is_active": {"$exists": False}}],
        })
    else:
        cust_count = int(max(0, body.active_customers))

    freq_counts: Dict[str, int] = {}
    monthly_amounts: list[float] = []
    async for plan in db.billing_plans.find(
        {"tenant_id": tenant["id"], "active": True}, {"_id": 0}
    ):
        amt = float(plan.get("amount") or 0)
        freq = (plan.get("frequency") or "").lower()
        vpm = _VISITS_PER_MONTH.get(freq)
        if not vpm or amt <= 0:
            continue
        freq_counts[freq] = freq_counts.get(freq, 0) + 1
        if freq in ("weekly", "biweekly", "bi-weekly"):
            monthly_amounts.append(amt * vpm)
        elif freq == "monthly":
            monthly_amounts.append(amt)
        elif freq == "quarterly":
            monthly_amounts.append(amt / 3.0)

    if body.avg_monthly_revenue_per_customer is None:
        avg_monthly = median(monthly_amounts) if monthly_amounts else 0.0
    else:
        avg_monthly = float(body.avg_monthly_revenue_per_customer)

    today_total_monthly = round(avg_monthly * cust_count, 2)

    # ── Portfolio dominant frequency + tenant state ────────────────
    dominant_freq, service_type = _dominant_frequency(freq_counts)
    if body.dominant_frequency:
        dominant_freq = body.dominant_frequency
        mapping = {
            "weekly": "weekly_pool_service", "biweekly": "biweekly_pool_service",
            "bi-weekly": "biweekly_pool_service", "monthly": "monthly_pool_service",
        }
        service_type = mapping.get(dominant_freq, service_type)

    if body.state_code:
        state_code = body.state_code.upper()
        state_fallback = False
    else:
        state_code, state_fallback = _get_tenant_state(tenant)

    market_row = BY_STATE.get(state_code)
    if not market_row:
        # Unknown state — fall back to AZ + flag it.
        market_row = BY_STATE["AZ"]
        state_code = "AZ"
        state_fallback = True

    market_rates = market_row["market_rates"].get(service_type, {})
    market_median_per_visit = float(market_rates.get("median") or 0)

    # visits/month for the dominant frequency (default weekly = 52/12)
    vpm = _VISITS_PER_MONTH.get(dominant_freq, _VISITS_PER_MONTH["weekly"])
    market_median_monthly_per_customer = round(market_median_per_visit * vpm, 2)

    # ── T5.1 assumptions ────────────────────────────────────────────
    density = (body.density or d["route_density"]).lower()
    churn_pct = body.churn_pct if body.churn_pct is not None else d["churn_rate_pct"]
    contract_months = body.contract_months if body.contract_months is not None \
        else d["contract_length_avg_months"]

    # ── Scenario 1 · Today's route value ────────────────────────────
    today_calc = _compute_multiple(d, density, churn_pct, contract_months)
    today_multiple = round(today_calc["multiple"], 2)
    today_valuation = round(today_total_monthly * today_multiple, 2)
    today_annual_revenue = round(today_total_monthly * 12, 2)
    today_per_customer_val = round(today_valuation / cust_count, 2) if cust_count else 0.0

    # ── Scenario 2 · Market-median scenario ─────────────────────────
    market_total_monthly = round(market_median_monthly_per_customer * cust_count, 2)
    # Density/churn/contract unchanged in the market scenario (per spec).
    market_multiple = today_multiple  # same assumptions → same multiple
    market_valuation = round(market_total_monthly * market_multiple, 2)
    market_annual_revenue = round(market_total_monthly * 12, 2)
    delta_monthly = round(market_total_monthly - today_total_monthly, 2)
    delta_annual = round(market_annual_revenue - today_annual_revenue, 2)
    delta_valuation = round(market_valuation - today_valuation, 2)

    price_delta_positive = delta_monthly > 0
    market_position = (
        "below_market" if avg_monthly < market_median_monthly_per_customer * 0.85
        else "above_market" if avg_monthly > market_median_monthly_per_customer * 1.15
        else "at_market"
    ) if market_median_monthly_per_customer > 0 and avg_monthly > 0 else "unknown"

    # ── Scenario 3 · Churn breakeven ────────────────────────────────
    # Solve for churn_new such that market_total × multiple(churn_new) == today_valuation
    if not price_delta_positive or market_total_monthly <= 0:
        # Skip playbook — repricing would REDUCE (or not change) valuation.
        churn_breakeven = None
        churn_delta = None
        breakeven_flavor = "skip_playbook"
        saturated_low = False
        saturated_high = False
    else:
        target_multiple = today_valuation / market_total_monthly
        churn_new, sat_low, sat_high = _solve_breakeven_churn(
            d, density, contract_months, target_multiple)
        churn_breakeven = round(churn_new, 2)
        churn_delta = round(churn_new - churn_pct, 2)
        saturated_low, saturated_high = sat_low, sat_high
        if churn_delta <= 0:
            breakeven_flavor = "thin"
        elif saturated_high or churn_delta > 50:
            breakeven_flavor = "very_generous"
        elif churn_delta < 3:
            breakeven_flavor = "thin"
        else:
            breakeven_flavor = "healthy"

    response = {
        "tenant_id": tenant["id"],
        "state_code": state_code,
        "state_name": market_row["state_name"],
        "state_fallback_used": state_fallback,
        "service_type": service_type,
        "dominant_frequency": dominant_freq,
        "visits_per_month": round(vpm, 3),
        "active_customers": cust_count,
        "assumptions": {
            "density": density,
            "churn_pct": churn_pct,
            "contract_length_avg_months": contract_months,
            "target_margin_pct": p["margin_target_pct"],
            "multiple_min": d["multiple_min"],
            "multiple_max": d["multiple_max"],
        },
        "today": {
            "avg_monthly_revenue_per_customer": round(avg_monthly, 2),
            "total_monthly_revenue": today_total_monthly,
            "annual_revenue": today_annual_revenue,
            "route_multiple": today_multiple,
            "route_valuation": today_valuation,
            "valuation_per_customer": today_per_customer_val,
        },
        "market_median_scenario": {
            "market_median_per_visit": market_median_per_visit,
            "market_median_monthly_per_customer": market_median_monthly_per_customer,
            "market_position": market_position,
            "total_monthly_revenue": market_total_monthly,
            "annual_revenue": market_annual_revenue,
            "route_multiple": market_multiple,
            "route_valuation": market_valuation,
            "delta_monthly_revenue": delta_monthly,
            "delta_annual_revenue": delta_annual,
            "delta_valuation": delta_valuation,
            "price_delta_positive": price_delta_positive,
        },
        "churn_breakeven": {
            "current_churn_pct": churn_pct,
            "breakeven_churn_pct": churn_breakeven,
            "additional_churn_tolerated_pct": churn_delta,
            "flavor": breakeven_flavor,
            "saturated_low": saturated_low,
            "saturated_high": saturated_high,
        },
    }
    # Ship 3 · Item C — snapshot write (non-blocking best-effort).
    await _write_snapshot(tenant, user, response)
    return response


async def _write_snapshot(tenant: dict, user: dict, r: dict) -> None:
    """Persist a compact snapshot for future chart rendering. Never
    raises — silently logs and returns if the write fails."""
    try:
        await _ensure_snapshot_indexes()
        now = datetime.now(timezone.utc)
        await db.growth_playbook_snapshots.insert_one({
            "id": new_id(),
            "tenant_id": tenant["id"],
            "snapshot_at": now.isoformat(),
            "snapshot_at_dt": now,  # BSON date for TTL
            "requested_by_user_id": user["id"],
            "active_customers": r["active_customers"],
            "monthly_revenue": r["today"]["total_monthly_revenue"],
            "today_valuation": r["today"]["route_valuation"],
            "today_multiple": r["today"]["route_multiple"],
            "market_state": r["state_code"],
            "market_median_price": r["market_median_scenario"]["market_median_per_visit"],
            "market_valuation": r["market_median_scenario"]["route_valuation"],
            "delta_valuation": r["market_median_scenario"]["delta_valuation"],
            "churn_breakeven_pct": r["churn_breakeven"]["breakeven_churn_pct"],
            "playbook_flavor": r["churn_breakeven"]["flavor"],
            "state_fallback_used": r["state_fallback_used"],
            "dominant_frequency": r["dominant_frequency"],
        })
    except Exception as e:
        logger.warning(f"growth_playbook snapshot write failed: {type(e).__name__}: {e}")


@router.get("/growth-playbook/history")
async def growth_playbook_history(
    days: int = Query(90, ge=1, le=730),
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Return snapshot rows for the tenant within the last `days` days,
    sorted chronologically (oldest first) for straightforward
    chart-x-axis rendering. Strict tenant isolation.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows: list[dict] = []
    async for row in db.growth_playbook_snapshots.find({
        "tenant_id": tenant["id"],
        "snapshot_at": {"$gte": cutoff},
    }, {"_id": 0, "snapshot_at_dt": 0}).sort("snapshot_at", 1):
        rows.append(row)
    return {"count": len(rows), "days": days, "rows": rows}
