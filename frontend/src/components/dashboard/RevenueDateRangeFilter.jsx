/**
 * Revenue date-range filter · Feb-2026.
 *
 * Presets: Today · Tomorrow · This Week · Next Week · This Month ·
 * Last Month · This Year · Last Year · Custom Range.  Persists
 * the last selection in localStorage so both revenue tiles
 * remember the range across page loads.
 *
 * Phase P15 · Feb-2026 — the Today + Tomorrow presets now compute
 * their date in the tenant's local timezone (via
 * ``Intl.DateTimeFormat`` with a ``timeZone`` option) so an admin
 * clicking "Today" at 01:30 UTC / 18:30 Phoenix gets the CURRENT
 * Phoenix calendar day, not tomorrow's browser-local day.
 * Week / month / year presets remain browser-local — they're
 * month/year-granularity and the tz drift is negligible.  They're
 * queued for a later phase (see wrap-up "Deferred").
 *
 * The effective tenant tz is resolved from
 * ``useAuth().user?.tenant?.timezone`` with an ``America/Phoenix``
 * fallback (matches the pod-wide P13 default).  A ``tenantTimezone``
 * prop takes precedence for tests + explicit overrides.
 */
import React, { useEffect, useRef, useState } from "react";
import { CalendarRange, ChevronDown } from "lucide-react";
import { colors } from "@/theme";
import { useAuth } from "@/auth";

const LS_KEY = "admin.dashboard.revenue.range.v1";
// Phase P15 · Feb-2026 — must match backend
// ``services.tenant_helpers.DEFAULT_TENANT_TZ`` + the P13 default
// used by the schedule "today" cell.
const TENANT_TZ_FALLBACK = "America/Phoenix";

const PRESETS = [
  { key: "today",       label: "Today" },
  { key: "tomorrow",    label: "Tomorrow" },
  { key: "this_week",   label: "This Week" },
  { key: "next_week",   label: "Next Week" },
  { key: "this_month",  label: "This Month" },
  { key: "last_month",  label: "Last Month" },
  // Phase 34 · Feb-2026 — year-granularity presets. Inserted
  // between Last Month and Custom Range so the dropdown's
  // visual flow stays "narrow → wide" (day → week → month →
  // year → arbitrary). Both ranges resolve browser-local at
  // year granularity — tz drift is immaterial at this
  // precision, same convention as the month presets above.
  { key: "this_year",   label: "This Year" },
  { key: "last_year",   label: "Last Year" },
  { key: "custom",      label: "Custom Range" },
];

function _isoDate(d) {
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Phase P15 · Feb-2026 — the calendar day of ``d`` as seen in
 * ``timeZone``.  Uses the ``en-CA`` locale because it emits
 * unambiguous ``YYYY-MM-DD``-ordered numeric parts regardless of
 * the runtime locale.
 */
export function _isoDateInTz(d, timeZone) {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(d);
    const y = parts.find((p) => p.type === "year")?.value;
    const m = parts.find((p) => p.type === "month")?.value;
    const day = parts.find((p) => p.type === "day")?.value;
    if (y && m && day) return `${y}-${m}-${day}`;
  } catch { /* invalid timeZone — fall through */ }
  return _isoDate(d);
}

/**
 * ``rangeFromPreset`` is exported for the unit test harness. The
 * optional ``opts.tenantTimezone`` argument locks Today + Tomorrow
 * to the tenant's zone. Week / month presets are unchanged.
 */
export function rangeFromPreset(preset, custom, opts) {
  const now = new Date();
  const tz = opts?.tenantTimezone || TENANT_TZ_FALLBACK;
  switch (preset) {
    case "today": {
      const iso = _isoDateInTz(now, tz);
      return { start: iso, end: iso };
    }
    case "tomorrow": {
      // Compute "today in tenant tz" first, then add one calendar
      // day using UTC arithmetic on the parsed ISO parts. This
      // avoids the browser-local ``Date.setDate`` DST landmine
      // while staying tz-correct.
      const todayIso = _isoDateInTz(now, tz);
      const [y, m, d] = todayIso.split("-").map((v) => parseInt(v, 10));
      const dt = new Date(Date.UTC(y, m - 1, d));
      dt.setUTCDate(dt.getUTCDate() + 1);
      const yy = dt.getUTCFullYear();
      const mm = String(dt.getUTCMonth() + 1).padStart(2, "0");
      const dd = String(dt.getUTCDate()).padStart(2, "0");
      const iso = `${yy}-${mm}-${dd}`;
      return { start: iso, end: iso };
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
    case "last_month": {
      // Feb-2026 · "Last Month" = the previous calendar month in
      // browser-local time, symmetric with "This Month" above.
      // ``new Date(y, -1, 1)`` → Dec 1 of the previous year, so the
      // year-rollover case (now = January) is handled by JavaScript
      // Date's month-overflow normalization — no explicit branch
      // required.  ``new Date(y, m, 0)`` picks "day 0 of month m",
      // which Date normalizes to the LAST day of month ``m-1``, so
      // passing ``now.getMonth()`` yields the final day of the
      // previous month.  Month-granularity + browser-local matches
      // the existing This Month convention; the P15 tz lift for
      // month presets stays deferred.
      const s = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      const e = new Date(now.getFullYear(), now.getMonth(), 0);
      return { start: _isoDate(s), end: _isoDate(e) };
    }
    case "this_year": {
      // Phase 34 · Feb-2026 — "This Year" = Jan 1 to Dec 31 of
      // the current browser-local year. Range is inclusive at
      // both ends; Dec 31 is passed as-is to the backend, which
      // applies the local-tz end-of-day semantics to the invoice
      // range filter. Year-granularity matches the Last Month
      // convention — tz drift at the Jan 1 / Dec 31 boundary is
      // acceptable (an invoice landing at Dec 31 23:59 Phoenix /
      // Jan 1 06:59 UTC falls on Dec 31 in either rendering).
      const y = now.getFullYear();
      const s = new Date(y, 0, 1);
      const e = new Date(y, 11, 31);
      return { start: _isoDate(s), end: _isoDate(e) };
    }
    case "last_year": {
      // Phase 34 · Feb-2026 — "Last Year" = Jan 1 to Dec 31 of
      // the previous browser-local year. Same tz semantics as
      // This Year above.
      const y = now.getFullYear() - 1;
      const s = new Date(y, 0, 1);
      const e = new Date(y, 11, 31);
      return { start: _isoDate(s), end: _isoDate(e) };
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

export default function RevenueDateRangeFilter({
  onChange,
  defaultPreset = "this_month",
  tenantTimezone,
}) {
  // Phase P19.2 · Feb-2026 — ``useAuth()`` is called unconditionally
  // at the top of the component body per the React Rules of Hooks.
  // The previous try/catch scaffold was a violation. Auth may not be
  // mounted (some smoke tests render this in isolation), in which
  // case ``useContext`` returns ``null`` and the optional chaining
  // on ``auth`` handles the fall-through — no try/catch needed.
  const auth = useAuth();
  const effectiveTz = tenantTimezone ?? auth?.user?.tenant?.timezone ?? TENANT_TZ_FALLBACK;

  const [preset, setPreset] = useState(() => loadPersisted()?.preset || defaultPreset);
  const [custom, setCustom] = useState(() => loadPersisted()?.custom || {
    start: _isoDate(new Date()), end: _isoDate(new Date()),
  });
  const [customDraft, setCustomDraft] = useState(custom);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  const emit = (p, c) => {
    const range = rangeFromPreset(p, c, { tenantTimezone: effectiveTz });
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({ preset: p, custom: c }));
    } catch { /* ignore */ }
    onChange?.({ preset: p, ...range });
  };

  // Emit initial value once mounted.
  useEffect(() => { emit(preset, custom); }, []); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3 mount-only + explicit param deps

  // Close popover on outside click.
  useEffect(() => {
    const h = (e) => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  // Phase P15 · Feb-2026 — re-emit the current preset when the
  // tenant timezone flips (BusinessSettings dispatches
  // ``tenant:settings-updated``). The persisted preset key is
  // unchanged; only the computed [start, end] shifts.
  useEffect(() => {
    function onTenantSettingsUpdated() { emit(preset, custom); }
    window.addEventListener(
      "tenant:settings-updated", onTenantSettingsUpdated,
    );
    return () => window.removeEventListener(
      "tenant:settings-updated", onTenantSettingsUpdated,
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, custom, effectiveTz]);

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
      <span className="sr-only" data-testid="revenue-tz-badge">{effectiveTz}</span>
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
