// Feb-2026 · Live-Tech-Map · Phase 4 batched — Team color legend pill.
//
// Compact overlay pinned to the top-right of the dispatch map. One
// row per tech (or crew, or service_day, per the active
// ``PIN_COLOR_MODES``). Clicking a row toggles the isolate for
// that key — sharing the same isolate state as the Tech Load strip.
//
// Deliberately <60 LOC — the map already has plenty of visual weight.
import React from "react";
import { colors } from "@/theme";

function _entriesFor(pins, mode, techColorById, techNameById) {
  if (mode === "service_day") {
    const days = new Set();
    for (const p of pins) {
      if (!p.is_scheduled_this_day) continue;
      const d = p.service_day || (p.service_days || [])[0];
      if (d) days.add(d);
    }
    const _ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
    return [..._ORDER].filter((d) => days.has(d)).map((d) => ({
      key: d, label: d.toUpperCase(),
      color: {
        mon: "#3b82f6", tue: "#8b5cf6", wed: "#22c55e",
        thu: "#f97316", fri: "#ef4444", sat: "#14b8a6",
        sun: "#a855f7",
      }[d],
    }));
  }
  if (mode === "crew") {
    const seen = new Map();
    for (const p of pins) {
      if (!p.is_scheduled_this_day) continue;
      const k = p.crew_label || "Other";
      if (!seen.has(k)) seen.set(k, p.crew_color_hex || "#64748b");
    }
    return [...seen.entries()].map(([label, color]) => ({
      key: label, label, color,
    }));
  }
  // tech (default)
  const seen = new Map();
  for (const p of pins) {
    if (!p.is_scheduled_this_day) continue;
    const tid = (p.assigned_tech_ids || [])[0];
    if (!tid) continue;
    if (!seen.has(tid)) seen.set(tid, p.tech_color_hex || techColorById[tid] || "#0EA5E9");
  }
  return [...seen.entries()].map(([tid, color]) => ({
    key: tid,
    label: (techNameById[tid] || `Tech ${tid.slice(0, 6)}`).split(/\s+/)[0],
    color,
  }));
}

export default function DispatchColorLegend({
  pins = [],
  pinColorMode = "tech",
  techColorById = {},
  techNameById = {},
  isolatedKey = null,
  onIsolate = () => {},
}) {
  const entries = React.useMemo(
    () => _entriesFor(pins, pinColorMode, techColorById, techNameById),
    [pins, pinColorMode, techColorById, techNameById],
  );
  if (!entries.length) return null;
  // Only "tech" mode drives the isolate handler — crew/service_day
  // isolate is a Phase 5 nice-to-have.
  const canIsolate = pinColorMode === "tech";
  return (
    <div
      className="flex flex-wrap items-center gap-1 rounded-lg px-2 py-1.5"
      style={{
        background: "rgba(255,255,255,0.95)",
        border: `1px solid ${colors.border}`,
        boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
        maxWidth: 320,
      }}
      data-testid="dispatch-color-legend"
      data-mode={pinColorMode}
    >
      {entries.map((e) => {
        const active = canIsolate && isolatedKey === e.key;
        return (
          <button
            key={e.key}
            type="button"
            onClick={() => canIsolate && onIsolate(isolatedKey === e.key ? null : e.key)}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[11px] font-semibold transition"
            style={{
              background: active ? colors.brand : "transparent",
              color: active ? "#fff" : colors.onSurface,
              cursor: canIsolate ? "pointer" : "default",
              opacity: (isolatedKey && !active && canIsolate) ? 0.5 : 1,
            }}
            data-testid={`dispatch-color-legend-item-${e.key}`}
            data-active={active ? "true" : "false"}
          >
            <span
              aria-hidden="true"
              style={{
                width: 8, height: 8, borderRadius: 999, background: e.color,
              }}
            />
            {e.label}
          </button>
        );
      })}
    </div>
  );
}
