"""Ship 1 · T3-followup + T3.2 — Pricing Defaults editor + Recommend
price-increase endpoints (admin-only).

Endpoints
=========
GET  /api/settings/pricing-defaults
    Returns spec defaults + tenant overrides for pricing_defaults,
    route_valuation_defaults, pay_model_defaults. Frontend renders
    3 collapsible sections and per-field "Reset to app default".

PUT  /api/settings/pricing-defaults
    Accepts partial patch. Validates numeric ranges. Merges over
    tenant.settings.{pricing_defaults|route_valuation_defaults|pay_model_defaults}.
    422 on any out-of-range value.

GET  /api/calculators/price-increase-suggestion
    ?customer_id=X — returns suggested new price for a low-margin customer
    based on target margin (defaults or override).

POST /api/calculators/recommend-price-increase
    {customer_id, current_price, recommended_price, current_margin_pct,
     effective_date, reason?, action: "preview"|"draft"|"send"}
    Drafts, sends, or previews the email via the Resend-graceful pipeline
    in services/price_increase_email.py. Idempotency key includes the
    price snapshot so a re-fire at a different price is a valid new draft.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, now_iso
from routers.tenants import get_current_tenant
from routers.pool_calculators import (
    PRICING_DEFAULTS, ROUTE_VALUATION_DEFAULTS, PAY_MODEL_DEFAULTS,
    _VISITS_PER_MONTH,
)
from services import price_increase_email as pie


router = APIRouter(tags=["pricing-defaults"])


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    return user


# ─── Validation bounds (guardrail 422 rejection) ────────────────────
_BOUNDS: Dict[str, Dict[str, tuple]] = {
    "pricing_defaults": {
        "tech_hourly_cost":       (5.0, 500.0),
        "overhead_multiplier":    (1.0, 5.0),
        "margin_target_pct":      (0.0, 200.0),
        "tech_time_minutes":      (5, 300),
        "base_weekly":            (0.0, 10000.0),
        "base_bi_weekly":         (0.0, 10000.0),
        "base_monthly":           (0.0, 10000.0),
        "gallons_baseline":       (1000, 500000),
        "gallons_step":           (500, 100000),
        "gallons_step_price":     (0.0, 1000.0),
        "adder_saltwater":        (0.0, 1000.0),
        "adder_heater":           (0.0, 1000.0),
        "adder_spa":              (0.0, 1000.0),
        "adder_automation":       (0.0, 1000.0),
        "adder_chlorine_tabs":    (0.0, 1000.0),
        "adder_liquid_chlorine":  (0.0, 1000.0),
        "zone_default_multiplier": (0.1, 5.0),
    },
    "route_valuation_defaults": {
        "churn_rate_pct":                (0.0, 100.0),
        "tech_cost_percentage":          (0.0, 100.0),
        "chemical_cost_percentage":      (0.0, 100.0),
        "overhead_percentage":           (0.0, 100.0),
        "contract_length_avg_months":    (0, 240),
        "multiple_min":                  (0.1, 20.0),
        "multiple_max":                  (0.1, 20.0),
        "churn_low_pct":                 (0.0, 100.0),
        "churn_high_pct":                (0.0, 100.0),
        "contract_short_months":         (0, 240),
        "contract_long_months":          (0, 240),
        "industry_per_customer_low":     (0, 100000),
        "industry_per_customer_high":    (0, 100000),
    },
    "pay_model_defaults": {
        "hourly_rate":                   (0.0, 500.0),
        "per_pool_rate":                 (0.0, 500.0),
        "route_buy_pct":                 (0.0, 100.0),
        "chemical_cost_percentage":      (0.0, 100.0),
        "overhead_percentage":           (0.0, 100.0),
    },
}

_ENUM_FIELDS = {
    "route_valuation_defaults.route_density": {"dense", "medium", "spread"},
}

_DICT_FIELDS = {
    "route_valuation_defaults.density_weights",
}


def _validate(section: str, key: str, value):
    full = f"{section}.{key}"
    if full in _ENUM_FIELDS:
        if str(value) not in _ENUM_FIELDS[full]:
            raise HTTPException(422, f"{full}: must be one of {sorted(_ENUM_FIELDS[full])}")
        return value
    if full in _DICT_FIELDS:
        if not isinstance(value, dict):
            raise HTTPException(422, f"{full}: must be a dict")
        return value
    bounds = _BOUNDS.get(section, {}).get(key)
    if bounds is None:
        # Unknown key — allow but do not enforce bounds. Prevents accidental
        # rejection if the constants dict grows in a later ship.
        return value
    lo, hi = bounds
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{full}: must be numeric")
    if not (lo <= num <= hi):
        raise HTTPException(422, f"{full}: must be in [{lo}, {hi}]")
    return num if isinstance(bounds[0], float) else int(num)


# ─── GET /api/settings/pricing-defaults ──────────────────────────────
@router.get("/settings/pricing-defaults")
async def get_pricing_defaults(
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    settings = (tenant.get("settings") or {})
    return {
        "spec_defaults": {
            "pricing_defaults":         PRICING_DEFAULTS,
            "route_valuation_defaults": ROUTE_VALUATION_DEFAULTS,
            "pay_model_defaults":       PAY_MODEL_DEFAULTS,
        },
        "tenant_overrides": {
            "pricing_defaults":         settings.get("pricing_defaults")         or {},
            "route_valuation_defaults": settings.get("route_valuation_defaults") or {},
            "pay_model_defaults":       settings.get("pay_model_defaults")       or {},
        },
        "effective": {
            "pricing_defaults":         {**PRICING_DEFAULTS,
                                         **(settings.get("pricing_defaults") or {})},
            "route_valuation_defaults": {**ROUTE_VALUATION_DEFAULTS,
                                         **(settings.get("route_valuation_defaults") or {})},
            "pay_model_defaults":       {**PAY_MODEL_DEFAULTS,
                                         **(settings.get("pay_model_defaults") or {})},
        },
    }


class PricingDefaultsIn(BaseModel):
    pricing_defaults: Optional[Dict[str, Any]] = None
    route_valuation_defaults: Optional[Dict[str, Any]] = None
    pay_model_defaults: Optional[Dict[str, Any]] = None


@router.put("/settings/pricing-defaults")
async def put_pricing_defaults(
    body: PricingDefaultsIn,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    existing = tenant.get("settings") or {}
    payload = body.dict(exclude_none=True)

    set_ops: Dict[str, Any] = {"updated_at": now_iso()}
    for section, patch in payload.items():
        if not isinstance(patch, dict):
            raise HTTPException(422, f"{section}: must be an object")
        current = existing.get(section) or {}
        merged: Dict[str, Any] = {**current}
        for key, value in patch.items():
            if value is None:
                # Explicit null → reset to app default (remove override).
                merged.pop(key, None)
            else:
                merged[key] = _validate(section, key, value)
        set_ops[f"settings.{section}"] = merged

    await db.tenants.update_one({"id": tenant["id"]}, {"$set": set_ops})
    fresh = await db.tenants.find_one({"id": tenant["id"]}, {"_id": 0})
    settings = (fresh or {}).get("settings") or {}
    return {
        "ok": True,
        "tenant_overrides": {
            "pricing_defaults":         settings.get("pricing_defaults")         or {},
            "route_valuation_defaults": settings.get("route_valuation_defaults") or {},
            "pay_model_defaults":       settings.get("pay_model_defaults")       or {},
        },
    }


# ─── Price-increase suggestion helper (T3.2 modal open) ──────────────
@router.get("/calculators/price-increase-suggestion")
async def price_increase_suggestion(
    customer_id: str = Query(...),
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Given a customer flagged low_margin / negative_margin, compute a
    per-visit recommended price that reaches the tenant's target margin.
    Uses the same in-cost formula as the cost-per-pool tab so the numbers
    line up exactly.
    """
    d_pricing = {**PRICING_DEFAULTS, **((tenant.get("settings") or {}).get("pricing_defaults") or {})}
    customer = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not customer:
        raise HTTPException(404, "Customer not found")
    plan = await db.billing_plans.find_one(
        {"tenant_id": tenant["id"], "customer_id": customer_id, "active": True},
        {"_id": 0}, sort=[("created_at", -1)])
    if not plan:
        raise HTTPException(404, "Customer has no active billing plan")

    vt = (plan.get("frequency") or "").lower()
    vpm = _VISITS_PER_MONTH.get(vt) or 0.0
    if not vpm:
        raise HTTPException(400, f"Unsupported billing frequency: {vt}")

    # Baseline chemical + labor + overhead per visit (mirror cost_per_pool).
    cost_map = {}
    async for row in db.chemical_costs.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ):
        cost_map[row["chemical_slug"]] = row
    standard_mix = [
        {"chemical_slug": "liquid_chlorine", "quantity": 1.0},
        {"chemical_slug": "muriatic_acid", "quantity": 0.25},
        {"chemical_slug": "chlorine_tabs", "quantity": 2},
    ]
    baseline_chem = sum(
        (cost_map.get(m["chemical_slug"], {}).get("cost_per_unit_cents", 0) / 100.0)
        * m["quantity"] for m in standard_mix
    )
    labor = (d_pricing["tech_time_minutes"] / 60.0) * d_pricing["tech_hourly_cost"]
    per_visit_in_cost = round((baseline_chem + labor) * d_pricing["overhead_multiplier"], 2)

    # Current monthly revenue → current per-visit price.
    monthly_amt = float(plan.get("amount") or 0)
    if vt in ("weekly", "biweekly", "bi-weekly"):
        current_price_per_visit = round(monthly_amt, 2)  # plan.amount is per-visit
        current_monthly_revenue = round(monthly_amt * vpm, 2)
    elif vt == "monthly":
        current_price_per_visit = round(monthly_amt, 2)
        current_monthly_revenue = round(monthly_amt, 2)
    elif vt == "quarterly":
        current_price_per_visit = round(monthly_amt, 2)
        current_monthly_revenue = round(monthly_amt / 3.0, 2)
    else:
        current_price_per_visit = 0.0
        current_monthly_revenue = 0.0

    # Target price = in-cost / (1 - margin_target_pct/100)
    target_margin = float(d_pricing["margin_target_pct"]) / 100.0
    if target_margin >= 1.0:
        target_margin = 0.9
    recommended_per_visit = round(per_visit_in_cost / max(1e-3, 1 - target_margin), 2)

    # Current margin
    current_monthly_in_cost = round(per_visit_in_cost * vpm, 2)
    margin_amount = round(current_monthly_revenue - current_monthly_in_cost, 2)
    current_margin_pct = round(margin_amount / current_monthly_revenue * 100, 1) if current_monthly_revenue else None

    return {
        "customer_id": customer_id,
        "customer_name": customer.get("name") or "",
        "customer_email": customer.get("email") or "",
        "visit_type": vt,
        "visits_per_month": round(vpm, 3),
        "per_visit_in_cost": per_visit_in_cost,
        "current_price_per_visit": current_price_per_visit,
        "current_monthly_revenue": current_monthly_revenue,
        "current_monthly_in_cost": current_monthly_in_cost,
        "current_margin_pct": current_margin_pct,
        "target_margin_pct": d_pricing["margin_target_pct"],
        "recommended_price_per_visit": recommended_per_visit,
    }


# ─── Recommend price increase (draft / send / preview) ───────────────
class RecommendPriceIncreaseIn(BaseModel):
    customer_id: str
    current_price: float
    recommended_price: float
    current_margin_pct: Optional[float] = None
    effective_date: Optional[str] = None  # YYYY-MM-DD; default = today + 30d
    reason: Optional[str] = None
    action: str = Field("preview", description="preview | draft | send")


@router.post("/calculators/recommend-price-increase")
async def recommend_price_increase(
    body: RecommendPriceIncreaseIn,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if body.action not in ("preview", "draft", "send"):
        raise HTTPException(422, "action must be preview | draft | send")
    if body.recommended_price <= 0 or body.current_price < 0:
        raise HTTPException(422, "prices must be non-negative and recommended > 0")

    customer = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not customer:
        raise HTTPException(404, "Customer not found")

    effective_date = body.effective_date or (
        (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    )

    if body.action == "preview":
        rendered = pie.render_email(
            tenant, customer,
            current_price=body.current_price,
            recommended_price=body.recommended_price,
            current_margin_pct=body.current_margin_pct,
            effective_date=effective_date,
            reason=body.reason,
        )
        existing = await pie.find_existing(
            tenant["id"], body.customer_id,
            body.current_price, body.recommended_price,
        )
        return {
            "action": "preview",
            "customer_email": customer.get("email") or "",
            "subject": rendered["subject"],
            "html": rendered["html"],
            "text": rendered["text"],
            "existing_status": (existing or {}).get("status"),
            "existing_id": (existing or {}).get("id"),
        }

    row = await pie.save_or_send(
        tenant, customer,
        current_price=body.current_price,
        recommended_price=body.recommended_price,
        current_margin_pct=body.current_margin_pct,
        effective_date=effective_date,
        reason=body.reason,
        action=body.action,
    )
    return {
        "action": body.action,
        "id": row["id"],
        "status": row["status"],
        "customer_email": row.get("to") or "",
        "subject": row["subject"],
        "resend_id": row.get("resend_id"),
        "error": row.get("error"),
    }
