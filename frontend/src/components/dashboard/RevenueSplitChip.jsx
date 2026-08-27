import React, { useMemo } from "react";
import { colors, money } from "@/theme";

/**
 * Feb 2026 · Batch 2 — Pool vs Landscape revenue split chip.
 *
 * Sits directly below the emerald "Total Paid Revenue" hero on the
 * Admin Dashboard and visualises which portion of the tenant's paid
 * revenue came from each service line.
 *
 * Data source: ``GET /api/dashboard`` response fields
 *   * ``pool_revenue``       (dollars)
 *   * ``landscape_revenue``  (dollars)
 *   * ``mixed_revenue``      (dollars — multi-line or unlabelled invoices)
 *
 * All three are additive by construction (the backend bucket rule is
 * mutually exclusive) → their sum equals ``revenue`` up to floating-
 * point rounding. This component doesn't recompute anything; it just
 * renders segments proportional to the values it's handed.
 *
 * Colour tokens: ``colors.pool[500]`` (cyan) and
 * ``colors.landscape[500]`` (green). Mixed uses a neutral gray so it
 * doesn't visually compete with the two brand accents.
 *
 * Props::
 *   pool:      number  · paid dollars attributed to Pool
 *   landscape: number  · paid dollars attributed to Landscape
 *   mixed:     number  · paid dollars in the "mixed" bucket
 *
 * Behaviour:
 *   - When every value is 0, renders the empty state
 *     ("No revenue this period yet").
 *   - Segments < 5% still render at ``minWidth: 4%`` so they don't
 *     disappear entirely; their number label truncates gracefully.
 *   - Percentages round to whole numbers. A non-zero value under 1%
 *     shows as ``<1%`` (never ``0%``) — reads honestly.
 *   - The mixed segment is only rendered when it's > 0.
 */
export default function RevenueSplitChip({ pool = 0, landscape = 0, mixed = 0 }) {
  const nums = useMemo(() => {
    const p = Math.max(0, Number(pool) || 0);
    const l = Math.max(0, Number(landscape) || 0);
    const m = Math.max(0, Number(mixed) || 0);
    const total = p + l + m;
    if (total <= 0) return { total: 0 };
    const pct = (v) => {
      if (v <= 0) return { display: "0%", css: "0%" };
      const raw = (v / total) * 100;
      const rounded = Math.round(raw);
      // Never lie about "0%" for a non-zero value — show ``<1%``.
      const display = raw > 0 && rounded === 0 ? "<1%" : `${rounded}%`;
      // Guarantee at least 4% width so a small segment stays
      // clickable/readable — the label may truncate but the bar
      // doesn't vanish.
      const css = `${Math.max(4, raw)}%`;
      return { display, css };
    };
    return {
      total,
      pool: { value: p, ...pct(p) },
      landscape: { value: l, ...pct(l) },
      mixed: m > 0 ? { value: m, ...pct(m) } : null,
    };
  }, [pool, landscape, mixed]);

  if (nums.total <= 0) {
    return (
      <div
        data-testid="revenue-split-chip-empty"
        className="rounded-xl px-4 py-3 mb-6 flex items-center justify-center text-sm"
        style={{
          backgroundColor: colors.pool[50],
          color: colors.pool[700],
          border: `1px solid ${colors.pool[100]}`,
        }}
      >
        No revenue this period yet — chart will fill in once the first invoice is paid.
      </div>
    );
  }

  const segments = [
    { key: "pool", label: "Pool", color: colors.pool[500],
      textColor: "#083344", seg: nums.pool },
    { key: "landscape", label: "Landscape", color: colors.landscape[500],
      textColor: "#052E16", seg: nums.landscape },
    ...(nums.mixed
      ? [{ key: "mixed", label: "Mixed", color: "#9CA3AF",
          textColor: "#111827", seg: nums.mixed }]
      : []),
  ].filter((s) => s.seg && s.seg.value > 0);

  return (
    <div className="mb-6" data-testid="revenue-split-chip">
      <div
        className="flex w-full h-6 rounded-full overflow-hidden"
        style={{ backgroundColor: "#F3F4F6" }}
      >
        {segments.map((s) => (
          <div
            key={s.key}
            data-testid={`revenue-split-segment-${s.key}`}
            className="flex items-center justify-center text-[10px] font-semibold whitespace-nowrap overflow-hidden"
            style={{
              width: s.seg.css,
              backgroundColor: s.color,
              color: s.textColor,
            }}
            title={`${s.label}: ${money(s.seg.value)} (${s.seg.display})`}
          >
            {s.seg.display}
          </div>
        ))}
      </div>
      <div
        className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs"
        style={{ color: "#4B5563" }}
      >
        {segments.map((s) => (
          <div
            key={s.key}
            data-testid={`revenue-split-legend-${s.key}`}
            className="flex items-center gap-1.5"
          >
            <span
              className="inline-block w-2.5 h-2.5 rounded-sm"
              style={{ backgroundColor: s.color }}
            />
            <span className="font-medium">{s.label}</span>
            <span>
              {money(s.seg.value)} ({s.seg.display})
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
