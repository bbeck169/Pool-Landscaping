/**
 * Feb-2026 · MARCO Proactive Alerts — FAB badge.
 *
 * Renders a small circular badge overlay on top of the AIDock FAB
 * when ``count > 0``.  Color is derived from the max active
 * severity (``error > warn > info``).  Numbers display 1-99 as-is,
 * 100+ as ``99+``.
 *
 * Click handler fires ``ai-dock:open-alerts`` on the window so
 * AIDock can open its drawer AND scroll to the alerts panel in
 * Marco's chat view.
 */
import React from "react";
import { colors } from "@/theme";

function _color(bySeverity) {
  if ((bySeverity?.error || 0) > 0) return colors.danger;
  if ((bySeverity?.warn || 0) > 0) return colors.warning || "#f59e0b";
  return colors.brand;
}

function _displayCount(n) {
  if (!n || n < 1) return "";
  if (n > 99) return "99+";
  return String(n);
}

export default function AlertsBadge({ count = 0, bySeverity, onClick }) {
  if (!count || count < 1) return null;
  const bg = _color(bySeverity);
  const display = _displayCount(count);
  const handle = (e) => {
    e.stopPropagation();
    if (typeof onClick === "function") onClick(e);
    try {
      window.dispatchEvent(new CustomEvent("ai-dock:open-alerts", {
        detail: { count, bySeverity },
      }));
    } catch (_err) {
      // best effort
    }
  };
  return (
    <button
      type="button"
      onClick={handle}
      title={`${count} active alert${count === 1 ? "" : "s"}`}
      className="absolute -top-1 -right-1 rounded-full flex items-center justify-center text-[10px] font-bold shadow"
      style={{
        minWidth: 20,
        height: 20,
        padding: "0 6px",
        backgroundColor: bg,
        color: "#fff",
        border: "2px solid #fff",
        lineHeight: 1,
        cursor: "pointer",
      }}
      data-testid="ai-dock-alerts-badge"
      data-severity={bySeverity?.error > 0 ? "error"
                       : bySeverity?.warn > 0 ? "warn" : "info"}
    >
      {display}
    </button>
  );
}
