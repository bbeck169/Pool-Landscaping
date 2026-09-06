import React from "react";
import { colors } from "@/theme";
import { formatCurrency } from "./formatters";


/**
 * Phase R0.1+ · Feb-2026 — Prior-period delta cell.
 *
 * Renders a two-line stack:
 *   ± $DELTA        (bold, tone-coloured)
 *   ± NN.N %         (small, tone-coloured)
 *
 * Tone rules:
 *   * ``priorRevenue == 0`` and current > 0  → neutral "New" chip.
 *   * ``delta_abs > 0`` → up tone (brand accent).
 *   * ``delta_abs < 0`` → down tone (error).
 *   * ``delta_abs == 0`` → muted neutral.
 *
 * The component is intentionally testid-friendly so the panel
 * tests can assert tone selection without inspecting CSS.
 */
export function DeltaCell({ deltaAbs, deltaPct, priorRevenue, testid = "delta-cell" }) {
  const isNew = Number(priorRevenue || 0) === 0
    && Number(deltaAbs || 0) !== 0;

  let tone = "neutral";
  if (isNew) tone = "new";
  else if (deltaAbs == null) tone = "neutral";
  else if (Number(deltaAbs) > 0) tone = "up";
  else if (Number(deltaAbs) < 0) tone = "down";

  const toneColor = {
    up: colors.success || colors.brand,
    down: colors.error,
    new: colors.brandTertiary,
    neutral: colors.onSurfaceSecondary,
  }[tone];

  const toneBg = {
    up: (colors.successMuted || colors.brandTertiary),
    down: (colors.errorMuted || colors.errorBg || colors.brandTertiary),
    new: (colors.brandTertiary),
    neutral: (colors.surfaceSecondary),
  }[tone];

  if (isNew) {
    return (
      <span
        className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold"
        data-testid={testid}
        data-tone="new"
        style={{ color: toneColor, backgroundColor: toneBg }}
      >
        New
      </span>
    );
  }

  if (deltaAbs == null || Number(deltaAbs) === 0) {
    return (
      <span
        className="text-xs"
        data-testid={testid}
        data-tone="neutral"
        style={{ color: colors.onSurfaceSecondary }}
      >
        —
      </span>
    );
  }

  const sign = Number(deltaAbs) > 0 ? "+" : "";
  const pctSign = deltaPct != null && Number(deltaPct) > 0 ? "+" : "";
  return (
    <span
      className="inline-flex flex-col items-end leading-tight"
      data-testid={testid}
      data-tone={tone}
      style={{ color: toneColor }}
    >
      <span className="text-sm font-semibold">
        {sign}{formatCurrency(deltaAbs)}
      </span>
      {deltaPct != null ? (
        <span className="text-xs" data-testid={`${testid}-pct`}>
          {pctSign}{Number(deltaPct).toFixed(1)}%
        </span>
      ) : null}
    </span>
  );
}

export default DeltaCell;
