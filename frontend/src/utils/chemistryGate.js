// Feb-2026 · Web mirror of backend `services/chemistry_gate.py`.
// Keep the missing-detection rules in exact lockstep with the backend
// helper so an admin's UI-gated Complete Job button never lets a
// submit through that the API then 422s.
//
//   * `null` / `undefined` / `""` / whitespace-only → MISSING
//   * `0` and negative floats → VALID (real chemistry readings)
//   * Numeric strings must parse; unparseable → MISSING
//
// Canonical keys mirror the backend so mock service-report docs can
// be dropped in either shape (list-of-dicts or flat dict).

export const CORE_KEYS = [
  "free_chlorine",
  "total_chlorine",
  "alkalinity",
  "ph",
  "cyanuric_acid",
];

const LABEL = {
  free_chlorine: "Free Cl",
  total_chlorine: "Total Cl",
  alkalinity: "Alkalinity",
  ph: "pH",
  cyanuric_acid: "CYA",
};

// Product-approved DISPLAY labels used by the button tooltip and the
// inline warning banner.  Kept in exact lockstep with
// ``backend/services/chemistry_gate.py :: DISPLAY_LABELS``.
export const DISPLAY_LABELS = LABEL;

// Legacy machine-friendly labels (kebab-y snake case) — matches the
// 422 payload's ``missing_fields`` array.  Exposed so callers that
// prefer to key on those (e.g. analytics) don't have to re-derive.
export const CANONICAL_SHORT_LABELS = {
  free_chlorine: "free_cl",
  total_chlorine: "total_cl",
  alkalinity: "alkalinity",
  ph: "ph",
  cyanuric_acid: "cya",
};

const ALIASES = {
  free_cl: "free_chlorine",
  freecl: "free_chlorine",
  "free chlorine": "free_chlorine",
  total_cl: "total_chlorine",
  totalcl: "total_chlorine",
  "total chlorine": "total_chlorine",
  cya: "cyanuric_acid",
  cyanuric: "cyanuric_acid",
  "cyanuric acid": "cyanuric_acid",
  ph_balance: "ph",
  "ph balance": "ph",
  alk: "alkalinity",
  total_alkalinity: "alkalinity",
};

function canonicalKey(k) {
  if (typeof k !== "string") return null;
  const norm = k.trim().toLowerCase().replace(/-/g, "_");
  if (CORE_KEYS.includes(norm)) return norm;
  return ALIASES[norm] || ALIASES[norm.replace(/_/g, " ")] || null;
}

function isValidReading(v) {
  if (v === null || v === undefined) return false;
  if (typeof v === "boolean") return false;
  if (typeof v === "number") return Number.isFinite(v);
  if (typeof v === "string") {
    const s = v.trim();
    if (!s) return false;
    const n = Number(s);
    return Number.isFinite(n);
  }
  return false;
}

/** Accepts either the service_report list-of-dicts shape
 *  ([{key, value, ...}]) or a flat dict ({free_chlorine: 2.5, ...}). */
export function normalizeReadings(source) {
  const out = {};
  if (!source) return out;
  if (Array.isArray(source)) {
    for (const row of source) {
      if (!row || typeof row !== "object") continue;
      const ck = canonicalKey(row.key || row.name);
      if (!ck || out[ck] !== undefined) continue;
      out[ck] = row.value;
    }
    return out;
  }
  if (typeof source === "object") {
    for (const [k, v] of Object.entries(source)) {
      const ck = canonicalKey(k);
      if (ck && out[ck] === undefined) out[ck] = v;
    }
  }
  return out;
}

/** Returns the UI-friendly label list of MISSING core readings. */
export function missingCoreReadings(source) {
  const norm = normalizeReadings(source);
  return CORE_KEYS.filter((k) => !isValidReading(norm[k])).map(
    (k) => LABEL[k],
  );
}

/** Convenience — the gate passes if this returns true. */
export function isChemistryGateSatisfied(source) {
  return missingCoreReadings(source).length === 0;
}
