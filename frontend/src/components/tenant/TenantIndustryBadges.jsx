/**
 * Phase Feb-2026 · Multi-industry Phase B — Tenant industry badges.
 *
 * Compact chip strip that surfaces the tenant's active industries
 * (read from ``useIndustries()``).  Overflow: >4 items → show
 * first 3 + a "+N more" chip that reveals the rest on click.
 *
 * NO gating logic here — this is a pure display component.  Phase C
 * will introduce the ``hasIndustry(slug)`` predicate for feature gates.
 */
import React, { useState } from "react";
import { colors } from "@/theme";
import { INDUSTRY_LABELS } from "@/config/industries";
import { useIndustries } from "@/hooks/useIndustries";

const CHIP_STYLE = {
  fontSize: 11,
  fontWeight: 600,
  padding: "2px 8px",
  borderRadius: 999,
  lineHeight: 1.4,
  whiteSpace: "nowrap",
};

export default function TenantIndustryBadges({ max = 4 }) {
  const { industries, labels, loaded } = useIndustries();
  const [expanded, setExpanded] = useState(false);
  if (!loaded || !industries.length) return null;

  const shownCount = expanded ? industries.length : Math.min(max - 1, industries.length);
  const overflow = industries.length > max && !expanded;
  const shown = overflow ? industries.slice(0, max - 1) : industries;
  const hidden = overflow ? industries.slice(max - 1) : [];

  return (
    <div
      className="inline-flex items-center gap-1 flex-wrap"
      data-testid="tenant-industry-badges"
    >
      {shown.map((slug) => (
        <span
          key={slug}
          style={{
            ...CHIP_STYLE,
            background: "rgba(2,132,199,0.10)",
            color: colors.brand,
            border: `1px solid rgba(2,132,199,0.25)`,
          }}
          data-testid={`tenant-industry-badge-${slug}`}
        >
          {(labels || INDUSTRY_LABELS)[slug] || slug}
        </span>
      ))}
      {overflow ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          title={hidden.map((s) => (labels || INDUSTRY_LABELS)[s] || s).join(", ")}
          style={{
            ...CHIP_STYLE,
            background: colors.surface,
            color: colors.muted,
            border: `1px solid ${colors.border}`,
            cursor: "pointer",
          }}
          data-testid="tenant-industry-badge-overflow"
        >
          +{hidden.length} more
        </button>
      ) : null}
    </div>
  );
}
