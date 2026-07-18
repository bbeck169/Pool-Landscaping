import React from "react";
import { colors } from "@/theme";

const META = {
  draft:     { label: "Draft",     bg: "#FEF9C3", fg: "#A16207" },
  finalized: { label: "Finalized", bg: "#DCFCE7", fg: "#166534" },
};

/**
 * Small status pill for template instance state.
 * Keeps colours in-sync with `theme.statusMeta` conventions.
 */
export default function TemplateStatusPill({ status = "draft" }) {
  const meta = META[status] || { label: status, bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary };
  return (
    <span
      data-testid={`template-status-pill-${status}`}
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
      style={{ backgroundColor: meta.bg, color: meta.fg }}
    >
      {meta.label}
    </span>
  );
}
