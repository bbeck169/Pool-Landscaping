import React from "react";
import { colors } from "@/theme";
import { formatValue, formatDelta } from "./formatters";

/**
 * Phase R0 · Feb-2026 — KPI card component.
 *
 * Big value + label + prior/delta chip + optional inline sparkline.
 *
 * @typedef {Object} KpiCardProps
 * @property {string} label              — human-readable metric name (e.g. "Total Revenue")
 * @property {number|null} value         — current-period value
 * @property {number|null} priorValue    — same-length prior-period value
 * @property {number|null} deltaPct      — signed percent delta (nullable when prior = 0)
 * @property {Array<{t: string, v: number}>} [sparkline]
 *                                       — optional sparkline points
 * @property {"currency"|"number"|"percent"} [format="number"]
 *                                       — routes to the correct formatter
 * @property {"up_is_good"|"down_is_good"} [direction="up_is_good"]
 *                                       — controls green/red tone on the delta chip
 * @property {boolean} [loading=false]
 * @property {string|null} [error=null]
 * @property {string} [testid="kpi-card"]
 */
export function KpiCard({
  label,
  value,
  priorValue,
  deltaPct,
  sparkline,
  format = "number",
  direction = "up_is_good",
  loading = false,
  error = null,
  testid = "kpi-card",
}) {
  return (
    <div
      className="rounded-xl border p-5 flex flex-col gap-3"
      style={{
        backgroundColor: colors.surface,
        borderColor: colors.border,
      }}
      data-testid={testid}
    >
      <div className="flex items-center justify-between">
        <span
          className="text-sm font-semibold uppercase tracking-wide"
          style={{ color: colors.onSurfaceSecondary }}
          data-testid={`${testid}-label`}
        >
          {label}
        </span>
        <DeltaChip
          deltaPct={deltaPct}
          direction={direction}
          testid={`${testid}-delta`}
        />
      </div>

      <div
        className="text-3xl font-bold leading-none"
        style={{ color: colors.onSurface }}
        data-testid={`${testid}-value`}
      >
        {loading ? (
          <span className="opacity-40">…</span>
        ) : error ? (
          <span style={{ color: colors.error }} className="text-base font-medium">
            {String(error)}
          </span>
        ) : (
          formatValue(value, format)
        )}
      </div>

      <div
        className="text-xs"
        style={{ color: colors.onSurfaceSecondary }}
        data-testid={`${testid}-prior`}
      >
        Prior period: {formatValue(priorValue, format)}
      </div>

      {sparkline && sparkline.length > 0 ? (
        <InlineSparkline
          points={sparkline}
          direction={direction}
          testid={`${testid}-sparkline`}
        />
      ) : null}
    </div>
  );
}

function DeltaChip({ deltaPct, direction, testid }) {
  const label = formatDelta(deltaPct);
  const positive = typeof deltaPct === "number" && deltaPct > 0;
  const negative = typeof deltaPct === "number" && deltaPct < 0;
  const good = direction === "down_is_good" ? negative : positive;
  const bad = direction === "down_is_good" ? positive : negative;

  const palette = good
    ? { bg: "#DCFCE7", fg: colors.success }
    : bad
      ? { bg: "#FEE2E2", fg: colors.error }
      : { bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary };

  return (
    <span
      className="text-xs font-semibold px-2 py-0.5 rounded-full"
      style={{ backgroundColor: palette.bg, color: palette.fg }}
      data-testid={testid}
    >
      {label}
    </span>
  );
}

function InlineSparkline({ points, direction, testid }) {
  // Deliberately zero-dependency — a tiny inline SVG so the KPI
  // card can render even in a test-runner without ApexCharts
  // registered. The real ``<TrendChart>`` uses ApexCharts for the
  // full-fidelity dashboard tiles.
  if (points.length < 2) {
    return (
      <div className="text-xs opacity-40" data-testid={`${testid}-empty`}>
        Not enough data for trend
      </div>
    );
  }
  const w = 200;
  const h = 40;
  const values = points.map((p) => p.v);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = w / (points.length - 1);
  const path = points
    .map((p, i) => {
      const x = i * stepX;
      const y = h - ((p.v - min) / range) * h;
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  const stroke = direction === "down_is_good" ? colors.info : colors.brand;
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="w-full h-10"
      preserveAspectRatio="none"
      data-testid={testid}
    >
      <path d={path} fill="none" stroke={stroke} strokeWidth={2} />
    </svg>
  );
}

export default KpiCard;
