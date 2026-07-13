import React from "react";
import { useSearchParams } from "react-router-dom";
import { Calendar as CalendarIcon, ChevronDown } from "lucide-react";
import { colors } from "@/theme";

// Returns [start, end] as YYYY-MM-DD strings for a named preset.
export function presetRange(preset) {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  const iso = (d) => d.toISOString().slice(0, 10);
  if (preset === "this-month") {
    return [iso(new Date(y, m, 1)), iso(new Date(y, m + 1, 0))];
  }
  if (preset === "last-month") {
    return [iso(new Date(y, m - 1, 1)), iso(new Date(y, m, 0))];
  }
  if (preset === "this-quarter") {
    const q = Math.floor(m / 3);
    return [iso(new Date(y, q * 3, 1)), iso(new Date(y, q * 3 + 3, 0))];
  }
  if (preset === "ytd") {
    return [iso(new Date(y, 0, 1)), iso(now)];
  }
  if (preset === "last-90-days") {
    const from = new Date();
    from.setDate(from.getDate() - 90);
    return [iso(from), iso(now)];
  }
  return ["", ""];
}

const PRESETS = [
  { key: "this-month", label: "This month" },
  { key: "last-month", label: "Last month" },
  { key: "this-quarter", label: "This quarter" },
  { key: "ytd", label: "YTD" },
  { key: "last-90-days", label: "Last 90 days" },
  { key: "custom", label: "Custom" },
];

/**
 * DateRangePicker — presets + custom, keeps `start` and `end` in the URL query
 * so filters persist and are shareable. Emits change via onChange({start,end}).
 */
export default function DateRangePicker({ defaultPreset = "this-month", onChange, testId = "date-range-picker" }) {
  const [params, setParams] = useSearchParams();
  const start = params.get("start") || "";
  const end = params.get("end") || "";
  const [open, setOpen] = React.useState(false);
  const [current, setCurrent] = React.useState(params.get("preset") || defaultPreset);

  // Sync a preset to the URL on first render if nothing is set yet.
  React.useEffect(() => {
    if (!start && !end) {
      const [s, e] = presetRange(defaultPreset);
      const next = new URLSearchParams(params);
      next.set("start", s);
      next.set("end", e);
      next.set("preset", defaultPreset);
      setParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (onChange) onChange({ start, end });
  }, [start, end]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyPreset = (key) => {
    setCurrent(key);
    if (key === "custom") {
      setOpen(true);
      const next = new URLSearchParams(params);
      next.set("preset", "custom");
      setParams(next, { replace: true });
      return;
    }
    const [s, e] = presetRange(key);
    const next = new URLSearchParams(params);
    next.set("start", s);
    next.set("end", e);
    next.set("preset", key);
    setParams(next, { replace: true });
    setOpen(false);
  };

  const updateCustom = (field, value) => {
    const next = new URLSearchParams(params);
    next.set(field, value);
    next.set("preset", "custom");
    setParams(next, { replace: true });
    setCurrent("custom");
  };

  const label = PRESETS.find((p) => p.key === current)?.label || "This month";

  return (
    <div className="relative" data-testid={testId}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-semibold transition hover:brightness-95"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
          color: colors.onSurface,
        }}
        data-testid={`${testId}-toggle`}
      >
        <CalendarIcon size={16} style={{ color: colors.brand }} />
        <span>{label}</span>
        <span className="text-xs" style={{ color: colors.muted }}>
          {start} → {end}
        </span>
        <ChevronDown size={14} style={{ color: colors.muted }} />
      </button>
      {open ? (
        <div
          className="absolute right-0 mt-2 rounded-2xl shadow-lg z-30 p-4"
          style={{
            width: 320,
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid={`${testId}-panel`}
        >
          <div className="grid grid-cols-2 gap-2 mb-3">
            {PRESETS.map((p) => (
              <button
                key={p.key}
                onClick={() => applyPreset(p.key)}
                className="text-left px-3 py-2 rounded-lg text-xs font-semibold transition hover:brightness-95"
                style={{
                  backgroundColor: current === p.key ? colors.brandTertiary : colors.surfaceSecondary,
                  color: current === p.key ? colors.onBrandTertiary : colors.onSurface,
                }}
                data-testid={`${testId}-preset-${p.key}`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs font-semibold" style={{ color: colors.muted }}>
              Start
              <input
                type="date"
                value={start}
                onChange={(e) => updateCustom("start", e.target.value)}
                className="w-full mt-1 px-2 py-1.5 rounded-lg text-sm"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  border: `1px solid ${colors.border}`,
                  color: colors.onSurface,
                }}
                data-testid={`${testId}-start`}
              />
            </label>
            <label className="text-xs font-semibold" style={{ color: colors.muted }}>
              End
              <input
                type="date"
                value={end}
                onChange={(e) => updateCustom("end", e.target.value)}
                className="w-full mt-1 px-2 py-1.5 rounded-lg text-sm"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  border: `1px solid ${colors.border}`,
                  color: colors.onSurface,
                }}
                data-testid={`${testId}-end`}
              />
            </label>
          </div>
          <div className="mt-3 text-right">
            <button
              onClick={() => setOpen(false)}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid={`${testId}-apply`}
            >
              Done
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// Helper hook other pages can use to read the current window.
export function useDateRange(defaultPreset = "this-month") {
  const [params] = useSearchParams();
  const start = params.get("start") || presetRange(defaultPreset)[0];
  const end = params.get("end") || presetRange(defaultPreset)[1];
  return { start, end };
}
