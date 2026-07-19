import React from "react";
import { colors } from "@/theme";

const STATUS_COLOURS = {
  queued: { bg: "#EFF6FF", fg: "#1D4ED8", border: "#BFDBFE" },
  sent: { bg: "#DCFCE7", fg: "#166534", border: "#86EFAC" },
  mocked: { bg: "#FEF9C3", fg: "#854D0E", border: "#FDE68A" },
  failed: { bg: "#FEE2E2", fg: "#991B1B", border: "#FECACA" },
  opted_out: { bg: "#F3F4F6", fg: "#374151", border: "#D1D5DB" },
  missing_key: { bg: "#FFEDD5", fg: "#9A3412", border: "#FDBA74" },
};

export default function SendStatusPill({ status }) {
  const s = STATUS_COLOURS[status] || {
    bg: colors.surfaceSecondary, fg: colors.muted, border: colors.border,
  };
  return (
    <span
      className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
      style={{ background: s.bg, color: s.fg, border: `1px solid ${s.border}` }}
      data-testid={`send-status-${status || "unknown"}`}
    >
      {String(status || "unknown").replace(/_/g, " ")}
    </span>
  );
}
