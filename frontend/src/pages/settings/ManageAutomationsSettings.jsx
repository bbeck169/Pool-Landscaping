/**
 * LDM-D · Feb-2026 — Manage Automations settings tab.
 *
 * Admin-only sidebar tab in ``SettingsHub``. Four range-bounded
 * sliders map 1-to-1 onto the ``settings.automation_rules``
 * sub-document introduced by LDM-A:
 *
 *   dispatch_delay_threshold_mins  (1–240 min,   default 20)
 *   dispatch_sms_customer_count    (1–10,        default 3)
 *   filter_clean_interval_months   (1–24 months, default 6)
 *   salt_cell_replacement_months   (12–120,      default 36)
 *
 * Read: ``GET /api/tenants/mine/automation-rules``
 * Write: ``PATCH /api/tenants/mine/automation-rules``
 *
 * Both endpoints derive ``tenant_id`` from the caller's JWT — this
 * component never sends a body ``tenant_id`` (LDM-A rejection at
 * the API boundary is 403). Role gate is enforced at the route
 * level by <AdminOnly>; this component also renders a friendly
 * "admin required" card if a non-admin reaches it directly.
 *
 * Behaviour rulings from LDM-D:
 *   * Auto-save with a 500 ms debounce on any slider/input change.
 *     Two rapid nudges coalesce into a single PATCH.
 *   * Save indicator: "Saving…" → "Saved ✓". Failure surfaces a
 *     retrying banner and attempts one auto-retry before flipping
 *     to a persistent error state; local state is preserved.
 *   * Slider + number input hybrid — typing into the input clamps
 *     to the field's [min, max] and updates the slider instantly.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Zap, Clock, Users, Filter, Waves } from "lucide-react";
import { Slider } from "@/components/ui/slider";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";


// ─────────────────────────────────────────────────────────────────
// Field descriptors. Kept declarative so the four rows render from
// a single map + so tests can iterate the same source of truth.
// ─────────────────────────────────────────────────────────────────
const FIELDS = [
  {
    key: "dispatch_delay_threshold_mins",
    label: "Dispatch Delay Threshold",
    hint: "Notify customers when techs are running late by more than N minutes.",
    unit: "min",
    min: 1,
    max: 240,
    default: 20,
    Icon: Clock,
    // data-testid suffixes
    slider_testid: "automation-slider-dispatch-delay",
    input_testid: "automation-input-dispatch-delay",
    row_testid: "automation-row-dispatch-delay",
  },
  {
    key: "dispatch_sms_customer_count",
    label: "SMS Notification Count",
    hint: "Notify the next N customers on the route when a delay is detected.",
    unit: "customers",
    min: 1,
    max: 10,
    default: 3,
    Icon: Users,
    slider_testid: "automation-slider-sms-count",
    input_testid: "automation-input-sms-count",
    row_testid: "automation-row-sms-count",
  },
  {
    key: "filter_clean_interval_months",
    label: "Filter Cleaning Interval",
    hint: "Flag customers as due for filter cleaning after N months.",
    unit: "months",
    min: 1,
    max: 24,
    default: 6,
    Icon: Filter,
    slider_testid: "automation-slider-filter-interval",
    input_testid: "automation-input-filter-interval",
    row_testid: "automation-row-filter-interval",
  },
  {
    key: "salt_cell_replacement_months",
    label: "Salt Cell Replacement Interval",
    hint: "Flag customers as due for salt cell replacement after N months.",
    unit: "months",
    min: 12,
    max: 120,
    default: 36,
    Icon: Waves,
    slider_testid: "automation-slider-salt-interval",
    input_testid: "automation-input-salt-interval",
    row_testid: "automation-row-salt-interval",
  },
];

const DEFAULT_VALUES = FIELDS.reduce(
  (acc, f) => ({ ...acc, [f.key]: f.default }),
  {},
);

// Section-header navy per LDM-D palette ruling. Kept as inline
// literals so the codebase-wide ``colors.brand`` (sky-blue #0284C7)
// isn't overridden anywhere else on the settings surface.
const NAVY = "#1B1F5C";

const DEBOUNCE_MS = 500;


// ─────────────────────────────────────────────────────────────────
// Utility: clamp ``v`` to [min, max]. Returns the field default
// when ``v`` isn't a finite number (empty input, garbage paste, etc.)
// so the slider never lands on NaN.
// ─────────────────────────────────────────────────────────────────
function clamp(v, min, max, fallback) {
  const n = Number(v);
  if (!Number.isFinite(n)) return fallback;
  if (n < min) return min;
  if (n > max) return max;
  return Math.round(n);
}


export default function ManageAutomationsSettings() {
  const { user } = useAuth() || {};
  const roleLc = (user?.role || "").toLowerCase();
  const isAdmin = roleLc === "admin" || roleLc === "super_admin";

  // ── Local state ────────────────────────────────────────────────
  //  ``values``   — the current in-memory field values (drives UI).
  //  ``loadErr``  — non-empty when the initial GET failed.
  //  ``loaded``   — flips true after the first successful GET.
  //  ``saveStatus`` — 'idle' | 'saving' | 'saved' | 'retrying' | 'error'
  const [values, setValues] = useState(DEFAULT_VALUES);
  const [loadErr, setLoadErr] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [saveStatus, setSaveStatus] = useState("idle");
  const [saveErr, setSaveErr] = useState("");

  // Debounce timer + pending payload — collapsed into refs so the
  // 500 ms coalesce doesn't tear across renders. The "pending diff"
  // ref accumulates every field the user has touched since the last
  // successful save; on flush we PATCH those keys together.
  const timerRef = useRef(null);
  const pendingRef = useRef({});
  const retriedRef = useRef(false);

  // ── Initial load ────────────────────────────────────────────────
  const load = useCallback(async () => {
    try {
      const r = await api.get("/tenants/mine/automation-rules");
      const next = { ...DEFAULT_VALUES };
      for (const f of FIELDS) {
        if (r && typeof r[f.key] === "number") {
          next[f.key] = clamp(r[f.key], f.min, f.max, f.default);
        }
      }
      setValues(next);
      setLoaded(true);
      setLoadErr("");
    } catch (e) {
      setLoadErr(
        e?.message
          || "Could not load automation settings — refresh to retry",
      );
    }
  }, []);

  useEffect(() => {
    if (isAdmin) load();
  }, [isAdmin, load]);

  // ── PATCH flush ─────────────────────────────────────────────────
  //  Sends only the keys in ``pendingRef``. On success clears the
  //  buffer + shows "Saved". On failure attempts one retry, then
  //  flips to the persistent error state without reverting local
  //  values (per LDM-D ruling #6 — don't yank the slider back on
  //  transient network hiccups).
  const flush = useCallback(async () => {
    const payload = { ...pendingRef.current };
    if (Object.keys(payload).length === 0) return;
    setSaveStatus("saving");
    setSaveErr("");
    try {
      await api.patch("/tenants/mine/automation-rules", payload);
      pendingRef.current = {};
      retriedRef.current = false;
      setSaveStatus("saved");
      // Auto-fade "Saved ✓" back to idle after 2 s so the pill
      // doesn't stay pinned indefinitely.
      setTimeout(() => {
        setSaveStatus((s) => (s === "saved" ? "idle" : s));
      }, 2000);
    } catch (e) {
      const msg = e?.message || "Save failed";
      if (!retriedRef.current) {
        // Auto-retry once — banner shows "retrying".
        retriedRef.current = true;
        setSaveStatus("retrying");
        setSaveErr(msg);
        setTimeout(() => { flush(); }, 800);
      } else {
        setSaveStatus("error");
        setSaveErr(msg);
      }
    }
  }, []);

  // Local-state mutator — used by both slider + input.
  const updateField = useCallback((field, raw) => {
    const clamped = clamp(raw, field.min, field.max, field.default);
    setValues((prev) => {
      if (prev[field.key] === clamped) return prev;
      const next = { ...prev, [field.key]: clamped };
      // Queue the PATCH — merged into pendingRef so a burst of
      // slider drags all coalesces into one request.
      pendingRef.current = { ...pendingRef.current, [field.key]: clamped };
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        flush();
      }, DEBOUNCE_MS);
      return next;
    });
  }, [flush]);

  // Clean up any pending timer on unmount to prevent an in-flight
  // PATCH from firing after navigation away.
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  // ── Renderers ───────────────────────────────────────────────────
  if (!isAdmin) {
    return (
      <div
        className="rounded-2xl p-6"
        style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="automations-forbidden"
      >
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
          Admin access required
        </div>
        <div className="text-xs mt-1" style={{ color: colors.muted }}>
          Only admins can view or change automation rules.
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded-2xl p-5 space-y-5"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="automations-tab"
    >
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2
            className="text-lg font-semibold flex items-center gap-2"
            style={{ color: NAVY }}
            data-testid="automations-title"
          >
            <Zap size={18} style={{ color: NAVY }} />
            Manage Automations
          </h2>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Tune the thresholds that drive the AI Live Dispatcher +
            Predictive Maintenance Scanner. Changes save automatically.
          </p>
        </div>
        <SaveIndicator status={saveStatus} errMessage={saveErr} />
      </header>

      {loadErr ? (
        <div
          className="rounded-lg px-3 py-2 text-sm"
          style={{
            background: "#FEF2F2",
            color: "#991B1B",
            border: "1px solid #FECACA",
          }}
          data-testid="automation-error-banner"
        >
          {loadErr}
        </div>
      ) : null}

      {!loaded && !loadErr ? (
        <AutomationsSkeleton />
      ) : null}

      {loaded ? (
        <div className="space-y-4" data-testid="automations-fields">
          {FIELDS.map((field) => (
            <AutomationRow
              key={field.key}
              field={field}
              value={values[field.key]}
              onChange={(v) => updateField(field, v)}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────
// One row: label + hint + slider + numeric input side-by-side.
// ─────────────────────────────────────────────────────────────────
function AutomationRow({ field, value, onChange }) {
  const { Icon } = field;
  return (
    <div
      className="rounded-xl p-3"
      style={{ border: `1px solid ${colors.border}`,
                background: colors.surfaceSecondary }}
      data-testid={field.row_testid}
    >
      <div className="flex items-start gap-3">
        <Icon size={18} style={{ color: NAVY, marginTop: 2 }} />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            {field.label}
          </div>
          <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
            {field.hint}
          </div>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-4">
        <div className="flex-1">
          <Slider
            value={[value]}
            min={field.min}
            max={field.max}
            step={1}
            onValueChange={(vv) => onChange(vv?.[0])}
            data-testid={field.slider_testid}
            aria-label={field.label}
          />
          <div
            className="mt-1 flex justify-between text-[10px]"
            style={{ color: colors.muted }}
          >
            <span>{field.min}</span>
            <span>{field.max}</span>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <input
            type="number"
            className="w-20 rounded-md px-2 py-1 text-sm text-right outline-none"
            style={{
              border: `1px solid ${colors.border}`,
              background: colors.surface,
              color: colors.onSurface,
            }}
            value={value}
            min={field.min}
            max={field.max}
            step={1}
            onChange={(e) => onChange(e.target.value)}
            onBlur={(e) => onChange(e.target.value)}
            data-testid={field.input_testid}
            aria-label={`${field.label} value`}
          />
          <span
            className="text-xs"
            style={{ color: colors.muted }}
            data-testid={`${field.input_testid}-unit`}
          >
            {field.unit}
          </span>
        </div>
      </div>
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────
// Save-status pill. Colours + copy shift with the state machine.
// ─────────────────────────────────────────────────────────────────
function SaveIndicator({ status, errMessage }) {
  if (status === "saving") {
    return (
      <span
        className="text-xs px-2 py-1 rounded-md"
        style={{ background: "#EFF6FF", color: "#1D4ED8", border: "1px solid #BFDBFE" }}
        data-testid="automation-saving-indicator"
      >
        Saving…
      </span>
    );
  }
  if (status === "saved") {
    return (
      <span
        className="text-xs px-2 py-1 rounded-md"
        style={{ background: "#ECFDF5", color: "#047857", border: "1px solid #A7F3D0" }}
        data-testid="automation-saved-indicator"
      >
        Saved ✓
      </span>
    );
  }
  if (status === "retrying") {
    return (
      <span
        className="text-xs px-2 py-1 rounded-md"
        style={{ background: "#FFFBEB", color: "#B45309", border: "1px solid #FDE68A" }}
        data-testid="automation-retrying-indicator"
        title={errMessage || ""}
      >
        Save failed — retrying…
      </span>
    );
  }
  if (status === "error") {
    return (
      <span
        className="text-xs px-2 py-1 rounded-md"
        style={{ background: "#FEF2F2", color: "#991B1B", border: "1px solid #FECACA" }}
        data-testid="automation-save-error-indicator"
        title={errMessage || ""}
      >
        Save failed
      </span>
    );
  }
  return null;
}


// ─────────────────────────────────────────────────────────────────
// Skeleton shown while the initial GET is in flight.
// ─────────────────────────────────────────────────────────────────
function AutomationsSkeleton() {
  return (
    <div className="space-y-3" data-testid="automations-skeleton">
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="rounded-xl p-3"
          style={{ border: `1px solid ${colors.border}` }}
        >
          <div
            className="h-3 rounded"
            style={{ background: colors.surfaceTertiary, width: "45%" }}
          />
          <div
            className="mt-2 h-2 rounded"
            style={{ background: colors.surfaceTertiary, width: "80%" }}
          />
          <div
            className="mt-4 h-2 rounded"
            style={{ background: colors.surfaceTertiary, width: "100%" }}
          />
        </div>
      ))}
    </div>
  );
}
