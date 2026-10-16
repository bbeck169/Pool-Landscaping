/**
 * EBITDA-SOFT-ADD (mobile mirror of web 73f5fbc9a + 892e4c38e).
 * Wire fields are `ebitda` / `ebit` (dollars). BE hydrates `ebitda` on
 * legacy rows, but a row that still lacks it is shown as EBIT + legacy chip.
 */
export const EBITDA_TOOLTIP =
  "EBITDA: Earnings Before Interest, Taxes, Depreciation, and Amortization. " +
  "A financial metric used to measure a company's overall operational profitability and core earning power.";

export const EBITDA_LEGACY_LABEL = "EBIT only (legacy)";

type Row = { ebit?: number | null; ebitda?: number | null } | null | undefined;

/** Primary read = `ebitda`; null/missing → `ebit` with `legacy: true`. */
export function resolveEbitda(row: Row): { value: number; legacy: boolean } {
  if (row?.ebitda != null && Number.isFinite(Number(row.ebitda))) {
    return { value: Number(row.ebitda), legacy: false };
  }
  return { value: Number(row?.ebit || 0), legacy: row != null };
}
