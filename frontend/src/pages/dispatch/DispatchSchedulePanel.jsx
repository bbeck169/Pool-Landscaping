// Feb-2026 · Live-Tech-Map · Phase 4.a + Q4 — DispatchSchedulePanel.
//
// Compact scrollable list of the day's scheduled stops, rendered
// in the left column below the existing filters. Groups follow the
// active ``PIN_COLOR_MODES`` control — one control drives BOTH the
// map's pin color AND the panel's grouping (tech / crew / service_
// day) so admins never have to sync two settings.
//
// Data source: ``board.pins`` (fanned-out by
// ``is_scheduled_this_day``). We intentionally do NOT use
// ``board.route_stops`` because it's only populated when the
// backend has a single ``tech_user_id`` filter — the panel needs
// to work across "All techs" too.
//
// Q4 — clicking a row focuses the map on that stop (via the
// ``onFocusStop`` callback the parent wires to
// ``setSelectedCustomerId`` + ``setFocusedStopId``).
import React from "react";
import { colors } from "@/theme";
import { colorForPin, PIN_COLOR_BY_DAY, CREW_LEGEND } from "@/pages/dispatch/dispatchColors";
import formatAddress from "@/utils/formatAddress";

const _DAY_ORDER = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

function _groupPins(pins, mode, techColorById, techNameById) {
  const groups = {};
  const meta = {};
  for (const p of pins) {
    let key, label, dot;
    if (mode === "service_day") {
      key = p.service_day || (p.service_days || [])[0] || "unknown";
      label = key === "unknown" ? "Unassigned day" : key.toUpperCase();
      dot = PIN_COLOR_BY_DAY[key] || "#64748b";
    } else if (mode === "crew") {
      key = p.crew_label || "Other";
      label = key;
      dot = p.crew_color_hex || (CREW_LEGEND.find((c) => c.label === key) || {}).color || "#64748b";
    } else {
      // tech (default)
      const tid = (p.assigned_tech_ids || [])[0] || "unassigned";
      key = tid;
      label = techNameById[tid] || (tid === "unassigned" ? "Unassigned" : `Tech ${String(tid).slice(0, 6)}`);
      dot = p.tech_color_hex || techColorById[tid] || "#0EA5E9";
    }
    if (!groups[key]) {
      groups[key] = [];
      meta[key] = { label, dot };
    }
    groups[key].push(p);
  }
  // Sort keys for stable rendering.
  const orderedKeys = Object.keys(groups).sort((a, b) => {
    if (mode === "service_day") {
      return _DAY_ORDER.indexOf(a) - _DAY_ORDER.indexOf(b);
    }
    return (meta[a].label || "").localeCompare(meta[b].label || "");
  });
  return orderedKeys.map((k) => ({
    key: k, label: meta[k].label, dot: meta[k].dot, pins: groups[k],
  }));
}

export default function DispatchSchedulePanel({
  pins = [],
  pinColorMode = "tech",
  techColorById = {},
  techNameById = {},
  dayLabel = "today",
  focusedStopId = null,
  isolatedTechId = null,
  onFocusStop = () => {},
}) {
  // Only show pins that are actually on the schedule (day-scoped)
  // — the "unscheduled" ones live in the drag panel elsewhere.
  const scheduled = React.useMemo(
    () => pins.filter((p) => p.is_scheduled_this_day),
    [pins],
  );
  const groups = React.useMemo(
    () => _groupPins(scheduled, pinColorMode, techColorById, techNameById),
    [scheduled, pinColorMode, techColorById, techNameById],
  );

  if (!scheduled.length) {
    return (
      <div
        className="rounded-xl p-3 text-xs"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
          color: colors.muted,
        }}
        data-testid="dispatch-schedule-panel"
        data-empty="true"
      >
        No jobs scheduled for {dayLabel}.
      </div>
    );
  }

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="dispatch-schedule-panel"
      data-pin-color-mode={pinColorMode}
      data-empty="false"
    >
      <div
        className="px-3 py-2 text-[10px] font-bold uppercase tracking-wide"
        style={{
          color: colors.muted,
          borderBottom: `1px solid ${colors.border}`,
          backgroundColor: colors.surfaceSecondary,
        }}
      >
        Schedule · {scheduled.length} stop{scheduled.length === 1 ? "" : "s"}
      </div>
      <div
        className="overflow-y-auto"
        style={{ maxHeight: 420 }}
      >
        {groups.map((g) => (
          <div key={g.key} data-testid={`dispatch-schedule-group-${g.key}`}>
            <div
              className="px-3 py-1.5 flex items-center gap-2 text-[11px] font-bold"
              style={{
                color: colors.onSurface,
                backgroundColor: colors.surfaceSecondary,
                borderTop: `1px solid ${colors.border}`,
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  width: 8, height: 8, borderRadius: 999, background: g.dot,
                }}
              />
              <span className="uppercase tracking-wide">{g.label}</span>
              <span
                className="ml-auto text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                style={{ backgroundColor: colors.surface, color: colors.muted }}
              >
                {g.pins.length}
              </span>
            </div>
            {g.pins.map((p) => {
              const focused = focusedStopId === p.customer_id;
              // Isolate dim: only in "tech" mode does the isolate
              // apply here — crew / day panels are keyed on a
              // different attribute so isolating by tech would
              // silently hide rows that share a crew/day.
              const dimmed =
                pinColorMode === "tech" &&
                isolatedTechId &&
                !(p.assigned_tech_ids || []).includes(isolatedTechId);
              return (
                <button
                  key={p.customer_id}
                  type="button"
                  onClick={() => onFocusStop(p)}
                  className="w-full text-left px-3 py-2 text-xs transition"
                  style={{
                    borderTop: `1px solid ${colors.border}`,
                    background: focused ? "#EFF6FF" : colors.surface,
                    color: colors.onSurface,
                    opacity: dimmed ? 0.35 : 1,
                    cursor: "pointer",
                  }}
                  data-testid={`dispatch-schedule-panel-item-${p.customer_id}`}
                  data-focused={focused ? "true" : "false"}
                  data-dimmed={dimmed ? "true" : "false"}
                >
                  <div className="flex items-center gap-2">
                    <span
                      aria-hidden="true"
                      style={{
                        width: 8, height: 8, borderRadius: 999,
                        background: colorForPin(p, pinColorMode, techColorById),
                        flexShrink: 0,
                      }}
                    />
                    <span
                      className="font-semibold truncate"
                      style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    >
                      {p.name || "Unknown customer"}
                    </span>
                  </div>
                  <div
                    className="text-[11px] mt-0.5 pl-4"
                    style={{ color: colors.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                  >
                    {formatAddress(p.address) || "—"}
                  </div>
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
