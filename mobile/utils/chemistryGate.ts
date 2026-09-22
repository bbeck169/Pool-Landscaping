// Feb-2026 · Mobile mirror of backend `services/chemistry_gate.py`.
// Kept in exact lockstep with the web mirror
// (`frontend/src/utils/chemistryGate.js`) so all three surfaces
// (backend, web, mobile) enforce the same "Required Four core
// readings" contract.
//
//   * `null` / `undefined` / `""` / whitespace-only → MISSING
//   * literal `"null"` / `"None"` (case-insensitive) → MISSING
//   * `0` is MISSING for ph / alkalinity / cyanuric_acid (P17
//     zero-carve-out); `0` remains VALID for chlorine
//     (fully-consumed pools can legitimately read 0 ppm).
//   * Negative floats + numeric strings that parse → VALID
//   * Unparseable strings → MISSING
//
// Phase P17 · Feb-2026 · P0 HOTFIX — Chemistry Gate Key Unification.
// Phase P17.1 · Feb-2026 — canonical rename: `free_chlorine` →
// `chlorine`. Legacy spellings (`free_chlorine`, `free_cl`,
// `freecl`, `fc`) remain as SOURCE aliases so any stored doc /
// legacy client write still resolves to the new canonical.
//
// Keep in sync with:
//   * backend/services/chemistry_gate.py  :: ALIAS_MAP
//   * frontend/src/utils/chemistryGate.js :: ALIAS_MAP

export type CanonicalKey =
  | "ph"
  | "chlorine"
  | "alkalinity"
  | "cyanuric_acid";

export const CORE_KEYS: readonly CanonicalKey[] = [
  "chlorine",
  "alkalinity",
  "ph",
  "cyanuric_acid",
] as const;

const LABEL: Record<CanonicalKey, string> = {
  chlorine: "Chlorine",
  alkalinity: "Alkalinity",
  ph: "pH",
  cyanuric_acid: "CYA",
};

// Product-approved DISPLAY labels — mirror of backend
// ``services/chemistry_gate.py :: DISPLAY_LABELS``.
export const DISPLAY_LABELS = LABEL;

// Phase P17 · Feb-2026 — single source of truth for alias resolution.
export const ALIAS_MAP: Record<string, CanonicalKey> = {
  // ── ph ────────────────────────────────────────────────────
  ph: "ph",
  p_h: "ph",
  ph_balance: "ph",              // legacy — preserved
  // ── chlorine (Phase P17.1 · Feb-2026 canonical rename;
  // legacy spellings preserved as source aliases) ────────────
  chlorine: "chlorine",
  free_chlorine: "chlorine",
  free_cl: "chlorine",
  freecl: "chlorine",
  fc: "chlorine",
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

const ZERO_IS_EMPTY_KEYS: ReadonlySet<CanonicalKey> = new Set([
  "ph",
  "alkalinity",
  "cyanuric_acid",
]);

function normKey(k: unknown): string {
  if (typeof k !== "string") return "";
  return k.trim().toLowerCase().replace(/ /g, "_").replace(/-/g, "_");
}

function canonicalKey(k: unknown): CanonicalKey | null {
  const norm = normKey(k);
  if (!norm) return null;
  return ALIAS_MAP[norm] ?? null;
}

function numericValue(v: unknown): number | null {
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

function isEffectivelyEmpty(ck: CanonicalKey | null, v: unknown): boolean {
  if (v === null || v === undefined) return true;
  if (typeof v === "boolean") return true;
  if (typeof v === "string") {
    const s = v.trim();
    if (!s) return true;
    const low = s.toLowerCase();
    if (low === "null" || low === "none") return true;
  }
  if (ck && ZERO_IS_EMPTY_KEYS.has(ck)) {
    const num = numericValue(v);
    if (num !== null && num === 0) return true;
  }
  return false;
}

function isValidReading(v: unknown): boolean {
  if (v === null || v === undefined) return false;
  if (typeof v === "boolean") return false;
  if (typeof v === "number") return Number.isFinite(v);
  if (typeof v === "string") {
    const s = v.trim();
    if (!s) return false;
    const low = s.toLowerCase();
    if (low === "null" || low === "none") return false;
    const n = Number(s);
    return Number.isFinite(n);
  }
  return false;
}

function isGateValid(ck: CanonicalKey, v: unknown): boolean {
  if (isEffectivelyEmpty(ck, v)) return false;
  return isValidReading(v);
}

/** Accepts either the service_report list-of-dicts shape or a flat
 *  dict.  Phase P17 two-pass dedupe — see backend/JS mirrors.
 */
export function normalizeReadings(
  source: unknown,
): Partial<Record<CanonicalKey, unknown>> {
  const buckets = new Map<CanonicalKey, Array<[unknown, unknown]>>();
  if (!source) return {};

  const items: Array<[unknown, unknown]> = [];
  if (Array.isArray(source)) {
    for (const row of source as any[]) {
      if (!row || typeof row !== "object") continue;
      items.push([row.key ?? row.name, row.value]);
    }
  } else if (typeof source === "object") {
    for (const [k, v] of Object.entries(source as Record<string, unknown>)) {
      items.push([k, v]);
    }
  } else {
    return {};
  }

  for (const [rawKey, val] of items) {
    const ck = canonicalKey(rawKey);
    if (!ck) continue;
    if (!buckets.has(ck)) buckets.set(ck, []);
    buckets.get(ck)!.push([rawKey, val]);
  }

  const out: Partial<Record<CanonicalKey, unknown>> = {};
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
    let winnerRaw: unknown;
    let winnerVal: unknown;
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

export function missingCoreReadings(source: unknown): string[] {
  const norm = normalizeReadings(source);
  return CORE_KEYS.filter((k) => !isGateValid(k, norm[k])).map(
    (k) => LABEL[k],
  );
}

export function isChemistryGateSatisfied(source: unknown): boolean {
  return missingCoreReadings(source).length === 0;
}
