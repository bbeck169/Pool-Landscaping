/**
 * Ticket AA · Feb-2026 · CombinedCategoryBadge
 *
 * Replaces the P2 #6 editable ``<ServiceCategoryControl>`` on the
 * CustomerDetail identity header with a read-only "combined
 * category" badge computed from the customer's `properties`.
 *
 * Rules (locked in operator decision 2a):
 *   all-Pool                       → "Pool"
 *   all-Landscaping                → "Landscaping"
 *   all-Both                       → "Both"
 *   mix (any combination of Pool,
 *        Landscaping, Both)        → joined with " + " in canonical
 *                                     order Pool / Landscaping / Both
 *   zero properties OR all null   → "—" muted
 *
 * Hover tooltip: "Set category per property below" — points the
 * operator at the per-property chip-group selector in the
 * Properties tab (the single authoring surface post-AA).
 */
import React from "react";
import { colors } from "@/theme";


const _ORDER = ["pool", "landscaping", "both"];
const _LABEL = {
  pool: "Pool",
  landscaping: "Landscaping",
  both: "Both",
};


export function _computeCombinedCategory(properties) {
  if (!Array.isArray(properties) || properties.length === 0) return null;
  const present = new Set();
  for (const p of properties) {
    // Skip inactive — the dashboard aggregator excludes
    // ``active===false`` so the badge mirrors that visibility.
    if (p?.active === false) continue;
    const cat = (p?.service_category || "").toString().toLowerCase();
    if (_ORDER.includes(cat)) present.add(cat);
  }
  if (present.size === 0) return null;
  const parts = _ORDER.filter((c) => present.has(c)).map((c) => _LABEL[c]);
  return parts.join(" + ");
}


export function CombinedCategoryBadge({ properties }) {
  const label = _computeCombinedCategory(properties);
  const empty = !label;
  return (
    <span
      className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold uppercase tracking-wider"
      style={{
        backgroundColor: empty ? colors.surfaceSecondary : "#DBEAFE",
        color: empty ? colors.muted : "#1E3A8A",
        border: `1px solid ${empty ? colors.border : "#93C5FD"}`,
        cursor: "default",
      }}
      title="Set category per property below"
      data-testid="customer-combined-category-badge"
      data-combined-category={label || ""}
    >
      {empty ? "—" : label}
    </span>
  );
}
