import React from "react";
import { colors } from "@/theme";
import { formatValue } from "./formatters";

/**
 * Phase R0 · Feb-2026 — Variance tile (Datarails-signature style).
 *
 * Renders current vs prior side-by-side with a percent delta and
 * an up/down arrow tone-mapped via ``direction``.
 *
 * @typedef {Object} VarianceTileProps
 * @property {string} label
 * @property {number|null} current
 * @property {number|null} prior
 * @property {number|null} deltaPct
 * @property {"currency"|"number"|"percent"} [format="number"]
 * @property {"up_is_good"|"down_is_good"} [direction="up_is_good"]
 * @property {string} [testid="variance-tile"]
 */
export function VarianceTile({
  label,
  current,
  prior,
  deltaPct,
  format = "number",
  direction = "up_is_good",
  testid = "variance-tile",
}) {
  const positive = typeof deltaPct === "number" && deltaPct > 0;
  const negative = typeof deltaPct === "number" && deltaPct < 0;
  const good = direction === "down_is_good" ? negative : positive;
  const bad = direction === "down_is_good" ? positive : negative;

  const tone = good ? "up" : bad ? "down" : "flat";
  const stripeColor = good
    ? colors.success
    : bad
      ? colors.error
      : colors.surfaceTertiary;

  const arrow = tone === "up" ? "▲" : tone === "down" ? "▼" : "▬";
  const arrowColor = good ? colors.success : bad ? colors.error : colors.onSurfaceSecondary;

  const deltaLabel =
    typeof deltaPct === "number" && !Number.isNaN(deltaPct)
      ? `${deltaPct > 0 ? "+" : ""}${deltaPct.toFixed(1)}%`
      : "—";

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ backgroundColor: colors.surface, borderColor: colors.border }}
      data-testid={testid}
    >
      <div style={{ height: 4, backgroundColor: stripeColor }} data-testid={`${testid}-stripe-${tone}`} />
      <div className="p-4 flex items-center gap-4">
        <div className="flex-1">
          <div
            className="text-xs font-semibold uppercase tracking-wide"
            style={{ color: colors.onSurfaceSecondary }}
            data-testid={`${testid}-label`}
          >
            {label}
          </div>
          <div className="flex items-baseline gap-3 mt-1">
            <div
              className="text-2xl font-bold"
              style={{ color: colors.onSurface }}
              data-testid={`${testid}-current`}
            >
              {formatValue(current, format)}
            </div>
            <div
              className="text-sm"
              style={{ color: colors.onSurfaceSecondary }}
              data-testid={`${testid}-prior`}
            >
              vs {formatValue(prior, format)}
            </div>
          </div>
        </div>
        <div
          className="flex items-center gap-1 text-sm font-semibold"
          style={{ color: arrowColor }}
          data-testid={`${testid}-delta`}
        >
          <span aria-hidden="true">{arrow}</span>
          <span>{deltaLabel}</span>
        </div>
      </div>
    </div>
  );
}

export default VarianceTile;
