/**
 * Feb-2026 · Batch #4 · Item 3 (continuation) — shared refresh
 * button used by every schedule surface (TodaySchedule + all
 * CalendarSchedule modes/views: Calendar month, Calendar agenda,
 * Grid day). Centralising here avoids the per-surface divergence
 * that let the button go missing on Calendar mode after the
 * initial Grid-only ship.
 *
 * Invariants:
 *   • Always renders ``data-testid="schedule-refresh"``.
 *   • Click invokes ``onRefresh()`` (nothing else — no side-effects,
 *     no ReferenceError to an out-of-scope symbol).
 *   • Disabled + no-op while ``busy`` is true (double-click guard).
 *   • Spinner surfaces via ``data-testid="schedule-refresh-spinner"``
 *     on the inner icon only while busy.
 */
import React from "react";
import { RefreshCw } from "lucide-react";
import { colors } from "@/theme";


export default function ScheduleRefreshButton({ busy = false, onRefresh }) {
  return (
    <button
      type="button"
      onClick={() => {
        if (busy) return;
        onRefresh?.();
      }}
      disabled={busy}
      className="w-9 h-9 rounded-lg flex items-center justify-center"
      style={{
        background: colors.surfaceSecondary,
        border: `1px solid ${colors.border}`,
        color: colors.onSurface,
        opacity: busy ? 0.6 : 1,
        cursor: busy ? "wait" : "pointer",
      }}
      title="Refresh schedule"
      aria-label="Refresh schedule"
      data-testid="schedule-refresh"
    >
      <RefreshCw
        size={16}
        className={busy ? "animate-spin" : ""}
        data-testid={busy ? "schedule-refresh-spinner" : undefined}
      />
    </button>
  );
}
