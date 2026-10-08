/**
 * Templates Library — Phase 3 (Mobile) · pure field helpers.
 * Kept framework-free so they're trivially unit-testable.
 */

/**
 * Keep partial decimals ("1.", "-", "0.0") as strings while typing so the
 * user can actually enter a decimal; commit a real number once parseable.
 */
export function parseNumberInput(text: string): number | string {
  const t = (text || "").replace(",", ".").replace(/[^0-9.\-]/g, "");
  if (t === "") return "";
  if (t === "-" || t.endsWith(".") || /\.\d*0$/.test(t)) return t;
  const n = Number(t);
  return Number.isFinite(n) ? n : t;
}

/** Inline min/max validation message for `number` fields (null = OK). */
export function numberRangeError(field: { min?: number; max?: number }, value: any): string | null {
  if (value === "" || value == null) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return "Enter a valid number";
  if (typeof field.min === "number" && n < field.min) return `Must be ≥ ${field.min}`;
  if (typeof field.max === "number" && n > field.max) return `Must be ≤ ${field.max}`;
  return null;
}

/** Signature stamp — `${full_name} • ${ISO datetime}` (no drawing pad this phase). */
export function makeSignatureStamp(name: string, now: Date = new Date()) {
  const signed_at = now.toISOString();
  const signer_name = (name || "").trim() || "Unknown user";
  return { signer_name, signed_at, stamp: `${signer_name} • ${signed_at}` };
}

export function todayISODate(now: Date = new Date()) {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}
