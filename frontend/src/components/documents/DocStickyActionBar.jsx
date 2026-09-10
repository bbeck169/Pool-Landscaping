/**
 * Feb-2026 · Universal mobile-responsive redesign · shared
 * sticky bottom action bar for customer-facing docs.
 *
 * Contract
 * --------
 *   props.actions — ordered list of action buttons, each:
 *     { key, label, tone, disabled, onClick, testid, icon }
 *     tone: "approve" (green) | "decline" (red) |
 *           "primary" (brand) | "secondary" (outline)
 *   props.hint — optional inline hint node (e.g. Phase C
 *                "Sign to enable" gate hint). Renders full-width
 *                above the button row on mobile.
 *
 * On desktop (>= 768px) the bar renders inline (no sticky
 * positioning) so surfaces can drop this component in without
 * conditional rendering.
 */
import React from "react";
import useViewportBreakpoint from "@/hooks/useViewportBreakpoint";


const TONE_STYLES = {
  approve: {
    background: "#059669",
    color: "#FFFFFF",
    border: "1px solid #059669",
  },
  decline: {
    background: "#DC2626",
    color: "#FFFFFF",
    border: "1px solid #DC2626",
  },
  primary: {
    background: "#0EA5E9",
    color: "#FFFFFF",
    border: "1px solid #0EA5E9",
  },
  secondary: {
    background: "transparent",
    color: "#0F172A",
    border: "1px solid #E5E7EB",
  },
};


export default function DocStickyActionBar({
  actions = [],
  hint = null,
  testid = "doc-sticky-action-bar",
}) {
  const bp = useViewportBreakpoint();
  const isMobile = bp === "mobile";

  const wrapStyle = isMobile
    ? {
        position: "fixed",
        left: 0, right: 0, bottom: 0,
        padding: "12px 16px calc(12px + env(safe-area-inset-bottom, 0px))",
        background: "rgba(255,255,255,0.98)",
        borderTop: "1px solid rgba(0,0,0,0.08)",
        boxShadow: "0 -6px 20px rgba(0,0,0,0.08)",
        zIndex: 40,
        display: "grid",
        gap: 8,
      }
    : {
        display: "flex",
        gap: 8,
        justifyContent: "flex-end",
        padding: "12px 0",
      };

  return (
    <div
      className="doc-sticky-action-bar"
      data-testid={testid}
      data-viewport={bp}
      style={wrapStyle}
    >
      {hint ? (
        <div
          style={isMobile ? { gridColumn: "1 / -1" } : { flex: 1 }}
          data-testid={`${testid}-hint`}
        >
          {hint}
        </div>
      ) : null}
      <div
        style={
          isMobile
            ? { display: "grid",
                gridTemplateColumns: `repeat(${actions.length}, minmax(0, 1fr))`,
                gap: 8 }
            : { display: "flex", gap: 8 }
        }
      >
        {actions.map((a) => {
          const tone = TONE_STYLES[a.tone] || TONE_STYLES.secondary;
          return (
            <button
              key={a.key || a.testid}
              onClick={a.onClick}
              disabled={a.disabled}
              data-testid={a.testid}
              style={{
                ...tone,
                minHeight: isMobile ? 44 : 36,
                padding: isMobile ? "12px 16px" : "8px 14px",
                borderRadius: 12,
                fontWeight: 700,
                fontSize: isMobile ? 16 : 14,
                cursor: a.disabled ? "not-allowed" : "pointer",
                opacity: a.disabled ? 0.5 : 1,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 6,
              }}
            >
              {a.icon || null}
              {a.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
