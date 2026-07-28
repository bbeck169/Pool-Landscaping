/**
 * Task TT · Feb 2026 — graceful fallback for the Zillow adapter surface.
 *
 * Rendered when the RapidAPI-Zillow adapter returns
 *   { unavailable: true, reason: <code> }
 * so the D2D map (and any other property-data-driven view) never
 * crashes when the key is missing, quota is exhausted, or the
 * preview test-scope guard refuses a non-synthetic address.
 */
import React from "react";
import { colors } from "@/theme";

const REASON_COPY = {
  keys_not_configured: "Property data provider is not configured yet.",
  quota_exhausted: "Property data provider is rate-limited — try again shortly.",
  test_scope_refused: "Live property data is disabled in preview for this address.",
  provider_error: "Property data provider is temporarily unreachable.",
  not_found: "No property record found for this address.",
};

export function PropertyMapUnavailable({ reason, onRefresh, testid = "property-map-unavailable" }) {
  const copy = REASON_COPY[reason] || "Property data unavailable — try again later.";
  return (
    <div
      className="rounded-xl px-4 py-3 text-sm flex items-center justify-between gap-3"
      style={{ backgroundColor: "#FEF3C7", color: "#78350F", border: "1px solid #FCD34D" }}
      data-testid={testid}
      role="status"
      aria-live="polite"
    >
      <span>
        <span className="font-semibold">Property data unavailable</span> — {copy}
      </span>
      {onRefresh && (
        <button
          onClick={onRefresh}
          className="px-3 py-1 rounded-lg text-xs font-semibold"
          style={{ backgroundColor: "#FCD34D", color: "#78350F" }}
          data-testid={`${testid}-refresh`}
        >
          Refresh
        </button>
      )}
    </div>
  );
}

export default PropertyMapUnavailable;
