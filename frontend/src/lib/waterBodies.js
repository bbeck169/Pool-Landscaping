/**
 * Feb-2026 · Multi-body service reports (Phase 2 · web).
 *
 * Client-side mirror of the backend allow-lists that live in
 * `backend/services/water_bodies.py`. Duplication is intentional —
 * the FE renders only allowed reading rows / chemical rows for a
 * body type, and does client-side validation before the PATCH.
 * The server remains the source of truth (422 on breach); this
 * module is purely a UX layer so techs don't waste taps entering
 * data that would be rejected.
 *
 * SYNC RULES: whenever `services/water_bodies.py` allow-lists change,
 * this file MUST change in lockstep. The Phase 1 pytest suite covers
 * the backend side; the Phase 2 Vitest suite covers this mirror.
 */

export const WATER_BODY_TYPES = [
  { value: "pool",          label: "Pool" },
  { value: "spa",           label: "Spa" },
  { value: "water_feature", label: "Water Feature" },
  { value: "fountain",      label: "Fountain" },
  { value: "other",         label: "Other" },
];

export const BODY_TYPE_LABELS = Object.fromEntries(
  WATER_BODY_TYPES.map((b) => [b.value, b.label]),
);

// Body-type UI tint helpers — reuse existing service-line palette where
// possible. Pool = cyan, everything else = neutral so we don't invent
// a new palette (per Phase 2 design constraint).
export const BODY_TYPE_TINTS = {
  pool:          { bg: "#E0F2FE", fg: "#0369A1", border: "#7DD3FC" },
  spa:           { bg: "#F3E8FF", fg: "#7E22CE", border: "#D8B4FE" },
  water_feature: { bg: "#F1F5F9", fg: "#334155", border: "#CBD5E1" },
  fountain:      { bg: "#F1F5F9", fg: "#334155", border: "#CBD5E1" },
  other:         { bg: "#F5F5F4", fg: "#44403C", border: "#E7E5E4" },
};


// Reading allow-lists per body type — mirrors
// `services.water_bodies.READING_ALLOWLIST`.
//
// Phase CHEM1 · Feb-2026 — ``total_chlorine`` removed. The Required
// set for pool bodies is now the "Required Four" (free_chlorine, ph,
// alkalinity, cyanuric_acid).
export const READING_ALLOWLIST = {
  pool: [
    "free_chlorine", "ph", "alkalinity",
    "cyanuric_acid", "calcium_hardness", "salt", "tds", "phosphates",
  ],
  spa: ["free_chlorine", "ph", "alkalinity", "calcium_hardness"],
  water_feature: ["free_chlorine", "ph"],
  fountain: ["free_chlorine", "ph"],
  other: [
    "free_chlorine", "ph", "alkalinity",
    "cyanuric_acid", "calcium_hardness", "salt", "tds", "phosphates",
  ],
};


// Required-reading list per body type — matches
// `services.water_bodies.READING_REQUIRED`. Only ``pool`` blocks submit.
// Phase CHEM1 · Feb-2026 — the Required Four (per body) gate pool close.
export const READING_REQUIRED = {
  pool: ["free_chlorine", "ph", "alkalinity", "cyanuric_acid"],
  spa: [],
  water_feature: [],
  fountain: [],
  other: [],
};


// Chemical allow-lists — mirrors
// `services.water_bodies.CHEMICAL_ALLOWLIST`.
export const CHEMICAL_ALLOWLIST = {
  pool: [
    "chlorine_tabs", "liquid_chlorine", "muriatic_acid", "soda_ash",
    "shock", "clarifier", "phosphate_remover", "salt", "enzymes",
  ],
  spa: [
    "chlorine_tabs", "liquid_chlorine", "muriatic_acid", "soda_ash",
    "shock", "clarifier", "enzymes",
  ],
  water_feature: [
    "liquid_chlorine", "muriatic_acid", "clarifier", "enzymes",
    "phosphate_remover",
  ],
  fountain: [
    "liquid_chlorine", "muriatic_acid", "clarifier", "enzymes",
    "phosphate_remover",
  ],
  other: [
    "chlorine_tabs", "liquid_chlorine", "muriatic_acid", "soda_ash",
    "shock", "clarifier", "phosphate_remover", "salt", "enzymes",
  ],
};


// Display metadata for the compact reading rows on Panel bodies.
export const READING_LABELS = {
  free_chlorine:    { name: "Free Chlorine",   unit: "ppm", short: "Free Cl" },
  ph:               { name: "pH",              unit: "",    short: "pH" },
  alkalinity:       { name: "Total Alkalinity", unit: "ppm", short: "TA" },
  cyanuric_acid:    { name: "Cyanuric Acid",   unit: "ppm", short: "CYA" },
  calcium_hardness: { name: "Calcium Hardness", unit: "ppm", short: "Calcium" },
  salt:             { name: "Salt",            unit: "ppm", short: "Salt" },
  tds:              { name: "TDS",             unit: "ppm", short: "TDS" },
  phosphates:       { name: "Phosphates",      unit: "ppb", short: "PO4" },
};


// Display metadata for chemicals — matches ``chemicalTypes.js`` slugs
// with the backend catalog's ``chemical_slug`` conventions.
export const CHEMICAL_LABELS = {
  chlorine_tabs:      { name: "Chlorine Tabs",     unit: "tabs" },
  liquid_chlorine:    { name: "Liquid Chlorine",   unit: "gal" },
  muriatic_acid:      { name: "Muriatic Acid",     unit: "gal" },
  soda_ash:           { name: "Soda Ash",          unit: "lbs" },
  shock:              { name: "Shock",             unit: "lbs" },
  clarifier:          { name: "Clarifier",         unit: "oz" },
  phosphate_remover:  { name: "Phosphate Remover", unit: "oz" },
  salt:               { name: "Salt",              unit: "40lb bag" },
  enzymes:            { name: "Enzymes",           unit: "oz" },
};


// Maximum bodies per report — soft cap so techs can't accidentally
// build a 30-body report on a single visit. Backend has no hard cap;
// this is a UX guardrail only.
export const MAX_BODIES = 6;


// Client-side validator — checks a bodies[] payload against the same
// rules the backend enforces. Returns `{ valid: bool, errors: [] }`.
// Errors have `{ bodyIndex, key?, slug?, message }` shape so the
// caller can highlight the offending body/field.
export function validateBodies(bodies) {
  if (!Array.isArray(bodies) || bodies.length === 0) {
    return { valid: false, errors: [{ message: "at_least_one_body_required" }] };
  }
  const errors = [];
  for (let i = 0; i < bodies.length; i++) {
    const b = bodies[i] || {};
    const type = (b.type || "pool");
    const allowedReadings = new Set(READING_ALLOWLIST[type] || []);
    const allowedChems = new Set(CHEMICAL_ALLOWLIST[type] || []);
    for (const r of (b.readings || [])) {
      const k = String(r?.key || "").toLowerCase();
      if (!k) continue;
      // ``other`` accepts anything; skip the allow-list check.
      if (type === "other") continue;
      if (!allowedReadings.has(k)) {
        errors.push({ bodyIndex: i, key: k, type,
                       message: "reading_not_allowed_for_body_type" });
      }
    }
    for (const c of (b.chemicals_used || b.chemicals_added || [])) {
      const slug = String(c?.product_slug || c?.slug || "").toLowerCase();
      if (!slug || type === "other") continue;
      if (!allowedChems.has(slug)) {
        errors.push({ bodyIndex: i, slug, type,
                       message: "chemical_not_allowed_for_body_type" });
      }
    }
  }
  return { valid: errors.length === 0, errors };
}


// Return the list of missing REQUIRED reading keys for a body. Empty
// list = passes the required-readings gate. Used on the pool body to
// mirror the backend chemistry gate.
export function missingRequiredReadings(body) {
  if (!body) return [];
  const type = body.type || "pool";
  const required = READING_REQUIRED[type] || [];
  if (required.length === 0) return [];
  const byKey = new Map();
  for (const r of (body.readings || [])) {
    if (r && r.key) byKey.set(String(r.key).toLowerCase(), r);
  }
  return required.filter((k) => {
    const r = byKey.get(k);
    if (!r) return true;
    const v = r.value;
    if (v === null || v === undefined || v === "") return true;
    const n = Number(v);
    return !Number.isFinite(n);
  });
}


// Generate a stable client-side id for a new body. Server will
// preserve or regenerate as needed — no cryptographic guarantees.
export function newBodyId() {
  return `wb-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}


// Empty-body template for the "Add body of water" flow.
export function makeEmptyBody(type = "pool", sequence = 0) {
  const t = READING_ALLOWLIST[type] ? type : "pool";
  return {
    id: newBodyId(),
    type: t,
    label: BODY_TYPE_LABELS[t],
    sequence,
    readings: [],
    chemicals_used: [],
    media: [],
    notes: "",
  };
}
