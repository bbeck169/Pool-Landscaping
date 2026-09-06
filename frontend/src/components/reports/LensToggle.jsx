import React from "react";
import { colors } from "@/theme";

/**
 * Phase R0.1 · Feb-2026 — Lens toggle for grouped revenue metrics.
 *
 * Two-state pill switcher: **Invoiced** (all issued invoices in
 * the period) vs **Collected** (paid invoices only). Emits
 * ``onChange("invoiced" | "collected")``.
 *
 * @typedef {Object} LensToggleProps
 * @property {"invoiced" | "collected"} value
 * @property {(next: "invoiced" | "collected") => void} onChange
 * @property {string} [testid="lens-toggle"]
 */
export function LensToggle({ value, onChange, testid = "lens-toggle" }) {
  const opts = [
    { key: "invoiced",  label: "Invoiced" },
    { key: "collected", label: "Collected" },
  ];
  return (
    <div
      className="inline-flex rounded-full p-1"
      style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
      data-testid={testid}
      role="tablist"
    >
      {opts.map((o) => {
        const active = o.key === value;
        return (
          <button
            key={o.key}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.key)}
            className="text-sm font-semibold px-3 py-1 rounded-full transition"
            style={{
              backgroundColor: active ? colors.brand : "transparent",
              color: active ? "#FFFFFF" : colors.onSurface,
            }}
            data-testid={`${testid}-${o.key}`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export default LensToggle;
