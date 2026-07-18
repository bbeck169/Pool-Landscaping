"""Phase T1 + T2 — Pool chemistry & sizing calculators (stateless).

All 5 endpoints are pure math — no DB writes, no side effects. RBAC:
super_admin + admin + technician allowed; customer + anonymous → 403.

Endpoints:
  * POST /api/calculators/lsi          — Langelier Saturation Index
  * POST /api/calculators/volume       — Pool volume (gal)
  * POST /api/calculators/salt         — Salt to add (lbs)
  * POST /api/calculators/turnover     — Turnover time + code compliance
  * POST /api/calculators/heater-size  — BTU + monthly cost estimate
"""
from __future__ import annotations
import math
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from utils import get_current_user

router = APIRouter(prefix="/calculators", tags=["calculators"])


def require_tech_or_above(user: dict = Depends(get_current_user)) -> dict:
    role = (user or {}).get("role")
    if role in ("super_admin", "admin", "technician"):
        return user
    raise HTTPException(status_code=403, detail="Calculators require admin or technician role")


# ─── LSI ──────────────────────────────────────────────────────────────
# Same TF table the mobile calculator uses. Linear interpolation between
# breakpoints; clamps to 0 below 32°F and 0.9 above 105°F.
_TF_TABLE = [(32, 0.0), (37, 0.1), (46, 0.2), (53, 0.3), (60, 0.4),
             (66, 0.5), (76, 0.6), (84, 0.7), (94, 0.8), (105, 0.9)]


def _temp_factor(f: float) -> float:
    if f <= 32: return 0.0
    if f >= 105: return 0.9
    for i in range(len(_TF_TABLE) - 1):
        t0, v0 = _TF_TABLE[i]
        t1, v1 = _TF_TABLE[i + 1]
        if t0 <= f <= t1:
            return v0 + ((f - t0) / (t1 - t0)) * (v1 - v0)
    return 0.6


class LsiIn(BaseModel):
    ph: float
    temp_f: float
    ch: float = Field(..., description="Calcium hardness ppm")
    ta: float = Field(..., description="Total alkalinity ppm")
    tds: float = 1000.0
    cya: Optional[float] = None
    cya_correction: str = Field("third", description="third|quarter|none")


@router.post("/lsi")
async def lsi_calc(body: LsiIn, user: dict = Depends(require_tech_or_above)):
    if body.ch <= 0 or body.ta <= 0 or body.ph <= 0:
        raise HTTPException(422, "pH, calcium hardness, and total alkalinity must be > 0")
    cya_val = body.cya or 0
    if body.cya_correction == "third":
        cya_adj = cya_val / 3
    elif body.cya_correction == "quarter":
        cya_adj = cya_val / 4
    else:
        cya_adj = 0
    carb_alk = max(1, body.ta - cya_adj)
    cf = math.log10(body.ch) - 0.4
    af = math.log10(carb_alk)
    tf = _temp_factor(body.temp_f)
    tds_const = 12.2 if body.tds >= 1000 else 12.1
    lsi = body.ph + tf + cf + af - tds_const
    if lsi < -0.3:
        interp = "corrosive"
        note = "Water is corrosive — add alkalinity/calcium to raise LSI."
    elif lsi > 0.3:
        interp = "scaling"
        note = "Water is scale-forming — lower pH/alkalinity."
    else:
        interp = "balanced"
        note = "Water is balanced (-0.3 ≤ LSI ≤ +0.3)."
    return {"lsi": round(lsi, 2), "interpretation": interp, "note": note,
            "components": {"tf": round(tf, 2), "cf": round(cf, 3),
                            "af": round(af, 3), "tds_const": tds_const,
                            "cya_adj": round(cya_adj, 2)}}


# ─── Volume ───────────────────────────────────────────────────────────
class VolumeIn(BaseModel):
    shape: str = Field(..., description="rectangle|oval|circle|freeform")
    length: Optional[float] = None
    width: Optional[float] = None
    radius: Optional[float] = None
    avg_depth: Optional[float] = None
    shallow_depth: Optional[float] = None
    deep_depth: Optional[float] = None


@router.post("/volume")
async def volume_calc(body: VolumeIn, user: dict = Depends(require_tech_or_above)):
    depth = body.avg_depth
    if depth is None and body.shallow_depth is not None and body.deep_depth is not None:
        depth = (body.shallow_depth + body.deep_depth) / 2
    if not depth or depth <= 0:
        raise HTTPException(422, "avg_depth or (shallow_depth + deep_depth) required")
    shape = (body.shape or "").lower()
    if shape == "rectangle":
        if not body.length or not body.width:
            raise HTTPException(422, "length + width required for rectangle")
        gallons = body.length * body.width * depth * 7.48
        formula = "L × W × avg_depth × 7.48"
    elif shape == "oval":
        if not body.length or not body.width:
            raise HTTPException(422, "length + width required for oval")
        gallons = body.length * body.width * depth * 5.9
        formula = "L × W × avg_depth × 5.9"
    elif shape == "circle":
        if not body.radius:
            raise HTTPException(422, "radius required for circle")
        gallons = math.pi * (body.radius ** 2) * depth * 7.48
        formula = "π × r² × avg_depth × 7.48"
    elif shape == "freeform":
        if not body.length or not body.width:
            raise HTTPException(422, "length + width required for freeform")
        gallons = body.length * body.width * depth * 7.0
        formula = "L × W × avg_depth × 7.0 (conservative)"
    else:
        raise HTTPException(422, "shape must be rectangle|oval|circle|freeform")
    return {"gallons": round(gallons), "avg_depth": round(depth, 2),
            "formula": formula, "shape": shape}


# ─── Salt ─────────────────────────────────────────────────────────────
class SaltIn(BaseModel):
    pool_gallons: float
    current_salt: float
    target_salt: float = 3200.0


@router.post("/salt")
async def salt_calc(body: SaltIn, user: dict = Depends(require_tech_or_above)):
    if body.pool_gallons <= 0:
        raise HTTPException(422, "pool_gallons must be > 0")
    delta = body.target_salt - body.current_salt
    if delta <= 0:
        # Over-salted → dilution estimate.
        over = body.current_salt - body.target_salt
        # Approximate replacement fraction to hit target.
        drain_frac = max(0, min(1, over / body.current_salt)) if body.current_salt else 0
        drain_gal = round(body.pool_gallons * drain_frac)
        return {"lbs_to_add": 0.0,
                "note": f"Salt is at or above target. To reduce, drain approximately {drain_gal:,} gallons and refill with fresh water.",
                "over_by_ppm": round(over, 1)}
    lbs = body.pool_gallons * delta / 120000
    return {"lbs_to_add": round(lbs, 1),
            "bags_40lb": round(lbs / 40, 2),
            "note": f"Add {round(lbs, 1)} lbs (≈{round(lbs/40, 1)} × 40-lb bags). Broadcast slowly, brush pool, verify with strip after 24h."}


# ─── Turnover ─────────────────────────────────────────────────────────
class TurnoverIn(BaseModel):
    pool_gallons: float
    pump_gpm: float
    pool_type: str = Field("residential", description="residential|commercial|spa")
    depth_ft: Optional[float] = None


@router.post("/turnover")
async def turnover_calc(body: TurnoverIn, user: dict = Depends(require_tech_or_above)):
    if body.pool_gallons <= 0 or body.pump_gpm <= 0:
        raise HTTPException(422, "pool_gallons and pump_gpm must be > 0")
    hours = body.pool_gallons / (body.pump_gpm * 60)
    ptype = (body.pool_type or "residential").lower()
    if ptype == "spa":
        code_max = 0.5
        code = "Spa (30-minute turnover max)"
    elif ptype == "commercial":
        if body.depth_ft is not None and body.depth_ft > 4:
            code_max = 6.0
            code = "Commercial deep pool (>4ft) — 6-hour max"
        else:
            code_max = 4.0
            code = "Commercial shallow pool (≤4ft) — 4-hour max"
    else:
        code_max = None
        code = "Residential (no code-mandated maximum — informational only)"
    compliant = None if code_max is None else hours <= code_max
    return {"turnover_hours": round(hours, 2),
            "code_standard": code,
            "code_max_hours": code_max,
            "compliant": compliant,
            "note": ("PASS — turnover meets code." if compliant
                     else "FAIL — turnover exceeds code max. Increase pump size or run time."
                     if compliant is False else
                     "Informational only — residential pools have no mandated turnover time.")}


# ─── Heater Size ──────────────────────────────────────────────────────
class HeaterIn(BaseModel):
    pool_gallons: float
    current_temp: float
    target_temp: float
    avg_ambient: float = Field(..., description="Average ambient temp °F")
    surface_area: float = Field(..., description="Pool surface area sq ft")
    heater_type: str = Field(..., description="gas|heat_pump|electric|solar")
    heat_up_hours: float = 24.0
    per_therm: float = 1.50
    per_kwh: float = 0.15
    days: int = 30


@router.post("/heater-size")
async def heater_calc(body: HeaterIn, user: dict = Depends(require_tech_or_above)):
    if body.pool_gallons <= 0 or body.surface_area <= 0:
        raise HTTPException(422, "pool_gallons and surface_area must be > 0")
    if body.target_temp <= body.current_temp:
        raise HTTPException(422, "target_temp must be greater than current_temp")
    delta_t = body.target_temp - body.current_temp
    btu_required = body.pool_gallons * 8.33 * delta_t / max(body.heat_up_hours, 1)
    # Ambient heat-loss BTU/day (rough coefficient 12).
    daily_loss_btu = body.surface_area * max(0, body.target_temp - body.avg_ambient) * 12

    htype = (body.heater_type or "").lower()
    notes = []
    monthly_cost = 0.0
    if htype == "gas":
        # 1 therm = 100,000 BTU. Assume 82% efficiency.
        therms_per_day = daily_loss_btu / (100_000 * 0.82)
        monthly_cost = therms_per_day * body.per_therm * body.days
        notes.append(f"Gas: ~{round(therms_per_day, 2)} therms/day at ${body.per_therm}/therm (82% eff).")
    elif htype == "heat_pump":
        # COP 5.0 typical for pool heat pumps in mild climate.
        kwh_per_day = daily_loss_btu / (3412 * 5.0)
        monthly_cost = kwh_per_day * body.per_kwh * body.days
        notes.append(f"Heat pump: ~{round(kwh_per_day, 2)} kWh/day at ${body.per_kwh}/kWh (COP 5.0). Requires ambient > 50°F.")
    elif htype == "electric":
        # COP 1.0 (resistance).
        kwh_per_day = daily_loss_btu / 3412
        monthly_cost = kwh_per_day * body.per_kwh * body.days
        notes.append(f"Electric resistance: ~{round(kwh_per_day, 2)} kWh/day at ${body.per_kwh}/kWh (COP 1.0). Expensive to operate.")
    elif htype == "solar":
        monthly_cost = 0.0
        notes.append("Solar: $0 operating cost. Install cost only. Sized for 60–80% of pool surface area typical.")
    else:
        raise HTTPException(422, "heater_type must be gas|heat_pump|electric|solar")

    notes.append("Actual sizing depends on wind exposure, insulation, cover use, and climate. Verify with a licensed installer for large systems.")

    return {
        "btu_required": round(btu_required),
        "daily_loss_btu": round(daily_loss_btu),
        "monthly_cost": round(monthly_cost, 2),
        "heater_type": htype,
        "delta_t": round(delta_t, 1),
        "notes": notes,
    }


# ══════════════════════════════════════════════════════════════════════
# Phase T3 — Business Pricing Tools (admin + super_admin only)
# ══════════════════════════════════════════════════════════════════════
from statistics import median
from config import db
from routers.tenants import get_current_tenant


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# Visit cadence → visits per month + per year. Includes quarterly for
# T3.2 aggregation completeness (billing_plans has quarterly rows).
_VISITS_PER_MONTH = {
    "weekly": 52 / 12,
    "bi-weekly": 26 / 12,
    "biweekly": 26 / 12,
    "monthly": 1.0,
    "quarterly": 1 / 3,
}
_VISITS_PER_YEAR = {"weekly": 52, "bi-weekly": 26, "biweekly": 26,
                    "monthly": 12, "quarterly": 4}


PRICING_DEFAULTS = {
    "tech_hourly_cost": 35.0,
    "overhead_multiplier": 1.25,
    "margin_target_pct": 40.0,
    "tech_time_minutes": 45,
    "base_weekly": 135.0,
    "base_bi_weekly": 95.0,
    "base_monthly": 80.0,
    "gallons_baseline": 15000,
    "gallons_step": 5000,
    "gallons_step_price": 5.0,
    "adder_saltwater": 15.0,
    "adder_heater": 10.0,
    "adder_spa": 25.0,
    "adder_automation": 15.0,
    "adder_chlorine_tabs": 5.0,
    "adder_liquid_chlorine": 20.0,
    "zone_default_multiplier": 1.0,
}


def _pricing_defaults(tenant: dict) -> dict:
    """Merge tenant.pricing_defaults over PRICING_DEFAULTS spec defaults."""
    override = ((tenant or {}).get("settings") or {}).get("pricing_defaults") or {}
    return {**PRICING_DEFAULTS, **override}


async def _chemical_cost_map(tenant_id: str) -> dict[str, dict]:
    """slug → {name, unit_kind, cost_per_unit_cents}."""
    out = {}
    async for row in db.chemical_costs.find(
        {"tenant_id": tenant_id}, {"_id": 0}
    ):
        out[row["chemical_slug"]] = row
    return out


# ─── T3.1 Service In-cost ────────────────────────────────────────────
class ChemUsage(BaseModel):
    chemical_slug: str
    quantity: float
    unit: Optional[str] = None


class ServiceInCostIn(BaseModel):
    pool_gallons: float
    visit_type: str = "weekly"
    chemicals_per_visit: list[ChemUsage] = Field(default_factory=list)
    tech_time_minutes: Optional[float] = None
    tech_hourly_cost: Optional[float] = None
    overhead_multiplier: Optional[float] = None
    margin_target_pct: Optional[float] = None


@router.post("/service-in-cost")
async def service_in_cost(
    body: ServiceInCostIn,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    d = _pricing_defaults(tenant)
    tech_minutes = body.tech_time_minutes or d["tech_time_minutes"]
    tech_hourly = body.tech_hourly_cost if body.tech_hourly_cost is not None \
        else d["tech_hourly_cost"]
    overhead_mult = body.overhead_multiplier if body.overhead_multiplier is not None \
        else d["overhead_multiplier"]
    margin_pct = body.margin_target_pct if body.margin_target_pct is not None \
        else d["margin_target_pct"]
    cost_map = await _chemical_cost_map(tenant["id"])

    chem_lines = []
    chemical_total = 0.0
    for c in body.chemicals_per_visit:
        row = cost_map.get(c.chemical_slug)
        unit_cost = (row or {}).get("cost_per_unit_cents", 0) / 100.0
        line_cost = round(unit_cost * c.quantity, 2)
        chem_lines.append({
            "chemical_slug": c.chemical_slug,
            "name": (row or {}).get("name", c.chemical_slug),
            "quantity": c.quantity,
            "unit": c.unit or (row or {}).get("unit_kind", ""),
            "unit_cost": unit_cost,
            "line_cost": line_cost,
        })
        chemical_total += line_cost

    labor_cost = round((tech_minutes / 60.0) * tech_hourly, 2)
    subtotal = chemical_total + labor_cost
    overhead_cost = round(subtotal * (overhead_mult - 1), 2)
    total_in_cost = round(subtotal + overhead_cost, 2)
    minimum_price_per_visit = round(total_in_cost * (1 + margin_pct / 100.0), 2)
    vpy = _VISITS_PER_YEAR.get(body.visit_type.lower(), 52)
    annualized_revenue = round(minimum_price_per_visit * vpy, 2)

    return {
        "visit_type": body.visit_type,
        "pool_gallons": body.pool_gallons,
        "chemical_lines": chem_lines,
        "chemical_cost_total": round(chemical_total, 2),
        "labor_cost": labor_cost,
        "labor_details": {"minutes": tech_minutes, "hourly": tech_hourly},
        "overhead_cost": overhead_cost,
        "overhead_multiplier": overhead_mult,
        "total_in_cost": total_in_cost,
        "margin_target_pct": margin_pct,
        "minimum_price_per_visit": minimum_price_per_visit,
        "visits_per_year": vpy,
        "annualized_revenue": annualized_revenue,
    }


# ─── T3.2 Cost per Pool (portfolio aggregation) ─────────────────────
@router.get("/cost-per-pool")
async def cost_per_pool(
    min_gallons: Optional[float] = None,
    max_gallons: Optional[float] = None,
    visit_type_filter: Optional[str] = None,
    only_active_customers: bool = True,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    d = _pricing_defaults(tenant)
    cost_map = await _chemical_cost_map(tenant["id"])

    # Standard per-visit chemical mix baseline for the estimator when a
    # customer has no per-customer override. Weekly service uses a bit
    # more than monthly. Values are per-visit tenants can tune later.
    standard_mix = [
        {"chemical_slug": "liquid_chlorine", "quantity": 1.0},
        {"chemical_slug": "muriatic_acid", "quantity": 0.25},
        {"chemical_slug": "chlorine_tabs", "quantity": 2},
    ]
    def chem_total_for_mix(mix):
        return sum(
            (cost_map.get(m["chemical_slug"], {}).get("cost_per_unit_cents", 0) / 100.0)
            * m["quantity"] for m in mix
        )
    baseline_chem_cost = chem_total_for_mix(standard_mix)

    # Query
    cust_q = {"tenant_id": tenant["id"]}
    if only_active_customers:
        cust_q["$or"] = [{"is_active": True}, {"is_active": {"$exists": False}}]
    if min_gallons is not None:
        cust_q["pool_gallons"] = {**cust_q.get("pool_gallons", {}), "$gte": min_gallons}
    if max_gallons is not None:
        cust_q["pool_gallons"] = {**cust_q.get("pool_gallons", {}), "$lte": max_gallons}

    rows = []
    async for cust in db.customers.find(cust_q, {"_id": 0}):
        plan = await db.billing_plans.find_one(
            {"tenant_id": tenant["id"], "customer_id": cust["id"], "active": True},
            {"_id": 0}, sort=[("created_at", -1)],
        )
        if not plan:
            continue
        vt = (plan.get("frequency") or "").lower()
        if visit_type_filter and vt != visit_type_filter.lower():
            continue
        vpm = _VISITS_PER_MONTH.get(vt, 0)
        if not vpm:
            continue
        labor_cost = (d["tech_time_minutes"] / 60.0) * d["tech_hourly_cost"]
        per_visit_in = (baseline_chem_cost + labor_cost) * d["overhead_multiplier"]
        monthly_in_cost = round(per_visit_in * vpm, 2)
        monthly_revenue = round(float(plan.get("amount") or 0) * vpm, 2) if vt in ("weekly","biweekly","bi-weekly") \
            else round(float(plan.get("amount") or 0), 2) if vt == "monthly" \
            else round(float(plan.get("amount") or 0) / 3.0, 2) if vt == "quarterly" \
            else 0
        margin_amount = round(monthly_revenue - monthly_in_cost, 2)
        margin_pct = round((margin_amount / monthly_revenue * 100), 1) if monthly_revenue else None
        # Outlier flags
        flags = []
        if margin_pct is not None:
            if margin_amount < 0:
                flags.append("negative_margin")
            elif margin_pct < 20:
                flags.append("low_margin")
            elif margin_pct > 60:
                flags.append("high_margin")
        rows.append({
            "customer_id": cust["id"],
            "customer_name": cust.get("name") or "",
            "pool_gallons": cust.get("pool_gallons") or 0,
            "visit_type": vt,
            "monthly_in_cost": monthly_in_cost,
            "monthly_revenue": monthly_revenue,
            "margin_amount": margin_amount,
            "margin_pct": margin_pct,
            "flags": flags,
        })
    # Sort by margin outliers first (negative/low), then high
    def sort_key(r):
        f = r.get("flags") or []
        if "negative_margin" in f: return (0, r.get("margin_pct") or 0)
        if "low_margin" in f: return (1, r.get("margin_pct") or 0)
        if "high_margin" in f: return (3, -(r.get("margin_pct") or 0))
        return (2, r.get("margin_pct") or 0)
    rows.sort(key=sort_key)
    margins = [r["margin_pct"] for r in rows if r["margin_pct"] is not None]
    return {
        "count": len(rows),
        "rows": rows,
        "summary": {
            "median_margin_pct": round(median(margins), 1) if margins else None,
            "low_margin_count": sum(1 for r in rows if "low_margin" in r["flags"]),
            "high_margin_count": sum(1 for r in rows if "high_margin" in r["flags"]),
            "negative_margin_count": sum(1 for r in rows if "negative_margin" in r["flags"]),
        },
        "baseline_chem_cost_per_visit": round(baseline_chem_cost, 2),
    }


# ─── T3.3 Service Price recommender ─────────────────────────────────
class ServicePriceIn(BaseModel):
    pool_gallons: float
    visit_type: str = "weekly"
    pool_features: list[str] = Field(default_factory=list)
    distance_zone: Optional[str] = None


@router.post("/service-price")
async def service_price(
    body: ServicePriceIn,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    d = _pricing_defaults(tenant)
    vt = body.visit_type.lower()
    if vt == "weekly":
        base = d["base_weekly"]
    elif vt in ("bi-weekly", "biweekly"):
        base = d["base_bi_weekly"]
    elif vt == "monthly":
        base = d["base_monthly"]
    else:
        raise HTTPException(422, "visit_type must be weekly|bi-weekly|monthly")

    adders = []
    feat_map = {
        "saltwater": d["adder_saltwater"],
        "heater": d["adder_heater"],
        "spa": d["adder_spa"],
        "automation": d["adder_automation"],
        "chlorine_tabs": d["adder_chlorine_tabs"],
        "liquid_chlorine": d["adder_liquid_chlorine"],
    }
    features_total = 0.0
    for f in body.pool_features or []:
        amt = feat_map.get(f)
        if amt is None:
            continue
        adders.append({"feature": f, "amount": amt})
        features_total += amt

    baseline = d["gallons_baseline"]
    step = d["gallons_step"]
    step_price = d["gallons_step_price"]
    over = max(0, body.pool_gallons - baseline)
    gallons_adder = round((over // step) * step_price, 2)

    zones = ((tenant or {}).get("settings") or {}).get("pricing_zones") or {}
    zone_mult = float(zones.get(body.distance_zone or "", d["zone_default_multiplier"])) \
        if body.distance_zone else d["zone_default_multiplier"]

    subtotal = base + features_total + gallons_adder
    recommended = round(subtotal * zone_mult, 2)

    # Median comparison — cheapest and roughest proxy: pull other
    # customers with the same visit_type and gallons within ±25%.
    lo = body.pool_gallons * 0.75
    hi = body.pool_gallons * 1.25
    peer_amounts: list[float] = []
    async for plan in db.billing_plans.find(
        {"tenant_id": tenant["id"], "active": True,
         "frequency": {"$in": ["weekly", "bi-weekly", "biweekly", "monthly"]}},
        {"_id": 0, "amount": 1, "frequency": 1, "customer_id": 1},
    ):
        pfreq = plan.get("frequency", "").lower()
        if pfreq != vt and not (pfreq in ("bi-weekly", "biweekly") and vt in ("bi-weekly", "biweekly")):
            continue
        cust = await db.customers.find_one(
            {"tenant_id": tenant["id"], "id": plan.get("customer_id")},
            {"_id": 0, "pool_gallons": 1},
        )
        if cust and cust.get("pool_gallons") and lo <= cust["pool_gallons"] <= hi:
            peer_amounts.append(float(plan.get("amount") or 0))
    peer_median = round(median(peer_amounts), 2) if peer_amounts else None

    return {
        "recommended_price": recommended,
        "breakdown": {
            "base": base,
            "features": adders,
            "features_total": round(features_total, 2),
            "gallons_adder": gallons_adder,
            "zone_multiplier": zone_mult,
            "subtotal_before_zone": round(subtotal, 2),
        },
        "visit_type": vt,
        "peer_median_price": peer_median,
        "peer_sample_size": len(peer_amounts),
    }



# ══════════════════════════════════════════════════════════════════════
# Phase T5 — Business Analysis Tools (admin + super_admin only)
# ══════════════════════════════════════════════════════════════════════

ROUTE_VALUATION_DEFAULTS = {
    "churn_rate_pct": 8.0,
    "tech_cost_percentage": 35.0,
    "chemical_cost_percentage": 15.0,
    "overhead_percentage": 12.0,
    "route_density": "medium",  # dense | medium | spread
    "contract_length_avg_months": 24,
    # Multiple bounds — routes trade in the industry between roughly
    # 4x monthly (spread + high churn + short contracts) and 8x monthly
    # (dense + low churn + long contracts). All three factors mix
    # linearly and are averaged.
    "multiple_min": 4.0,
    "multiple_max": 8.0,
    # Density factor bounds (fraction 0..1 of the min→max window).
    "density_weights": {"dense": 1.0, "medium": 0.55, "spread": 0.15},
    # Churn factor: >12% pins to 0; <4% pins to 1.
    "churn_low_pct": 4.0,
    "churn_high_pct": 12.0,
    # Contract length factor: >=36mo pins to 1; <=6mo pins to 0.
    "contract_short_months": 6,
    "contract_long_months": 36,
    "industry_per_customer_low": 1500,
    "industry_per_customer_high": 3500,
}


PAY_MODEL_DEFAULTS = {
    "hourly_rate": 22.0,
    "per_pool_rate": 18.0,
    "route_buy_pct": 65.0,   # tech keeps this fraction of route revenue
    # "Other costs" for company margin math when comparing pay models:
    # chemicals + overhead (labor is the variable being modeled).
    "chemical_cost_percentage": 15.0,
    "overhead_percentage": 12.0,
}


def _rv_defaults(tenant: dict) -> dict:
    override = ((tenant or {}).get("settings") or {}).get("route_valuation_defaults") or {}
    return {**ROUTE_VALUATION_DEFAULTS, **override}


def _pm_defaults(tenant: dict) -> dict:
    override = ((tenant or {}).get("settings") or {}).get("pay_model_defaults") or {}
    return {**PAY_MODEL_DEFAULTS, **override}


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


# ─── T5.1 Route Valuation ───────────────────────────────────────────
class RouteValuationIn(BaseModel):
    active_customers: Optional[float] = Field(None, description="null → auto pull tenant active count")
    avg_monthly_revenue_per_customer: Optional[float] = Field(None, description="null → auto median")
    total_monthly_revenue: Optional[float] = None
    churn_rate_pct: Optional[float] = None
    tech_cost_percentage: Optional[float] = None
    chemical_cost_percentage: Optional[float] = None
    overhead_percentage: Optional[float] = None
    route_density: Optional[str] = None
    contract_length_avg_months: Optional[float] = None


@router.post("/route-valuation")
async def route_valuation(
    body: RouteValuationIn,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    d = _rv_defaults(tenant)

    # Auto-pull active customer count if not provided.
    if body.active_customers is None:
        active_customers = float(await db.customers.count_documents({
            "tenant_id": tenant["id"],
            "$or": [{"is_active": True}, {"is_active": {"$exists": False}}],
        }))
    else:
        active_customers = float(body.active_customers or 0)

    # Auto-pull avg monthly revenue if not provided — median of the
    # active billing_plans expressed as a monthly figure.
    if body.avg_monthly_revenue_per_customer is None:
        monthly_amounts: list[float] = []
        async for plan in db.billing_plans.find(
            {"tenant_id": tenant["id"], "active": True}, {"_id": 0}
        ):
            amt = float(plan.get("amount") or 0)
            freq = (plan.get("frequency") or "").lower()
            vpm = _VISITS_PER_MONTH.get(freq)
            if not vpm or amt <= 0:
                continue
            monthly_amounts.append(amt * vpm if freq in ("weekly", "biweekly", "bi-weekly")
                                     else amt if freq == "monthly"
                                     else amt / 3.0)
        if monthly_amounts:
            avg_monthly = median(monthly_amounts)
        else:
            avg_monthly = 0.0
    else:
        avg_monthly = float(body.avg_monthly_revenue_per_customer or 0)

    total_monthly_revenue = body.total_monthly_revenue \
        if body.total_monthly_revenue is not None \
        else avg_monthly * active_customers
    annual_revenue = round(total_monthly_revenue * 12, 2)

    churn = body.churn_rate_pct if body.churn_rate_pct is not None else d["churn_rate_pct"]
    tech_pct = body.tech_cost_percentage if body.tech_cost_percentage is not None else d["tech_cost_percentage"]
    chem_pct = body.chemical_cost_percentage if body.chemical_cost_percentage is not None else d["chemical_cost_percentage"]
    oh_pct = body.overhead_percentage if body.overhead_percentage is not None else d["overhead_percentage"]
    density = (body.route_density or d["route_density"]).lower()
    contract_len = body.contract_length_avg_months if body.contract_length_avg_months is not None \
        else d["contract_length_avg_months"]

    annual_gross_profit = round(
        annual_revenue * (1 - (tech_pct + chem_pct + oh_pct) / 100.0), 2
    )

    # 3-factor mix, each on [0,1]. Average, then lerp between min/max multiple.
    density_factor = float(d["density_weights"].get(density, 0.55))
    churn_factor = 1 - (max(0, churn - d["churn_low_pct"])
                        / max(1e-6, (d["churn_high_pct"] - d["churn_low_pct"])))
    churn_factor = max(0.0, min(1.0, churn_factor))
    contract_factor = ((contract_len - d["contract_short_months"])
                        / max(1e-6, (d["contract_long_months"] - d["contract_short_months"])))
    contract_factor = max(0.0, min(1.0, contract_factor))
    combined_factor = (density_factor + churn_factor + contract_factor) / 3.0
    route_multiple = round(_lerp(d["multiple_min"], d["multiple_max"], combined_factor), 2)
    route_valuation_amt = round(total_monthly_revenue * route_multiple, 2)
    per_customer = round(route_valuation_amt / active_customers, 2) if active_customers else 0.0

    return {
        "active_customers": int(active_customers),
        "avg_monthly_revenue_per_customer": round(avg_monthly, 2),
        "total_monthly_revenue": round(total_monthly_revenue, 2),
        "annual_revenue": annual_revenue,
        "annual_gross_profit": annual_gross_profit,
        "route_multiple": route_multiple,
        "route_valuation": route_valuation_amt,
        "valuation_per_customer": per_customer,
        "breakdown": {
            "density": density,
            "density_factor": round(density_factor, 2),
            "churn_rate_pct": churn,
            "churn_factor": round(churn_factor, 2),
            "contract_length_avg_months": contract_len,
            "contract_factor": round(contract_factor, 2),
            "combined_factor": round(combined_factor, 2),
            "multiple_min": d["multiple_min"],
            "multiple_max": d["multiple_max"],
        },
        "benchmarks": {
            "industry_per_customer_low": d["industry_per_customer_low"],
            "industry_per_customer_high": d["industry_per_customer_high"],
            "position": ("below_industry" if per_customer < d["industry_per_customer_low"]
                          else "above_industry" if per_customer > d["industry_per_customer_high"]
                          else "in_industry_range"),
        },
    }


# ─── T5.2 Pay Model Comparator ──────────────────────────────────────
class PayModelIn(BaseModel):
    tech_route_customers: float
    avg_visit_time_minutes: float
    avg_revenue_per_customer_month: float
    visits_per_customer_per_month: float
    hourly_rate: Optional[float] = None
    per_pool_rate: Optional[float] = None
    route_buy_pct: Optional[float] = None


@router.post("/pay-model-compare")
async def pay_model_compare(
    body: PayModelIn,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    d = _pm_defaults(tenant)
    n = max(0.0, float(body.tech_route_customers or 0))
    vt = max(0.0, float(body.avg_visit_time_minutes or 0))
    rev_per_cust_mo = max(0.0, float(body.avg_revenue_per_customer_month or 0))
    vpcm = max(0.0, float(body.visits_per_customer_per_month or 0))

    hourly = body.hourly_rate if body.hourly_rate is not None else d["hourly_rate"]
    per_pool = body.per_pool_rate if body.per_pool_rate is not None else d["per_pool_rate"]
    route_pct = body.route_buy_pct if body.route_buy_pct is not None else d["route_buy_pct"]
    chem_pct = d["chemical_cost_percentage"]
    oh_pct = d["overhead_percentage"]

    monthly_visits = n * vpcm
    monthly_hours = (monthly_visits * vt) / 60.0
    weekly_hours = monthly_hours / 4.33 if monthly_hours else 0
    monthly_revenue = n * rev_per_cust_mo
    other_costs = monthly_revenue * (chem_pct + oh_pct) / 100.0

    def build(name: str, tech_pay: float) -> dict:
        remaining = monthly_revenue - tech_pay - other_costs
        margin_pct = round((remaining / monthly_revenue * 100), 1) if monthly_revenue else 0.0
        return {
            "model": name,
            "monthly_tech_pay": round(tech_pay, 2),
            "weekly_tech_pay": round(tech_pay / 4.33, 2) if tech_pay else 0.0,
            "annualized_tech_pay": round(tech_pay * 12, 2),
            "company_gross_margin_pct": margin_pct,
            "company_monthly_profit": round(remaining, 2),
        }

    hourly_pay = weekly_hours * hourly * 4.33
    per_pool_pay = monthly_visits * per_pool
    route_buy_pay = monthly_revenue * (route_pct / 100.0)

    models = {
        "hourly": build("hourly", hourly_pay),
        "per_pool": build("per_pool", per_pool_pay),
        "route_buy": build("route_buy", route_buy_pay),
    }
    for m in models.values():
        m["hourly_rate"] = hourly if m["model"] == "hourly" else None
        m["per_pool_rate"] = per_pool if m["model"] == "per_pool" else None
        m["route_buy_pct"] = route_pct if m["model"] == "route_buy" else None

    # Winner determination.
    best_margin = max(models.values(), key=lambda x: x["company_gross_margin_pct"])
    best_tech_pay = max(models.values(), key=lambda x: x["monthly_tech_pay"])

    # Break-even: at how many customers does route_buy > hourly for the tech?
    # Solve: n*rev/cust*route_pct = n*vpcm*vt/60 * hourly
    #   → rev/cust * route_pct/100 = vpcm * vt/60 * hourly
    # Note: n cancels. Result: not customer-count-dependent given the inputs.
    # So instead sweep visits_per_customer to find the break: keep n fixed.
    breakeven_hint: Optional[str] = None
    if rev_per_cust_mo * (route_pct / 100.0) > vpcm * (vt / 60.0) * hourly:
        breakeven_hint = "route_buy pays the tech more than hourly at any route size for these inputs."
    elif rev_per_cust_mo * (route_pct / 100.0) < vpcm * (vt / 60.0) * hourly:
        breakeven_hint = "hourly pays the tech more than route_buy at any route size for these inputs."
    else:
        breakeven_hint = "hourly and route_buy pay the same for these inputs."

    recommendation = (
        f"Highest company margin: {best_margin['model']} at "
        f"{best_margin['company_gross_margin_pct']}%. "
        f"Highest tech pay: {best_tech_pay['model']} at "
        f"${best_tech_pay['monthly_tech_pay']}/mo."
    )

    return {
        "inputs_echo": {
            "tech_route_customers": n,
            "avg_visit_time_minutes": vt,
            "avg_revenue_per_customer_month": rev_per_cust_mo,
            "visits_per_customer_per_month": vpcm,
            "monthly_hours": round(monthly_hours, 2),
            "weekly_hours": round(weekly_hours, 2),
            "monthly_revenue": round(monthly_revenue, 2),
            "other_costs_pct": chem_pct + oh_pct,
        },
        "models": models,
        "recommendation": recommendation,
        "best_company_margin": best_margin["model"],
        "best_tech_pay": best_tech_pay["model"],
        "breakeven_hint": breakeven_hint,
    }

