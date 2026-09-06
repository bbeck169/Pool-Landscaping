import React from "react";
import { colors } from "@/theme";

/**
 * Phase R0 · Feb-2026 — Period picker for the reporting suite.
 *
 * Renders five preset buttons (MTD / QTD / YTD / Last 30 days /
 * Custom) plus an inline date-range pair when Custom is active.
 * Emits ``onChange({ period, start, end })`` in the same shape
 * expected by ``GET /api/reports/kpi/{metric_key}``.
 *
 * @typedef {Object} PeriodPickerProps
 * @property {{ period: string, start?: string, end?: string }} value
 * @property {(next: { period: string, start?: string, end?: string }) => void} onChange
 * @property {string} [testid="period-picker"]
 */
const PRESETS = [
  { key: "mtd",       label: "MTD" },
  { key: "qtd",       label: "QTD" },
  { key: "ytd",       label: "YTD" },
  { key: "last_30d",  label: "Last 30 days" },
  { key: "custom",    label: "Custom" },
];

export function PeriodPicker({ value, onChange, testid = "period-picker" }) {
  const active = value?.period || "mtd";

  const emit = (period, start, end) => {
    if (period === "custom") {
      onChange({ period, start: start || value?.start || "", end: end || value?.end || "" });
    } else {
      onChange({ period });
    }
  };

  return (
    <div
      className="flex flex-wrap items-center gap-2"
      data-testid={testid}
    >
      {PRESETS.map((p) => {
        const isActive = p.key === active;
        return (
          <button
            key={p.key}
            type="button"
            onClick={() => emit(p.key)}
            className="text-sm font-semibold px-3 py-1.5 rounded-full transition"
            style={{
              backgroundColor: isActive ? colors.brand : colors.surfaceSecondary,
              color: isActive ? "#FFFFFF" : colors.onSurface,
              border: `1px solid ${isActive ? colors.brand : colors.border}`,
            }}
            data-testid={`${testid}-preset-${p.key}`}
            aria-pressed={isActive}
          >
            {p.label}
          </button>
        );
      })}

      {active === "custom" ? (
        <div className="flex items-center gap-2 pl-2 border-l" style={{ borderColor: colors.border }}>
          <input
            type="date"
            value={value?.start || ""}
            onChange={(e) => emit("custom", e.target.value, value?.end)}
            className="text-sm px-2 py-1 rounded border"
            style={{ borderColor: colors.border, color: colors.onSurface }}
            data-testid={`${testid}-start`}
          />
          <span style={{ color: colors.onSurfaceSecondary }}>→</span>
          <input
            type="date"
            value={value?.end || ""}
            onChange={(e) => emit("custom", value?.start, e.target.value)}
            className="text-sm px-2 py-1 rounded border"
            style={{ borderColor: colors.border, color: colors.onSurface }}
            data-testid={`${testid}-end`}
          />
        </div>
      ) : null}
    </div>
  );
}

export default PeriodPicker;
