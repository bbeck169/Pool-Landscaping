// Phase 17 · Feb-2026 — Pin color mode helpers.
//
// Three admin-selectable modes for the Dispatch Board map:
//   • tech         → use assigned tech's display_color_hex
//   • crew         → use the crew (department) color
//   • service_day  → use the fixed day-of-week color
//
// Storage key: ``dispatch.pin_color_mode`` in localStorage. Default
// is ``tech``. Unrouted pins ALWAYS render gray/hollow regardless
// of the active mode.

export const PIN_COLOR_MODES = [
  { key: "tech", label: "Tech" },
  { key: "crew", label: "Crew" },
  { key: "service_day", label: "Service day" },
];

export const PIN_COLOR_BY_DAY = {
  mon: "#3b82f6", // blue
  tue: "#8b5cf6", // purple
  wed: "#22c55e", // green
  thu: "#f97316", // orange
  fri: "#ef4444", // red
  sat: "#14b8a6", // teal
  sun: "#a855f7", // fuchsia
};

export const CREW_LEGEND = [
  { label: "Pool",        color: "#0ea5e9" },
  { label: "Landscaping", color: "#16a34a" },
  { label: "Repairs",     color: "#f59e0b" },
  { label: "Other",       color: "#64748b" },
];

const STORAGE_KEY = "dispatch.pin_color_mode";

export function loadPinColorMode() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v && PIN_COLOR_MODES.some((m) => m.key === v)) return v;
  } catch { /* jsdom */ }
  return "tech";
}

export function savePinColorMode(mode) {
  try { localStorage.setItem(STORAGE_KEY, mode); } catch { /* jsdom */ }
}

export function colorForPin(pin, mode, techColorById = {}) {
  if (!pin) return "#0EA5E9";
  if (mode === "service_day") {
    const d = pin.service_day || (pin.service_days || [])[0];
    return PIN_COLOR_BY_DAY[d] || "#64748b";
  }
  if (mode === "crew") {
    return pin.crew_color_hex || "#64748b";
  }
  // tech (default)
  return pin.tech_color_hex
    || techColorById[(pin.assigned_tech_ids || [])[0]]
    || "#0EA5E9";
}
