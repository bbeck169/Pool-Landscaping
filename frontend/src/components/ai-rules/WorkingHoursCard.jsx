/**
 * MTH-B · Feb-2026 — Working Hours card.
 *
 * "Restrict AI actions to working hours" master toggle + timezone
 * selector + 7 day rows with start/end pickers.  Multiple windows
 * per day supported (backend caps at 21 total = 3/day · 7 days).
 * Preview strip: "Right now: <status>" using the tenant's tz.
 *
 * The tenant's currently-selected timezone is passed through the
 * existing ``TimezoneSelect`` picker (P15) so we don't reinvent
 * the IANA-vs-legacy handling.
 */
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { RotateCcw, Save, Clock, Plus, Trash2 } from "lucide-react";
import { api } from "@/api";
import { Button, Chip } from "@/components/ui-kit";
import { TimezoneSelect } from "@/components/settings/TimezoneSelect";
import RulesReasonModal from "./RulesReasonModal";
import OverrideDiff from "./OverrideDiff";

const DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_LABELS = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};

/** JS weekday index (0=Sun) → 3-letter key. */
const JS_DAY_TO_KEY = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

function normalizeWindows(windows) {
  if (!Array.isArray(windows)) return [];
  return windows
    .filter((w) => w && DAY_KEYS.includes(w.day))
    .map((w) => ({
      day: w.day,
      start: w.start || "08:00",
      end: w.end || "17:00",
    }));
}

function byDay(windows) {
  const map = new Map();
  DAY_KEYS.forEach((d) => map.set(d, []));
  windows.forEach((w) => {
    if (map.has(w.day)) map.get(w.day).push({ start: w.start, end: w.end });
  });
  return map;
}

function flatWindows(map) {
  const out = [];
  DAY_KEYS.forEach((d) => {
    (map.get(d) || []).forEach((w) => {
      out.push({ day: d, start: w.start, end: w.end });
    });
  });
  return out;
}

/**
 * Determine whether ``now`` falls inside any window for its
 * weekday in the tenant timezone.  Uses Intl.DateTimeFormat with
 * the ``timeZone`` option so we don't depend on the browser tz.
 */
export function isInsideWindow(now, timezone, windows) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const partMap = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  // ``weekday`` is like "Sun", "Mon" — map to lowercase 3-letter key.
  const dayKey = String(partMap.weekday || "").slice(0, 3).toLowerCase();
  const hh = partMap.hour === "24" ? "00" : partMap.hour;
  const mm = partMap.minute;
  const cur = `${hh}:${mm}`;
  const dayWindows = (windows || []).filter((w) => w.day === dayKey);
  const inside = dayWindows.some((w) => cur >= w.start && cur < w.end);
  return {
    inside,
    dayKey,
    time: cur,
    display: `${partMap.weekday} ${cur} in ${timezone}`,
  };
}

export default function WorkingHoursCard({
  value,
  overrideMap,
  platformValue,
  onSaved,
  onReset,
  readOnly = false,
  nowRef,
  endpointPrefix = "/tenant-ai-rules",
  showReset = true,
  showDiff = true,
}) {
  const [enabled, setEnabled] = useState(
    value?.enabled === undefined ? true : Boolean(value.enabled),
  );
  const [tz, setTz] = useState(value?.timezone || "America/Los_Angeles");
  const [windowsMap, setWindowsMap] = useState(() =>
    byDay(normalizeWindows(value?.windows)),
  );
  const [saveOpen, setSaveOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);

  React.useEffect(() => {
    setEnabled(value?.enabled === undefined ? true : Boolean(value.enabled));
    setTz(value?.timezone || "America/Los_Angeles");
    setWindowsMap(byDay(normalizeWindows(value?.windows)));
  }, [value]);

  const flat = useMemo(() => flatWindows(windowsMap), [windowsMap]);

  const isOverridden = useMemo(() => {
    if (!overrideMap) return false;
    return ["enabled", "timezone", "windows"].some(
      (k) => overrideMap[`working_hours.${k}`] === "tenant",
    );
  }, [overrideMap]);
  const overrideCount = ["enabled", "timezone", "windows"].filter(
    (k) => overrideMap?.[`working_hours.${k}`] === "tenant",
  ).length;

  const preview = useMemo(() => {
    const now = nowRef || new Date();
    try {
      const res = isInsideWindow(now, tz, flat);
      return {
        display: res.display,
        inside: res.inside,
      };
    } catch (e) {
      return { display: "unknown", inside: false };
    }
  }, [tz, flat, nowRef]);

  // MTH-D · Feb-2026 — server-driven live preview.  Debounced 500 ms
  // on any edit so we don't rain requests on the LLM-free preview
  // endpoint while the operator is typing.  Falls back to the
  // client-computed strip above if the fetch fails or is disabled.
  const [serverPreview, setServerPreview] = useState(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [probeDatetime, setProbeDatetime] = useState("");

  useEffect(() => {
    if (readOnly) return undefined;
    let alive = true;
    const timer = setTimeout(async () => {
      setPreviewBusy(true);
      try {
        const res = await api.post("/tenant-ai-rules/preview", {
          category: "working_hours",
          pending_value: {
            enabled,
            timezone: tz,
            windows: flat,
          },
          preview_kind: "working_hours_status",
          preview_input: probeDatetime
            ? { probe_datetime: probeDatetime }
            : {},
        });
        if (alive) setServerPreview(res);
      } catch (e) {
        if (alive) setServerPreview(null);
      } finally {
        if (alive) setPreviewBusy(false);
      }
    }, 500);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, tz, flat, probeDatetime, readOnly]);

  const setDayEntry = (day, idx, field, val) => {
    setWindowsMap((prev) => {
      const next = new Map(prev);
      const list = [...(next.get(day) || [])];
      list[idx] = { ...list[idx], [field]: val };
      next.set(day, list);
      return next;
    });
  };
  const addWindow = (day) => {
    setWindowsMap((prev) => {
      const next = new Map(prev);
      const list = [...(next.get(day) || [])];
      list.push({ start: "08:00", end: "17:00" });
      next.set(day, list);
      return next;
    });
  };
  const removeWindow = (day, idx) => {
    setWindowsMap((prev) => {
      const next = new Map(prev);
      const list = [...(next.get(day) || [])];
      list.splice(idx, 1);
      next.set(day, list);
      return next;
    });
  };

  const doSave = async (reason) => {
    try {
      await api.put(`${endpointPrefix}/working_hours`, {
        value: {
          enabled,
          timezone: tz,
          windows: flat,
        },
        reason,
      });
      toast.success("Working hours saved.");
      setSaveOpen(false);
      if (onSaved) await onSaved();
    } catch (e) {
      toast.error(
        `Save failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    }
  };

  const doReset = async (reason) => {
    try {
      await api.post(`${endpointPrefix}/reset/working_hours`, { reason });
      toast.success("Working hours reset to platform default.");
      setResetOpen(false);
      if (onReset) await onReset();
    } catch (e) {
      toast.error(
        `Reset failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    }
  };

  return (
    <div
      className="rounded-2xl bg-white border p-5 space-y-4"
      style={{ borderColor: "#E2E8F0" }}
      data-testid="ai-rules-working-hours-card"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: "#E0F2FE", color: "#0369A1" }}
          >
            <Clock size={16} />
          </div>
          <div>
            <div className="text-sm font-bold">Working Hours</div>
            <div className="text-xs opacity-60">
              Restrict every AI-initiated action to the windows below.
            </div>
          </div>
        </div>
        {isOverridden ? (
          <Chip
            label={`${overrideCount} tenant override${overrideCount === 1 ? "" : "s"}`}
            tone="brand"
            testid="ai-rules-working-hours-override-pill"
          />
        ) : null}
      </div>

      <OverrideDiff
        category="working_hours"
        overrideMap={overrideMap}
        tenantValue={value}
        platformValue={platformValue}
        testid="ai-rules-working-hours-diff"
        readOnly={!showDiff}
      />

      <div className="flex items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          onClick={() => setEnabled((v) => !v)}
          disabled={readOnly}
          className="relative inline-flex items-center rounded-full transition-colors"
          style={{
            width: 44,
            height: 24,
            background: enabled ? "#166534" : "#94A3B8",
          }}
          data-testid="ai-rules-working-hours-enabled"
        >
          <span
            className="inline-block rounded-full bg-white shadow transition-transform"
            style={{
              width: 18,
              height: 18,
              transform: enabled ? "translateX(22px)" : "translateX(4px)",
            }}
          />
        </button>
        <div>
          <div className="text-sm font-semibold">
            Restrict AI actions to working hours
          </div>
          <div className="text-xs opacity-60">
            When off, AI employees may act at any hour.
          </div>
        </div>
      </div>

      <TimezoneSelect
        value={tz}
        onChange={(next) => setTz(next)}
        label="Timezone"
        testid="ai-rules-working-hours-timezone"
        disabled={readOnly}
      />

      <div
        className="rounded-lg border overflow-hidden"
        style={{ borderColor: "#E2E8F0" }}
      >
        {DAY_KEYS.map((d, idx) => {
          const list = windowsMap.get(d) || [];
          const dayEnabled = list.length > 0;
          return (
            <div
              key={d}
              className="px-3 py-2 space-y-2"
              style={{
                borderTop: idx === 0 ? "none" : "1px solid #F1F5F9",
                background: dayEnabled ? "#FFFFFF" : "#F8FAFC",
              }}
              data-testid={`ai-rules-working-hours-day-${d}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold w-10">
                    {DAY_LABELS[d]}
                  </span>
                  {!dayEnabled ? (
                    <span
                      className="text-[11px] opacity-60"
                      data-testid={`ai-rules-working-hours-day-${d}-off`}
                    >
                      Closed
                    </span>
                  ) : null}
                </div>
                <button
                  type="button"
                  onClick={() => addWindow(d)}
                  disabled={readOnly || list.length >= 3}
                  className="text-xs font-semibold inline-flex items-center gap-1 px-2 py-1 rounded-md"
                  style={{
                    background: "#E0F2FE",
                    color: "#0369A1",
                    opacity: list.length >= 3 ? 0.5 : 1,
                  }}
                  data-testid={`ai-rules-working-hours-day-${d}-add`}
                >
                  <Plus size={12} /> Add window
                </button>
              </div>
              {list.length > 0 ? (
                <div className="space-y-1">
                  {list.map((w, wi) => (
                    <div
                      key={wi}
                      className="flex items-center gap-2"
                      data-testid={`ai-rules-working-hours-day-${d}-window-${wi}`}
                    >
                      <input
                        type="time"
                        value={w.start}
                        onChange={(e) =>
                          setDayEntry(d, wi, "start", e.target.value)
                        }
                        disabled={readOnly}
                        className="px-2 py-1 rounded-md border text-sm"
                        style={{ borderColor: "#E2E8F0" }}
                        data-testid={`ai-rules-working-hours-day-${d}-window-${wi}-start`}
                      />
                      <span className="text-xs opacity-60">→</span>
                      <input
                        type="time"
                        value={w.end}
                        onChange={(e) =>
                          setDayEntry(d, wi, "end", e.target.value)
                        }
                        disabled={readOnly}
                        className="px-2 py-1 rounded-md border text-sm"
                        style={{ borderColor: "#E2E8F0" }}
                        data-testid={`ai-rules-working-hours-day-${d}-window-${wi}-end`}
                      />
                      <button
                        type="button"
                        onClick={() => removeWindow(d, wi)}
                        disabled={readOnly}
                        className="text-xs opacity-70 hover:opacity-100"
                        data-testid={`ai-rules-working-hours-day-${d}-window-${wi}-remove`}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      <div
        className="rounded-lg p-3 text-sm"
        style={{
          background: (serverPreview?.output?.inside_window ?? preview.inside)
            ? "#DCFCE7"
            : "#FEF3C7",
          color: (serverPreview?.output?.inside_window ?? preview.inside)
            ? "#166534"
            : "#92400E",
          border: `1px solid ${
            (serverPreview?.output?.inside_window ?? preview.inside)
              ? "#BBF7D0"
              : "#FDE68A"
          }`,
        }}
        data-testid="ai-rules-working-hours-preview"
      >
        <div className="text-xs font-bold mb-0.5 flex items-center justify-between">
          <span>RIGHT NOW {previewBusy ? "· updating…" : ""}</span>
          <label className="text-[10px] opacity-70 font-normal">
            Probe:{" "}
            <input
              type="datetime-local"
              value={probeDatetime}
              onChange={(e) => setProbeDatetime(e.target.value)}
              className="ml-1 px-1 py-0.5 rounded border text-xs"
              style={{ borderColor: "#E2E8F0", color: "#334155",
                        background: "#fff" }}
              data-testid="ai-rules-working-hours-preview-probe"
            />
          </label>
        </div>
        {serverPreview?.output?.summary ? (
          <div data-testid="ai-rules-working-hours-preview-summary">
            {serverPreview.output.summary}
          </div>
        ) : (
          <div>
            {preview.display} —{" "}
            <strong data-testid="ai-rules-working-hours-preview-status">
              {preview.inside ? "inside window" : "outside window"}
            </strong>
          </div>
        )}
        {serverPreview?.output?.inside_window !== undefined ? (
          <div className="mt-1 text-[10px] opacity-60">
            server-verified · tz {serverPreview.output.timezone_used}
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2">
        {showReset ? (
          <Button
            variant="ghost"
            onClick={() => setResetOpen(true)}
            disabled={readOnly}
            testid="ai-rules-working-hours-reset"
          >
            <RotateCcw size={14} /> Reset to Platform Default
          </Button>
        ) : null}
        <Button
          variant="primary"
          onClick={() => setSaveOpen(true)}
          disabled={readOnly}
          testid="ai-rules-working-hours-save"
        >
          <Save size={14} /> Save
        </Button>
      </div>

      <RulesReasonModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        title="Save Working Hours"
        description="AI employees will only act inside the windows below (tenant tz)."
        onConfirm={doSave}
        confirmLabel="Save Hours"
        testidPrefix="ai-rules-working-hours-save-reason"
      />
      <RulesReasonModal
        open={resetOpen}
        onClose={() => setResetOpen(false)}
        title="Reset Working Hours"
        description="Restores the platform-default hours + timezone + enabled flag."
        onConfirm={doReset}
        confirmLabel="Reset to Default"
        confirmVariant="danger"
        testidPrefix="ai-rules-working-hours-reset-reason"
      />
    </div>
  );
}
