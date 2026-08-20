// Feb-2026 · Mobile mirror of backend `services/chemistry_gate.py`.
// Kept in exact lockstep with the web mirror
// (`frontend/src/utils/chemistryGate.js`) so all three surfaces
// (backend, web, mobile) enforce the same "5 core readings" contract.
//
//   * `null` / `undefined` / `""` / whitespace-only → MISSING
//   * `0` and negative floats → VALID (real chemistry readings)
//   * Numeric strings must parse; unparseable → MISSING

export const CORE_KEYS = [
  "free_chlorine",
  "total_chlorine",
  "alkalinity",
  "ph",
  "cyanuric_acid",
] as const;

const LABEL: Record<string, string> = {
  free_chlorine: "Free Cl",
  total_chlorine: "Total Cl",
  alkalinity: "Alkalinity",
  ph: "pH",
  cyanuric_acid: "CYA",
};

// Product-approved DISPLAY labels — mirror of backend
// ``services/chemistry_gate.py :: DISPLAY_LABELS``.
export const DISPLAY_LABELS = LABEL;

const ALIASES: Record<string, string> = {
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

function canonicalKey(k: any): string | null {
  if (typeof k !== "string") return null;
  const norm = k.trim().toLowerCase().replace(/-/g, "_");
  if ((CORE_KEYS as readonly string[]).includes(norm)) return norm;
  return ALIASES[norm] || ALIASES[norm.replace(/_/g, " ")] || null;
}

function isValidReading(v: any): boolean {
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

export function normalizeReadings(source: any): Record<string, any> {
  const out: Record<string, any> = {};
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

export function missingCoreReadings(source: any): string[] {
  const norm = normalizeReadings(source);
  return CORE_KEYS
    .filter((k) => !isValidReading(norm[k]))
    .map((k) => LABEL[k]);
}

export function isChemistryGateSatisfied(source: any): boolean {
  return missingCoreReadings(source).length === 0;
}
