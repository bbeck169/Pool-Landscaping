/**
 * Revenue date-range filter · Feb-2026.
 *
 * Presets: Today · Tomorrow · This Week · Next Week · This Month ·
 * Custom Range.  Persists the last selection in localStorage so both
 * revenue tiles remember the range across page loads.
 */
import React, { useEffect, useRef, useState } from "react";
import { CalendarRange, ChevronDown } from "lucide-react";
import { colors } from "@/theme";

const LS_KEY = "admin.dashboard.revenue.range.v1";

const PRESETS = [
  { key: "today",       label: "Today" },
  { key: "tomorrow",    label: "Tomorrow" },
  { key: "this_week",   label: "This Week" },
  { key: "next_week",   label: "Next Week" },
  { key: "this_month",  label: "This Month" },
  { key: "custom",      label: "Custom Range" },
];

function _startOfDay(d) {
  const x = new Date(d); x.setHours(0, 0, 0, 0); return x;
}
function _endOfDay(d) {
  const x = new Date(d); x.setHours(23, 59, 59, 999); return x;
}
function _isoDate(d) {
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function rangeFromPreset(preset, custom) {
  const now = new Date();
  switch (preset) {
    case "today": {
      return { start: _isoDate(now), end: _isoDate(now) };
    }
    case "tomorrow": {
      const t = new Date(now); t.setDate(t.getDate() + 1);
      return { start: _isoDate(t), end: _isoDate(t) };
    }
    case "this_week": {
      const s = new Date(now); s.setDate(now.getDate() - ((now.getDay() + 6) % 7));
      const e = new Date(s); e.setDate(s.getDate() + 6);
      return { start: _isoDate(s), end: _isoDate(e) };
    }
    case "next_week": {
      const s = new Date(now); s.setDate(now.getDate() - ((now.getDay() + 6) % 7) + 7);
      const e = new Date(s); e.setDate(s.getDate() + 6);
      return { start: _isoDate(s), end: _isoDate(e) };
    }
    case "custom": {
      return { start: custom?.start || _isoDate(now),
                end: custom?.end || _isoDate(now) };
    }
    case "this_month":
    default: {
      const s = new Date(now.getFullYear(), now.getMonth(), 1);
      const e = new Date(now.getFullYear(), now.getMonth() + 1, 0);
      return { start: _isoDate(s), end: _isoDate(e) };
    }
  }
}

function loadPersisted() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && parsed.preset) return parsed;
  } catch { /* ignore */ }
  return null;
}

export default function RevenueDateRangeFilter({ onChange, defaultPreset = "this_month" }) {
  const [preset, setPreset] = useState(() => loadPersisted()?.preset || defaultPreset);
  const [custom, setCustom] = useState(() => loadPersisted()?.custom || {
    start: _isoDate(new Date()), end: _isoDate(new Date()),
  });
  const [customDraft, setCustomDraft] = useState(custom);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  const emit = (p, c) => {
    const range = rangeFromPreset(p, c);
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({ preset: p, custom: c }));
    } catch { /* ignore */ }
    onChange?.({ preset: p, ...range });
  };

  // Emit initial value once mounted.
  useEffect(() => { emit(preset, custom); /* eslint-disable-next-line */ }, []);

  // Close popover on outside click.
  useEffect(() => {
    const h = (e) => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const currentLabel = PRESETS.find((p) => p.key === preset)?.label || "Range";

  const pickPreset = (k) => {
    setPreset(k);
    if (k !== "custom") {
      setOpen(false);
      emit(k, custom);
    }
  };

  const applyCustom = () => {
    setCustom(customDraft);
    setOpen(false);
    emit("custom", customDraft);
  };

  return (
    <div className="relative inline-block" ref={wrapRef}
          data-testid="revenue-range-filter">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold"
        style={{ background: colors.surface,
                  border: `1px solid ${colors.border}`,
                  color: colors.onSurface }}
        data-testid="revenue-range-toggle"
      >
        <CalendarRange size={14} />
        {currentLabel}
        {preset === "custom" ? (
          <span className="text-xs opacity-70" data-testid="revenue-range-custom-summary">
            {custom.start} → {custom.end}
          </span>
        ) : null}
        <ChevronDown size={14} />
      </button>

      {open ? (
        <div
          className="absolute right-0 mt-2 rounded-2xl p-3 z-50 min-w-[240px]"
          style={{ background: colors.surface,
                    border: `1px solid ${colors.border}`,
                    boxShadow: "0 8px 24px rgba(0,0,0,0.10)" }}
          data-testid="revenue-range-popover"
        >
          <div className="flex flex-col gap-1 mb-2">
            {PRESETS.map((p) => (
              <button
                key={p.key}
                onClick={() => pickPreset(p.key)}
                className="text-left px-3 py-1.5 rounded-lg text-sm"
                style={{
                  background: preset === p.key ? colors.brandTertiary : "transparent",
                  color: preset === p.key ? colors.brand : colors.onSurface,
                  fontWeight: preset === p.key ? 700 : 500,
                }}
                data-testid={`revenue-range-preset-${p.key}`}
              >{p.label}</button>
            ))}
          </div>
          {preset === "custom" ? (
            <div className="border-t pt-3 mt-1 space-y-2"
                  style={{ borderColor: colors.border }}>
              <label className="text-xs block" style={{ color: colors.muted }}>Start</label>
              <input
                type="date"
                value={customDraft.start}
                onChange={(e) => setCustomDraft((d) => ({ ...d, start: e.target.value }))}
                className="w-full px-2 py-1 rounded-lg text-sm"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="revenue-range-custom-start"
              />
              <label className="text-xs block" style={{ color: colors.muted }}>End</label>
              <input
                type="date"
                value={customDraft.end}
                onChange={(e) => setCustomDraft((d) => ({ ...d, end: e.target.value }))}
                className="w-full px-2 py-1 rounded-lg text-sm"
                style={{ background: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="revenue-range-custom-end"
              />
              <button
                onClick={applyCustom}
                className="w-full rounded-full py-1.5 text-sm font-semibold"
                style={{ background: colors.brand, color: "#fff" }}
                data-testid="revenue-range-custom-apply"
              >Apply</button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
