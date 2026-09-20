import React from "react";

/**
 * Phase G4 · Feb-2026 — shared Suspense fallback used while a
 * route-level chunk is being fetched. Kept intentionally small +
 * dependency-free so it lives in the main bundle without cost.
 *
 * Renders a subdued full-width shimmering block. Non-blocking; if a
 * chunk arrives in <100ms the user barely sees the flash.
 */
export default function PageSkeleton() {
  return (
    <div
      data-testid="page-skeleton"
      role="status"
      aria-live="polite"
      aria-busy="true"
      style={{
        padding: "40px 24px",
        display: "flex",
        flexDirection: "column",
        gap: 16,
        opacity: 0.9,
      }}
    >
      <div style={_bar(28, "50%")} />
      <div style={_bar(14, "80%")} />
      <div style={_bar(14, "70%")} />
      <div style={_bar(200, "100%", 12)} />
      <span
        style={{
          position: "absolute",
          width: 1, height: 1, padding: 0,
          overflow: "hidden", clip: "rect(0,0,0,0)",
          whiteSpace: "nowrap", border: 0,
        }}
      >
        Loading page…
      </span>
    </div>
  );
}


function _bar(height, width, radius = 8) {
  return {
    height, width, borderRadius: radius,
    background:
      "linear-gradient(90deg, #E4E4E7 0%, #F4F4F5 50%, #E4E4E7 100%)",
    backgroundSize: "200% 100%",
    animation: "g4-page-skeleton-shimmer 1.4s ease-in-out infinite",
  };
}


// Inject the keyframes exactly once at module load. Prefer this over
// a global CSS file because the skeleton is used ONLY here and CSS
// module scoping across the tree gets awkward for a one-off.
if (typeof document !== "undefined" &&
    !document.getElementById("g4-page-skeleton-style")) {
  const s = document.createElement("style");
  s.id = "g4-page-skeleton-style";
  s.textContent =
    "@keyframes g4-page-skeleton-shimmer { "
    + "0% { background-position: 200% 0; } "
    + "100% { background-position: -200% 0; } }";
  document.head.appendChild(s);
}
