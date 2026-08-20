// Feb-2026 · Web mirror of backend `services/chemistry_bands.py`.
// Kept in exact lockstep so the portal service-report page and the
// door-hanger email classify readings identically.
//
// Boundary rule: LOWER inclusive, UPPER exclusive.

import { DISPLAY_LABELS } from "@/utils/chemistryGate";

export const BAND_BELOW = "Below Average";
export const BAND_AVERAGE = "Average";
export const BAND_ABOVE = "Above Average";
export const BAND_ELEVATED = "Elevated";

export const CANONICAL_BAND_THRESHOLDS = {
  free_chlorine:  { average_min: 1,   average_max: 5,   above_avg_max: 10 },
  total_chlorine: { average_min: 1,   average_max: 5,   above_avg_max: 10 },
  ph:             { average_min: 7.2, average_max: 7.6, above_avg_max: 8.2 },
  alkalinity:     { average_min: 80,  average_max: 120, above_avg_max: 140 },
  cyanuric_acid:  { average_min: 30,  average_max: 80,  above_avg_max: 150 },
};

function coerceFloat(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === "boolean") return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string") {
    const s = v.trim();
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * Return one of the four band labels, or `null` when the key is not
 * banded (water_temp, calcium_hardness) or the value is unparseable.
 * Boundary rule matches the backend: lower inclusive, upper exclusive.
 */
export function bandForReading(key, value) {
  const t = CANONICAL_BAND_THRESHOLDS[key];
  if (!t) return null;
  const v = coerceFloat(value);
  if (v === null) return null;
  if (v < t.average_min) return BAND_BELOW;
  if (v < t.average_max) return BAND_AVERAGE;
  if (v < t.above_avg_max) return BAND_ABOVE;
  return BAND_ELEVATED;
}

export { DISPLAY_LABELS };
