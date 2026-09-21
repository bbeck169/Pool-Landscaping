// Feb-2026 · Web mirror of backend `services/chemistry_gate.py`.
// Keep the missing-detection rules in exact lockstep with the backend
// helper so an admin's UI-gated Complete Job button never lets a
// submit through that the API then 422s.
//
//   * `null` / `undefined` / `""` / whitespace-only → MISSING
//   * literal `"null"` / `"None"` (case-insensitive) → MISSING
//   * `0` is MISSING for ph / alkalinity / cyanuric_acid (P17
//     zero-carve-out); `0` remains VALID for free_chlorine
//     (fully-consumed pools can legitimately read 0 ppm).
//   * Negative floats + numeric strings that parse → VALID
//   * Unparseable strings → MISSING
//
// Phase P17 · Feb-2026 · P0 HOTFIX — Chemistry Gate Key Unification
// -----------------------------------------------------------------
// Single ALIAS_MAP source of truth (mirror of backend).  Incoming
// keys are normalised with `key.trim().toLowerCase().replace(/ /g,
// "_").replace(/-/g, "_")` before lookup so "pH", "Total Alkalinity",
// "Cyanuric Acid", "CYA" all resolve.  Two-pass dedupe:
//   1. bucket every input candidate under its canonical key
//   2. pick winner: real beats empty → canonical spelling → alphabetically
//      first alias.
//
// Keep in sync with:
//   * backend/services/chemistry_gate.py  :: ALIAS_MAP
//   * mobile/utils/chemistryGate.ts       :: ALIAS_MAP

export const CORE_KEYS = [
  "free_chlorine",
  "alkalinity",
  "ph",
  "cyanuric_acid",
];

const LABEL = {
  free_chlorine: "Free Cl",
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
  alkalinity: "alkalinity",
  ph: "ph",
  cyanuric_acid: "cya",
};

// Phase P17 · Feb-2026 — single source of truth for alias resolution.
// Every canonical key is an identity entry; every legacy / short /
// human spelling folds onto its canonical.
export const ALIAS_MAP = {
  // ── ph ────────────────────────────────────────────────────
  ph: "ph",
  p_h: "ph",
  ph_balance: "ph",              // legacy — preserved
  // ── free_chlorine ─────────────────────────────────────────
  free_chlorine: "free_chlorine",
  chlorine: "free_chlorine",
  free_cl: "free_chlorine",
  freecl: "free_chlorine",
  fc: "free_chlorine",
  // ── alkalinity ────────────────────────────────────────────
  alkalinity: "alkalinity",
  total_alkalinity: "alkalinity",
  ta: "alkalinity",
  alk: "alkalinity",              // legacy — preserved
  // ── cyanuric_acid ─────────────────────────────────────────
  cyanuric_acid: "cyanuric_acid",
  cyanuric: "cyanuric_acid",
  cya: "cyanuric_acid",
};

const ZERO_IS_EMPTY_KEYS = new Set(["ph", "alkalinity", "cyanuric_acid"]);

function normKey(k) {
  if (typeof k !== "string") return "";
  return k.trim().toLowerCase().replace(/ /g, "_").replace(/-/g, "_");
}

function canonicalKey(k) {
  const norm = normKey(k);
  if (!norm) return null;
  return ALIAS_MAP[norm] || null;
}

function numericValue(v) {
  if (v === null || v === undefined || typeof v === "boolean") return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string") {
    const s = v.trim();
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function isEffectivelyEmpty(ck, v) {
  if (v === null || v === undefined) return true;
  if (typeof v === "boolean") return true;
  if (typeof v === "string") {
    const s = v.trim();
    if (!s) return true;
    const low = s.toLowerCase();
    if (low === "null" || low === "none") return true;
  }
  if (ZERO_IS_EMPTY_KEYS.has(ck)) {
    const num = numericValue(v);
    if (num !== null && num === 0) return true;
  }
  return false;
}

function isValidReading(v) {
  if (v === null || v === undefined) return false;
  if (typeof v === "boolean") return false;
  if (typeof v === "number") return Number.isFinite(v);
  if (typeof v === "string") {
    const s = v.trim();
    if (!s) return false;
    if (s.toLowerCase() === "null" || s.toLowerCase() === "none") return false;
    const n = Number(s);
    return Number.isFinite(n);
  }
  return false;
}

function isGateValid(ck, v) {
  if (isEffectivelyEmpty(ck, v)) return false;
  return isValidReading(v);
}

/** Accepts either the service_report list-of-dicts shape
 *  ([{key, value, ...}]) or a flat dict ({free_chlorine: 2.5, ...}).
 *
 *  Phase P17 · Feb-2026 — two-pass dedupe.  Pass 1 buckets every
 *  (rawKey, value) tuple under the resolved canonical key.  Pass 2
 *  picks the winner: non-empty beats empty; canonical spelling wins
 *  when multiple non-empty values collide; else alphabetically-first
 *  alias by normalised key.
 */
export function normalizeReadings(source) {
  const buckets = new Map();
  if (!source) return {};

  const items = [];
  if (Array.isArray(source)) {
    for (const row of source) {
      if (!row || typeof row !== "object") continue;
      items.push([row.key || row.name, row.value]);
    }
  } else if (typeof source === "object") {
    for (const [k, v] of Object.entries(source)) items.push([k, v]);
  } else {
    return {};
  }

  for (const [rawKey, val] of items) {
    const ck = canonicalKey(rawKey);
    if (!ck) continue;
    if (!buckets.has(ck)) buckets.set(ck, []);
    buckets.get(ck).push([rawKey, val]);
  }

  const out = {};
  for (const [ck, candidates] of buckets.entries()) {
    const nonEmpty = candidates.filter(
      ([, v]) => !isEffectivelyEmpty(ck, v),
    );
    if (nonEmpty.length === 0) {
      out[ck] = candidates[0][1];
      continue;
    }
    if (nonEmpty.length === 1) {
      out[ck] = nonEmpty[0][1];
      continue;
    }
    const canonicalHits = nonEmpty.filter(
      ([rk]) => normKey(rk) === ck,
    );
    let winnerRaw, winnerVal;
    if (canonicalHits.length > 0) {
      [winnerRaw, winnerVal] = canonicalHits[0];
    } else {
      const sorted = [...nonEmpty].sort(
        (a, b) => normKey(a[0]).localeCompare(normKey(b[0])),
      );
      [winnerRaw, winnerVal] = sorted[0];
    }
    const dropped = nonEmpty
      .filter(([rk]) => rk !== winnerRaw)
      .map(([rk]) => rk);
    // eslint-disable-next-line no-console
    console.warn(
      "[chem-normalize] " + ck + " alias collision — keeping "
      + String(winnerRaw) + ", dropped " + JSON.stringify(dropped),
    );
    out[ck] = winnerVal;
  }
  return out;
}

/** Returns the UI-friendly label list of MISSING core readings. */
export function missingCoreReadings(source) {
  const norm = normalizeReadings(source);
  return CORE_KEYS.filter((k) => !isGateValid(k, norm[k])).map(
    (k) => LABEL[k],
  );
}

/** Convenience — the gate passes if this returns true. */
export function isChemistryGateSatisfied(source) {
  return missingCoreReadings(source).length === 0;
}
