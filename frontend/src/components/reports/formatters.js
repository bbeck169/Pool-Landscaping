/**
 * Phase R0 · Feb-2026 — value formatters for the reporting suite.
 *
 * One tiny module so every KPI tile / variance card renders with
 * identical formatting rules. Consumers pass a ``format`` prop
 * ("currency" | "number" | "percent") plus the raw numeric value
 * and get back a human string.
 *
 * These helpers are pure — no i18n dependency, no Intl side
 * effects that require test setup — so they're safe to call
 * inside render loops and inside vitest.
 */

/**
 * Format a number as US-dollar currency with 2-decimal precision.
 * Nulls / undefineds / NaN render as `"—"` so the KPI tile stays
 * readable while backend data is loading.
 *
 * @param {number|null|undefined} value
 * @param {{ compact?: boolean }} [opts]
 */
export function formatCurrency(value, opts = {}) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const v = Number(value);
  if (opts.compact && Math.abs(v) >= 1000) {
    const units = [
      { div: 1e9, s: "B" },
      { div: 1e6, s: "M" },
      { div: 1e3, s: "k" },
    ];
    for (const { div, s } of units) {
      if (Math.abs(v) >= div) {
        return `$${(v / div).toFixed(v % div === 0 ? 0 : 1)}${s}`;
      }
    }
  }
  return v.toLocaleString("en-US", {
    style: "currency", currency: "USD",
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

/** Format an integer or float with thousand separators. */
export function formatNumber(value, opts = {}) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const v = Number(value);
  const decimals = opts.decimals ?? (Number.isInteger(v) ? 0 : 2);
  return v.toLocaleString("en-US", {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  });
}

/**
 * Format a percentage. Accepts EITHER a fractional value (0.25 →
 * "25.0%") OR a whole-number percent (25 → "25.0%") depending on
 * ``opts.fractional``.
 */
export function formatPercent(value, opts = {}) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const raw = opts.fractional ? Number(value) * 100 : Number(value);
  const decimals = opts.decimals ?? 1;
  const sign = opts.signed && raw > 0 ? "+" : "";
  return `${sign}${raw.toFixed(decimals)}%`;
}

/**
 * Format a signed delta (e.g. `-12.4` → `"−12.4%"`, `12.4` → `"+12.4%"`).
 * Null returns `"—"` so a metric with no prior-period baseline
 * renders a neutral chip.
 */
export function formatDelta(deltaPct) {
  if (deltaPct === null || deltaPct === undefined || Number.isNaN(Number(deltaPct))) return "—";
  return formatPercent(deltaPct, { signed: true, decimals: 1 });
}

/** Route to the right formatter based on the backend's ``format`` metadata. */
export function formatValue(value, format) {
  if (format === "currency") return formatCurrency(value);
  if (format === "percent") return formatPercent(value);
  return formatNumber(value);
}
