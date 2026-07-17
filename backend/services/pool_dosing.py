"""Phase 34e / 56.5 — Pool chemistry dosing engine (deterministic).

All formulas are per **10,000 US gallons** and are scaled linearly with
`pool_gallons`. Ranges follow standard APSP / Taylor guidance.

Chemistry decisions live here — the LLM is only allowed to re-phrase
the `reason` string, never touch the quantity. That prevents the
"chatty over-dose" failure mode.

Phase 56.5 additions:
  • Seasonal free-chlorine target (5.0 ppm high season / 1–3 ppm low).
  • Chlorine Tabs preferred over Liquid Chlorine unless a rapid-boost
    condition trips, the customer opted out of tabs, or tabs were used
    in the last 3 visits.
  • Muriatic Acid and Liquid Chlorine now expressed in gallons (2dp).
  • Every recommendation carries `target_ppm`, `season`, `preferred_form`,
    `preferred_form_reason` for the AI CFO / report renderer.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from config_chlorine_targets import (
    CHLORINE_HIGH_SEASON_MONTHS,
    CHLORINE_HIGH_SEASON_TARGET_PPM,
    CHLORINE_LOW_SEASON_TARGET_MIN_PPM,
    CHLORINE_LOW_SEASON_TARGET_MAX_PPM,
    CHLORINE_TAB_GALLONS_PER_TAB_PER_WEEK,
    CHLORINE_RAPID_BOOST_GAP_PPM,
    CHLORINE_TAB_ROTATION_LOOKBACK_VISITS,
    CAL_HYPO_AVAILABLE_CHLORINE_PCT,
    ALGAE_LIGHT_SHOCK_PPM,
    ALGAE_HEAVY_SHOCK_PPM,
    POLYQUAT_OZ_PER_10K_GAL,
    ALGAE_HIGH_PH_THRESHOLD,
)

# Target ranges: (min, max, ideal). Free chlorine is resolved per-season.
_TARGETS = {
    "ph":                 (7.2,   7.6,   7.4),
    "free_chlorine":      (1.0,   3.0,   2.0),   # low-season fallback
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

# fluid-ounces → US gallons.
_OZ_PER_GAL = 128.0


def _normalize(readings: dict) -> dict:
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


def _coerce_service_date(service_date) -> date:
    if service_date is None:
        return date.today()
    if isinstance(service_date, date) and not isinstance(service_date, datetime):
        return service_date
    if isinstance(service_date, datetime):
        return service_date.date()
    try:
        return datetime.fromisoformat(str(service_date)[:10]).date()
    except Exception:
        return date.today()


def resolve_chlorine_target(service_date=None) -> tuple[float, tuple[float, float, float], str]:
    """Return `(target_ppm, (min, max, ideal), season)` for the given date.

    High season (Mar–Sep) targets a single 5.0 ppm bull's-eye; low season
    (Oct–Feb) targets the 1–3 ppm range with 2.0 as the mid-point ideal.
    """
    d = _coerce_service_date(service_date)
    if d.month in CHLORINE_HIGH_SEASON_MONTHS:
        tgt = CHLORINE_HIGH_SEASON_TARGET_PPM
        # High-season "range" is tighter — use a symmetric ±0.5 band around
        # the bull's-eye so out-of-range detection still works.
        return tgt, (tgt - 0.5, tgt + 0.5, tgt), "high"
    lo, hi = CHLORINE_LOW_SEASON_TARGET_MIN_PPM, CHLORINE_LOW_SEASON_TARGET_MAX_PPM
    ideal = round((lo + hi) / 2.0, 2)
    return ideal, (lo, hi, ideal), "low"


def _decide_chlorine_form(
    fc: float,
    target_ppm: float,
    season: str,
    customer: Optional[dict],
    recent_service_reports: Optional[list],
) -> tuple[str, str]:
    """Return `(preferred_form, reason)` for a chlorine add.

    **Phase 56.9 update — Chlorine Tabs are the ALWAYS-default form.**

    Liquid is only recommended when the customer / operator explicitly
    signals one of these overrides:
      • Customer opted out of tabs (`chemical_preferences.no_tabs: True`).
      • Customer / operator explicitly requested liquid this visit
        (`chemical_preferences.prefer_liquid_chlorine: True`).
    Otherwise → tabs.  Ops instructions for "shock now" or "algae bloom"
    are handled by the Phase 56.10 algae-remediation module (in flight)
    — that path emits a distinct calcium-hypochlorite entry alongside
    the routine tabs recommendation, never by demoting the default.
    """
    prefs = ((customer or {}).get("chemical_preferences") or {})
    if prefs.get("no_tabs") is True:
        return "liquid", "Customer opted out of chlorine tabs."
    if prefs.get("prefer_liquid_chlorine") is True:
        return "liquid", "Operator override on this customer profile — liquid chlorine selected."
    # Tabs are the default. Reason string retained here matches the copy
    # the frontend surfaces as a tooltip next to the recommended dose.
    return "tabs", (
        "Tabs recommended for steady residual — override to liquid if shocking "
        "or during algae bloom."
    )


def _rec(chemical: str, qty: float, unit: str, reason: str,
         urgency: str, key: str, current: float,
         target: tuple[float, float, float],
         *, target_ppm: Optional[float] = None,
         season: Optional[str] = None,
         preferred_form: Optional[str] = None,
         preferred_form_reason: Optional[str] = None) -> dict:
    rec: dict = {
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
    if target_ppm is not None:
        rec["target_ppm"] = target_ppm
    if season is not None:
        rec["season"] = season
    if preferred_form is not None:
        rec["preferred_form"] = preferred_form
    if preferred_form_reason is not None:
        rec["preferred_form_reason"] = preferred_form_reason
    return rec


def compute(
    readings: dict,
    pool_gallons: Optional[int],
    *,
    customer: Optional[dict] = None,
    service_date=None,
    recent_service_reports: Optional[list] = None,
    visible_algae: str = "none",
) -> list[dict]:
    """Return an ordered list of chemical dose recommendations.

    Ordering priority (urgency, then health impact):
      1. Free Chlorine (sanitiser — health)
      2. pH (bather comfort + sanitiser efficacy)
      3. Total Alkalinity (pH buffer)
      4. Cyanuric Acid (chlorine stabiliser)
      5. Calcium Hardness (equipment protection)
      6. Salt (only when salt reading is present)
    Capped at 6 items.

    Phase 56.10 — algae remediation:
      * When `visible_algae` is "light" or "heavy", additional entries
        with `category="algae_remediation"` are appended AFTER the
        routine dose list. Heavy adds a Polyquat 60 algaecide entry
        alongside a triple-strength cal-hypo shock.
      * When pH exceeds `ALGAE_HIGH_PH_THRESHOLD`, an ordering-guidance
        entry with `category="ordering_note"` is PREPENDED so the tech
        lowers pH before shocking. Algae entries themselves are NOT
        subject to the 6-item cap.
    """
    if not pool_gallons or pool_gallons <= 0:
        return []
    scale = pool_gallons / 10_000.0
    r = _normalize(readings)
    out: list[dict] = []

    # Season-aware chlorine target (Phase 56.5).
    fc_target_ppm, fc_target_tuple, season = resolve_chlorine_target(service_date)
    fc_lo, fc_hi, _ = fc_target_tuple

    # 1. Free chlorine — sanitiser.
    if "free_chlorine" in r:
        fc = r["free_chlorine"]
        if fc < fc_lo:
            preferred_form, form_reason = _decide_chlorine_form(
                fc, fc_target_ppm, season, customer, recent_service_reports,
            )
            delta = fc_target_ppm - fc
            if preferred_form == "tabs":
                # Weekly tab count scales with gallons per manufacturer rating.
                # Higher gap ⇒ +1 tab bump (max 2 extra) so we don't overshoot.
                base_tabs = pool_gallons / float(CHLORINE_TAB_GALLONS_PER_TAB_PER_WEEK)
                bump = 1 if delta > 1.0 else 0
                bump += 1 if delta > 2.0 else 0
                qty = max(1, round(base_tabs) + bump)
                unit = "tabs"
                chemical = "Chlorine tabs (3\" trichlor)"
                reason = (
                    f"Free chlorine is {fc:.1f} ppm — below the seasonal "
                    f"target of {fc_target_ppm:.1f} ppm ({season} season). "
                    f"Load {qty} tab(s) in the feeder / floater."
                )
            else:
                # Liquid chlorine 12.5% — 10 fl-oz per 10k gal ≈ +2 ppm.
                # Phase 56.5 unit tweak — surface as gallons (2dp).
                oz = 10.0 * (delta / 2.0) * scale
                qty = round(oz / _OZ_PER_GAL, 2)
                unit = "gal"
                chemical = "Liquid chlorine (12.5%)"
                reason = (
                    f"Free chlorine is {fc:.1f} ppm — below the seasonal "
                    f"target of {fc_target_ppm:.1f} ppm ({season} season). "
                    f"{form_reason}"
                )
            out.append(_rec(
                chemical, qty, unit, reason, "immediate",
                "free_chlorine", fc, (fc_lo, fc_hi, fc_target_ppm),
                target_ppm=fc_target_ppm, season=season,
                preferred_form=preferred_form,
                preferred_form_reason=form_reason,
            ))
        elif fc > fc_hi:
            out.append(_rec(
                "Wait — do not add chlorine", 0, "",
                f"Free chlorine is {fc:.1f} ppm — above the seasonal "
                f"ceiling ({fc_hi:.1f} ppm). Let it drift down.",
                "routine", "free_chlorine", fc,
                (fc_lo, fc_hi, fc_target_ppm),
                target_ppm=fc_target_ppm, season=season,
            ))

    # 2. pH.
    if "ph" in r:
        ph = r["ph"]
        lo, hi, tgt = _TARGETS["ph"]
        if ph < lo:
            # Soda ash (Phase 56.5b unit fix) — 6 oz per 10k gal ≈ +0.2 pH.
            # Displayed as lbs (1 lb = 16 oz) to match how techs stock and
            # scoop the product. Underlying chemistry unchanged.
            delta = tgt - ph
            oz = 6.0 * (delta / 0.2) * scale
            lbs = round(oz / 16.0, 1)
            out.append(_rec(
                "Soda ash (sodium carbonate)", lbs, "lbs",
                f"pH is {ph} — below {lo}. {lbs} lbs raises pH gently without bumping alkalinity much.",
                "routine", "ph", ph, _TARGETS["ph"],
            ))
        elif ph > hi:
            # Muriatic acid — express in gallons per Phase 56.5 unit fix.
            delta = ph - tgt
            oz = 8.0 * (delta / 0.2) * scale
            gal = round(oz / _OZ_PER_GAL, 2)
            out.append(_rec(
                "Muriatic acid", gal, "gal",
                f"pH is {ph} — above {hi}. Also nudges total alkalinity down.",
                "routine", "ph", ph, _TARGETS["ph"],
            ))

    # 3. Total Alkalinity.
    if "total_alkalinity" in r:
        ta = r["total_alkalinity"]
        lo, hi, tgt = _TARGETS["total_alkalinity"]
        if ta < lo:
            # Sodium bicarbonate (Phase 56.5b unit fix) — 21 oz per 10k gal
            # ≈ +10 ppm. Displayed as lbs to match tech stocking.
            delta = tgt - ta
            oz = 21.0 * (delta / 10.0) * scale
            lbs = round(oz / 16.0, 1)
            out.append(_rec(
                "Sodium bicarbonate (baking soda)", lbs, "lbs",
                f"Total alkalinity is {ta} ppm — below {lo}. {lbs} lbs buffers pH swings.",
                "routine", "total_alkalinity", ta, _TARGETS["total_alkalinity"],
            ))
        elif ta > hi and r.get("ph", 7.4) > _TARGETS["ph"][1]:
            delta = ta - tgt
            oz = 25.0 * (delta / 10.0) * scale
            gal = round(oz / _OZ_PER_GAL, 2)
            out.append(_rec(
                "Muriatic acid (to lower TA)", gal, "gal",
                f"Total alkalinity is {ta} ppm AND pH is high — acid lowers both.",
                "routine", "total_alkalinity", ta, _TARGETS["total_alkalinity"],
            ))

    # 4. Cyanuric Acid (stabiliser).
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

    # 5. Calcium Hardness.
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

    # 6. Salt.
    if "salt" in r:
        s = r["salt"]
        lo, hi, tgt = _TARGETS["salt"]
        if s < lo:
            delta = tgt - s
            lb = round(25.0 * (delta / 300.0) * scale, 1)
            out.append(_rec(
                "Pool salt (NaCl)", lb, "lbs",
                f"Salt is {s} ppm — below {lo}. Required for the chlorine generator to run.",
                "routine", "salt", s, _TARGETS["salt"],
            ))

    out.sort(key=lambda x: 0 if x["urgency"] == "immediate" else 1)
    routine = out[:6]

    # Phase 56.10 — algae remediation is appended AFTER the routine cap so
    # a "shock the pool" recommendation never gets bumped by a low-priority
    # calcium entry. Ordering-note (high-pH guard) is prepended.
    algae_state = (visible_algae or "none").strip().lower()
    if algae_state in ("light", "heavy"):
        algae_entries = _algae_remediation_entries(algae_state, pool_gallons, r)
        return algae_entries + routine
    return routine


# ─── Phase 56.10 — visible algae remediation ───────────────────────────────
def _cal_hypo_lbs(pool_gallons: int, ppm_boost: float) -> float:
    """User spec formula:
        lbs = pool_gallons × ppm / 120000 × (73 / available_chlorine_%)
    A cal-hypo product tagged at the configured trade strength (73 %) is
    the reference. When `CAL_HYPO_AVAILABLE_CHLORINE_PCT` is bumped for a
    higher-strength product, the dose drops linearly."""
    ratio = 73.0 / float(CAL_HYPO_AVAILABLE_CHLORINE_PCT)
    return pool_gallons * ppm_boost / 120_000.0 * ratio


def _algae_remediation_entries(state: str, pool_gallons: int, readings: dict) -> list[dict]:
    """Assemble the 1–2 algae dose entries plus optional high-pH guard.

    Every entry carries `category="algae_remediation"` (or `ordering_note`
    for the high-pH guard) so the wizard step-2 UI can render them in a
    distinct sub-section with a warning icon."""
    ordering: list[dict] = []
    ph = readings.get("ph")
    if ph is not None and ph > ALGAE_HIGH_PH_THRESHOLD:
        ordering.append({
            "chemical": "Ordering guidance",
            "quantity": 0,
            "unit": "",
            "reason": (
                "Lower pH to 7.2 with muriatic acid FIRST, then shock. "
                "Shocking at high pH reduces effectiveness."
            ),
            "urgency": "immediate",
            "reading_key": "ph",
            "current_value": ph,
            "target_range": [7.2, 7.6],
            "target_value": 7.4,
            "category": "ordering_note",
        })

    entries: list[dict] = []
    if state == "light":
        ppm = ALGAE_LIGHT_SHOCK_PPM
        lbs = round(_cal_hypo_lbs(pool_gallons, ppm), 2)
        entries.append({
            "chemical": "Calcium hypochlorite shock (73%)",
            "quantity": lbs,
            "unit": "lbs",
            "reason": (
                f"Light algae observed. Cal-hypo shock at ~{ppm} ppm FC boost "
                f"({lbs} lbs) knocks down surface algae fast."
            ),
            "urgency": "immediate",
            "reading_key": "visible_algae",
            "current_value": 1,     # 1 = light, 2 = heavy (numeric for reports)
            "target_range": [0, 0],
            "target_value": 0,
            "category": "algae_remediation",
            "preferred_form": "cal_hypo",
            "preferred_form_reason": (
                "Rapid FC boost required for algae remediation. Cal-hypo "
                f"delivers ~{CAL_HYPO_AVAILABLE_CHLORINE_PCT}% available "
                "chlorine per lb."
            ),
            "guidance_note": "Brush walls thoroughly and run filter 24h continuous.",
            "severity": "light",
        })

    elif state == "heavy":
        ppm = ALGAE_HEAVY_SHOCK_PPM
        lbs = round(_cal_hypo_lbs(pool_gallons, ppm), 2)
        entries.append({
            "chemical": "Calcium hypochlorite triple shock (73%)",
            "quantity": lbs,
            "unit": "lbs",
            "reason": (
                f"Heavy algae observed. Triple-shock cal-hypo at ~{ppm} ppm "
                f"FC boost ({lbs} lbs) required to reach breakpoint over the bloom."
            ),
            "urgency": "immediate",
            "reading_key": "visible_algae",
            "current_value": 2,
            "target_range": [0, 0],
            "target_value": 0,
            "category": "algae_remediation",
            "preferred_form": "cal_hypo",
            "preferred_form_reason": (
                "Rapid FC boost required for algae remediation. Cal-hypo "
                f"delivers ~{CAL_HYPO_AVAILABLE_CHLORINE_PCT}% available "
                "chlorine per lb."
            ),
            "guidance_note": (
                "Brush walls thoroughly. Run filter 24h continuous. "
                "Backwash / clean filter after 24h. Recheck FC before "
                "allowing swimmers."
            ),
            "severity": "heavy",
        })
        polyquat_oz = round(POLYQUAT_OZ_PER_10K_GAL * (pool_gallons / 10_000.0), 1)
        entries.append({
            "chemical": "Polyquat 60 algaecide",
            "quantity": polyquat_oz,
            "unit": "oz",
            "reason": (
                f"Heavy algae bloom — add {polyquat_oz} oz Polyquat 60 "
                "alongside the shock for a redundant kill vector."
            ),
            "urgency": "immediate",
            "reading_key": "visible_algae",
            "current_value": 2,
            "target_range": [0, 0],
            "target_value": 0,
            "category": "algae_remediation",
            "preferred_form": "polyquat_60",
            "preferred_form_reason": (
                "Non-metallic algaecide safe for salt cells and vinyl "
                "liners. Chlorine alone is insufficient for heavy algae blooms."
            ),
            "guidance_note": (
                "Add slowly around the perimeter with the pump running. "
                "Do not mix with concentrated chlorine in the same bucket."
            ),
            "severity": "heavy",
        })

    return ordering + entries
