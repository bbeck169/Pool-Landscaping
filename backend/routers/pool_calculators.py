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
