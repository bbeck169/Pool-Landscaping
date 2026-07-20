import React from "react";

const TONES = {
  pending:                   { bg: "#FEF3C7", fg: "#92400E", label: "Pending" },
  public_posted_intent:      { bg: "#DCFCE7", fg: "#166534", label: "Posted to platform" },
  private_feedback_captured: { bg: "#DBEAFE", fg: "#1E3A8A", label: "Private feedback" },
  expired:                   { bg: "#E5E7EB", fg: "#374151", label: "Expired" },
  opted_out:                 { bg: "#FEE2E2", fg: "#991B1B", label: "Opted out" },
};

/** Colored outcome pill for review-request rows. */
export function OutcomePill({ outcome, className = "", testid }) {
  const t = TONES[outcome] || TONES.pending;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${className}`}
           style={{ background: t.bg, color: t.fg }}
           data-testid={testid || `outcome-${outcome}`}>
      {t.label}
    </span>
  );
}

export default OutcomePill;
