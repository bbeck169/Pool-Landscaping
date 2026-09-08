/**
 * Phase v · Multi-body service reports (mobile).
 *
 * Client-side mirror of the backend allow-lists from
 * `backend/services/water_bodies.py`. Same sync-rules as
 * `frontend/src/lib/waterBodies.js` — when the backend changes,
 * this file must change in lockstep.
 */

export type BodyType = "pool" | "spa" | "water_feature" | "fountain" | "other";

export type WaterBody = {
  id: string;
  type: BodyType;
  label: string;
  sequence: number;
  readings: { key: string; name?: string; value: number | string | null; unit?: string }[];
  chemicals_used: { product_slug: string; amount: number | string; unit: string; product_name?: string }[];
  media: any[];
  notes: string;
};

/* ── Fixed picker items ─────────────────────────────────────────────── */

export const WATER_BODY_TYPES: { value: BodyType; label: string }[] = [
  { value: "pool",          label: "Pool" },
  { value: "spa",           label: "Spa" },
  { value: "water_feature", label: "Water Feature" },
  { value: "fountain",      label: "Fountain" },
  { value: "other",         label: "Other" },
];

export const BODY_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  WATER_BODY_TYPES.map((b) => [b.value, b.label]),
);

/* ── Tint palette per body type ─────────────────────────────────────── */

export const BODY_TYPE_TINTS: Record<string, { bg: string; fg: string; border: string }> = {
  pool:          { bg: "#E0F2FE", fg: "#0369A1", border: "#7DD3FC" },
  spa:           { bg: "#F3E8FF", fg: "#7E22CE", border: "#D8B4FE" },
  water_feature: { bg: "#F1F5F9", fg: "#334155", border: "#CBD5E1" },
  fountain:      { bg: "#F1F5F9", fg: "#334155", border: "#CBD5E1" },
  other:         { bg: "#F5F5F4", fg: "#44403C", border: "#E7E5E4" },
};

/* ── Reading allow-list per body type ───────────────────────────────── */

export const READING_ALLOWLIST: Record<string, string[]> = {
  pool: ["free_chlorine", "total_chlorine", "combined_chlorine", "ph", "alkalinity", "cyanuric_acid", "calcium_hardness", "salt", "tds", "phosphates", "water_temp"],
  spa: ["free_chlorine", "ph", "alkalinity", "calcium_hardness", "water_temp"],
  water_feature: ["free_chlorine", "ph", "water_temp"],
  fountain: ["free_chlorine", "ph", "water_temp"],
  other: ["free_chlorine", "total_chlorine", "combined_chlorine", "ph", "alkalinity", "cyanuric_acid", "calcium_hardness", "salt", "tds", "phosphates", "water_temp"],
};

/* ── Required readings (only pool blocks submit) ───────────────────── */

export const READING_REQUIRED: Record<string, string[]> = {
  pool: ["free_chlorine", "total_chlorine", "ph", "alkalinity", "cyanuric_acid"],
  spa: [],
  water_feature: [],
  fountain: [],
  other: [],
};

/* ── Chemical allow-list per body type ──────────────────────────────── */

export const CHEMICAL_ALLOWLIST: Record<string, string[]> = {
  pool: ["chlorine_tabs", "liquid_chlorine", "muriatic_acid", "soda_ash", "shock", "clarifier", "phosphate_remover", "salt", "enzymes"],
  spa: ["chlorine_tabs", "liquid_chlorine", "muriatic_acid", "soda_ash", "shock", "clarifier", "enzymes"],
  water_feature: ["liquid_chlorine", "muriatic_acid", "clarifier", "enzymes", "phosphate_remover"],
  fountain: ["liquid_chlorine", "muriatic_acid", "clarifier", "enzymes", "phosphate_remover"],
  other: ["chlorine_tabs", "liquid_chlorine", "muriatic_acid", "soda_ash", "shock", "clarifier", "phosphate_remover", "salt", "enzymes"],
};

/* ── Display metadata ───────────────────────────────────────────────── */

export const READING_LABELS: Record<string, { name: string; unit: string; short: string }> = {
  free_chlorine:      { name: "Free Chlorine",      unit: "ppm", short: "FC" },
  total_chlorine:     { name: "Total Chlorine",      unit: "ppm", short: "TC" },
  combined_chlorine:  { name: "Combined Chlorine",   unit: "ppm", short: "CC" },
  ph:                 { name: "pH",                  unit: "",    short: "pH" },
  alkalinity:         { name: "Total Alkalinity",    unit: "ppm", short: "TA" },
  cyanuric_acid:      { name: "Cyanuric Acid",       unit: "ppm", short: "CYA" },
  calcium_hardness:   { name: "Calcium Hardness",    unit: "ppm", short: "CH" },
  salt:               { name: "Salt",                unit: "ppm", short: "Salt" },
  tds:                { name: "TDS",                 unit: "ppm", short: "TDS" },
  phosphates:         { name: "Phosphates",          unit: "ppb", short: "PO4" },
  water_temp:         { name: "Water Temp",          unit: "°F",  short: "Temp" },
};

export const CHEMICAL_LABELS: Record<string, { name: string; unit: string }> = {
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

export const MAX_BODIES = 6;

/* ── Validators ─────────────────────────────────────────────────────── */

export function missingRequiredReadings(body: WaterBody): string[] {
  if (!body) return [];
  const required = READING_REQUIRED[body.type] || [];
  if (required.length === 0) return [];
  const byKey = new Map<string, any>();
  for (const r of body.readings || []) {
    if (r?.key) byKey.set(String(r.key).toLowerCase(), r);
  }
  return required.filter((k) => {
    const r = byKey.get(k);
    if (!r) return true;
    const v = r.value;
    if (v === null || v === undefined || v === "") return true;
    return !Number.isFinite(Number(v));
  });
}

export function validateBodies(bodies: WaterBody[]): { valid: boolean; errors: any[] } {
  if (!Array.isArray(bodies) || bodies.length === 0) {
    return { valid: false, errors: [{ message: "at_least_one_body_required" }] };
  }
  const errors: any[] = [];
  for (let i = 0; i < bodies.length; i++) {
    const b = bodies[i] || {} as WaterBody;
    const type = b.type || "pool";
    const allowed = new Set(READING_ALLOWLIST[type] || []);
    for (const r of b.readings || []) {
      const k = String(r?.key || "").toLowerCase();
      if (!k || type === "other") continue;
      if (!allowed.has(k)) {
        errors.push({ bodyIndex: i, key: k, type, message: "reading_not_allowed_for_body_type" });
      }
    }
  }
  return { valid: errors.length === 0, errors };
}

/* ── Factory helpers ────────────────────────────────────────────────── */

export function newBodyId(): string {
  return `wb-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function makeEmptyBody(type: BodyType = "pool", sequence = 0): WaterBody {
  const t = READING_ALLOWLIST[type] ? type : "pool";
  return {
    id: newBodyId(),
    type: t as BodyType,
    label: BODY_TYPE_LABELS[t] || "Pool",
    sequence,
    readings: [],
    chemicals_used: [],
    media: [],
    notes: "",
  };
}
