"""Phase 34e — Pool chemistry dosing engine (deterministic).

All formulas are per **10,000 US gallons** and are scaled linearly with
`pool_gallons`. Ranges follow standard APSP / Taylor guidance.

Chemistry decisions live here — the LLM is only allowed to re-phrase
the `reason` string, never touch the quantity. That prevents the
"chatty over-dose" failure mode.
"""
from __future__ import annotations

from typing import Optional

# Target ranges: (min, max, ideal).
_TARGETS = {
    "ph":                 (7.2,   7.6,   7.4),
    "free_chlorine":      (1.0,   3.0,   2.0),
    "total_alkalinity":   (80,    120,   100),
    "calcium_hardness":   (200,   400,   250),
    "cyanuric_acid":      (30,    50,    40),
    "salt":               (2700,  3400,  3200),
}

# Handy reading aliases the mobile/web templates may send.
_ALIASES = {
    "ph": "ph",
    "free_chlorine": "free_chlorine",
    "fc": "free_chlorine",
    "chlorine": "free_chlorine",
    "total_alkalinity": "total_alkalinity",
    "ta": "total_alkalinity",
    "alkalinity": "total_alkalinity",
    "calcium_hardness": "calcium_hardness",
    "ch": "calcium_hardness",
    "hardness": "calcium_hardness",
    "cyanuric_acid": "cyanuric_acid",
    "cya": "cyanuric_acid",
    "stabilizer": "cyanuric_acid",
    "salt": "salt",
}


def _normalize(readings: dict) -> dict:
    """Lowercase, alias-map, coerce numerics, drop blanks."""
    out: dict[str, float] = {}
    for k, v in (readings or {}).items():
        if v is None or v == "":
            continue
        key = _ALIASES.get(str(k).strip().lower().replace(" ", "_"))
        if not key:
            continue
        try:
            out[key] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _rec(chemical: str, qty: float, unit: str, reason: str,
         urgency: str, key: str, current: float,
         target: tuple[float, float, float]) -> dict:
    return {
        "chemical": chemical,
        "quantity": round(qty, 2),
        "unit": unit,
        "reason": reason,
        "urgency": urgency,
        "reading_key": key,
        "current_value": current,
        "target_range": [target[0], target[1]],
        "target_value": target[2],
    }


def compute(readings: dict, pool_gallons: Optional[int]) -> list[dict]:
    """Return an ordered list of chemical dose recommendations.

    Ordering priority (urgency, then health impact):
      1. Free Chlorine (sanitiser — health)
      2. pH (bather comfort + sanitiser efficacy)
      3. Total Alkalinity (pH buffer)
      4. Cyanuric Acid (chlorine stabiliser)
      5. Calcium Hardness (equipment protection)
      6. Salt (only when salt reading is present)
    Capped at 6 items.
    """
    if not pool_gallons or pool_gallons <= 0:
        return []
    scale = pool_gallons / 10_000.0
    r = _normalize(readings)
    out: list[dict] = []

    # 1. Free chlorine — sanitiser
    if "free_chlorine" in r:
        fc = r["free_chlorine"]
        lo, hi, tgt = _TARGETS["free_chlorine"]
        if fc < lo:
            # Liquid chlorine 12.5% — 10 oz per 10k gal ≈ +2 ppm.
            delta = tgt - fc
            oz = round(10.0 * (delta / 2.0) * scale, 1)
            out.append(_rec(
                "Liquid chlorine (12.5%)", oz, "oz",
                f"Free chlorine is {fc} ppm — below the {lo}–{hi} sanitising range.",
                "immediate", "free_chlorine", fc, _TARGETS["free_chlorine"],
            ))
        elif fc > hi:
            # Overshoot — recommend letting it drift down. No chemical add.
            out.append(_rec(
                "Wait — do not add chlorine", 0, "",
                f"Free chlorine is {fc} ppm — above {hi} ppm. Let it drift down before adding more.",
                "routine", "free_chlorine", fc, _TARGETS["free_chlorine"],
            ))

    # 2. pH
    if "ph" in r:
        ph = r["ph"]
        lo, hi, tgt = _TARGETS["ph"]
        if ph < lo:
            # Soda ash: 6 oz per 10k gal ≈ +0.2 pH.
            delta = tgt - ph
            oz = round(6.0 * (delta / 0.2) * scale, 1)
            out.append(_rec(
                "Soda ash (sodium carbonate)", oz, "oz",
                f"pH is {ph} — below {lo}. Raises pH gently without bumping alkalinity much.",
                "routine", "ph", ph, _TARGETS["ph"],
            ))
        elif ph > hi:
            # Muriatic acid: 8 oz per 10k gal ≈ -0.2 pH.
            delta = ph - tgt
            oz = round(8.0 * (delta / 0.2) * scale, 1)
            out.append(_rec(
                "Muriatic acid", oz, "oz",
                f"pH is {ph} — above {hi}. Also nudges total alkalinity down.",
                "routine", "ph", ph, _TARGETS["ph"],
            ))

    # 3. Total Alkalinity
    if "total_alkalinity" in r:
        ta = r["total_alkalinity"]
        lo, hi, tgt = _TARGETS["total_alkalinity"]
        if ta < lo:
            # Sodium bicarbonate: 21 oz (~1.5 lb) per 10k gal ≈ +10 ppm.
            delta = tgt - ta
            oz = round(21.0 * (delta / 10.0) * scale, 1)
            out.append(_rec(
                "Sodium bicarbonate (baking soda)", oz, "oz",
                f"Total alkalinity is {ta} ppm — below {lo}. Buffers pH swings.",
                "routine", "total_alkalinity", ta, _TARGETS["total_alkalinity"],
            ))
        elif ta > hi and r.get("ph", 7.4) > _TARGETS["ph"][1]:
            # Only recommend acid when BOTH TA and pH are high (per brief).
            delta = ta - tgt
            oz = round(25.0 * (delta / 10.0) * scale, 1)
            out.append(_rec(
                "Muriatic acid (to lower TA)", oz, "oz",
                f"Total alkalinity is {ta} ppm AND pH is high — acid lowers both.",
                "routine", "total_alkalinity", ta, _TARGETS["total_alkalinity"],
            ))

    # 4. Cyanuric Acid (stabiliser)
    if "cyanuric_acid" in r:
        cya = r["cyanuric_acid"]
        lo, hi, tgt = _TARGETS["cyanuric_acid"]
        if cya < lo:
            delta = tgt - cya
            oz = round(13.0 * (delta / 10.0) * scale, 1)
            out.append(_rec(
                "Stabiliser (cyanuric acid granular)", oz, "oz",
                f"Cyanuric acid is {cya} ppm — below {lo}. Protects chlorine from UV burn-off.",
                "routine", "cyanuric_acid", cya, _TARGETS["cyanuric_acid"],
            ))
        elif cya > hi:
            out.append(_rec(
                "Partial drain + refill", 0, "",
                f"Cyanuric acid is {cya} ppm — above {hi}. Only fix is to drain some water.",
                "routine", "cyanuric_acid", cya, _TARGETS["cyanuric_acid"],
            ))

    # 5. Calcium Hardness
    if "calcium_hardness" in r:
        ch = r["calcium_hardness"]
        lo, hi, tgt = _TARGETS["calcium_hardness"]
        if ch < lo:
            delta = tgt - ch
            oz = round(10.0 * (delta / 10.0) * scale, 1)
            out.append(_rec(
                "Calcium chloride", oz, "oz",
                f"Calcium hardness is {ch} ppm — below {lo}. Prevents plaster etching.",
                "routine", "calcium_hardness", ch, _TARGETS["calcium_hardness"],
            ))
        elif ch > hi:
            out.append(_rec(
                "Partial drain + refill", 0, "",
                f"Calcium hardness is {ch} ppm — above {hi}. Only fix is to drain some water.",
                "routine", "calcium_hardness", ch, _TARGETS["calcium_hardness"],
            ))

    # 6. Salt (only recommended when a salt reading is actually present).
    if "salt" in r:
        s = r["salt"]
        lo, hi, tgt = _TARGETS["salt"]
        if s < lo:
            delta = tgt - s
            # 25 lb per 10k gal ≈ +300 ppm.
            lb = round(25.0 * (delta / 300.0) * scale, 1)
            out.append(_rec(
                "Pool salt (NaCl)", lb, "lbs",
                f"Salt is {s} ppm — below {lo}. Required for the chlorine generator to run.",
                "routine", "salt", s, _TARGETS["salt"],
            ))

    # Priority ordering: immediate items first, then keep original order.
    out.sort(key=lambda x: 0 if x["urgency"] == "immediate" else 1)
    return out[:6]
