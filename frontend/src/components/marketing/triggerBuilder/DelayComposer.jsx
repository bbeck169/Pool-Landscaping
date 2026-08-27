/**
 * Feb 2026 · Phase 2 Custom Trigger Builder · DelayComposer.
 *
 * Four delay modes mapped 1:1 to the Phase-1 evaluator:
 *   * ``immediate``   → { mode: "immediate" }
 *   * ``after``       → { mode: "after", value, unit }
 *   * ``before``      → { mode: "before", value }
 *   * ``on_weekday``  → { mode: "on_weekday", weekday, time_local }
 *
 * ``before`` is auto-disabled and hidden when the chosen event does
 * NOT set ``allow_negative_offset: true`` on the catalog entry.
 */
import React from "react";
import { colors } from "@/theme";


const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];


function ModeRadio({ mode, current, disabled, onSelect, label, testId }) {
  const active = current === mode && !disabled;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onSelect(mode)}
      className="px-2.5 py-1.5 rounded-lg text-xs font-semibold"
      style={{
        backgroundColor: active ? colors.brand : colors.surfaceSecondary,
        color: active ? colors.onBrandPrimary : (disabled ? colors.muted : colors.onSurface),
        border: `1px solid ${active ? colors.brand : colors.border}`,
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
      data-testid={testId}
    >
      {label}
    </button>
  );
}


export function DelayComposer({ value, event, onChange, testIdPrefix = "trigger-delay" }) {
  const delay = value || { mode: "immediate" };
  const mode = delay.mode || "immediate";
  const allowBefore = !!(event && event.allow_negative_offset);

  const setMode = (m) => {
    if (m === "immediate") onChange?.({ mode: "immediate" });
    else if (m === "after") onChange?.({ mode: "after", value: Number(delay.value) || 1, unit: delay.unit || "day" });
    else if (m === "before") onChange?.({ mode: "before", value: Number(delay.value) || 1 });
    else if (m === "on_weekday") onChange?.({ mode: "on_weekday", weekday: Number(delay.weekday) || 0, time_local: delay.time_local || "09:00" });
  };

  return (
    <div data-testid={`${testIdPrefix}-wrap`}>
      <div className="flex items-center gap-2 flex-wrap">
        <ModeRadio mode="immediate" current={mode} onSelect={setMode} label="Immediate" testId={`${testIdPrefix}-mode-immediate`} />
        <ModeRadio mode="after" current={mode} onSelect={setMode} label="After…" testId={`${testIdPrefix}-mode-after`} />
        <ModeRadio
          mode="before"
          current={mode}
          onSelect={setMode}
          disabled={!allowBefore}
          label="Before…"
          testId={`${testIdPrefix}-mode-before`}
        />
        <ModeRadio mode="on_weekday" current={mode} onSelect={setMode} label="On weekday…" testId={`${testIdPrefix}-mode-weekday`} />
      </div>

      {!allowBefore ? (
        <div
          className="mt-2 text-[11px]"
          style={{ color: colors.muted }}
          data-testid={`${testIdPrefix}-before-disabled-hint`}
        >
          "Before" is only available for events with a native scheduled time (job scheduled, birthday, anniversary).
        </div>
      ) : null}

      {mode === "after" ? (
        <div className="mt-2 flex items-center gap-2" data-testid={`${testIdPrefix}-after-inputs`}>
          <input
            type="number"
            min={0}
            value={delay.value ?? 1}
            onChange={(e) => onChange?.({ mode: "after", value: Math.max(0, Number(e.target.value) || 0), unit: delay.unit || "day" })}
            className="w-24 px-2 py-1.5 rounded-lg text-sm outline-none"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid={`${testIdPrefix}-after-value`}
          />
          <select
            value={delay.unit || "day"}
            onChange={(e) => onChange?.({ mode: "after", value: Number(delay.value) || 0, unit: e.target.value })}
            className="px-2 py-1.5 rounded-lg text-sm outline-none"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid={`${testIdPrefix}-after-unit`}
          >
            <option value="minute">minute(s)</option>
            <option value="hour">hour(s)</option>
            <option value="day">day(s)</option>
            <option value="week">week(s)</option>
          </select>
          <span className="text-xs" style={{ color: colors.muted }}>
            after the event
          </span>
        </div>
      ) : null}

      {mode === "before" ? (
        <div className="mt-2 flex items-center gap-2" data-testid={`${testIdPrefix}-before-inputs`}>
          <input
            type="number"
            min={0}
            value={delay.value ?? 1}
            onChange={(e) => onChange?.({ mode: "before", value: Math.max(0, Number(e.target.value) || 0) })}
            className="w-24 px-2 py-1.5 rounded-lg text-sm outline-none"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid={`${testIdPrefix}-before-value`}
          />
          <span className="text-xs" style={{ color: colors.muted }}>
            day(s) before the scheduled event
          </span>
        </div>
      ) : null}

      {mode === "on_weekday" ? (
        <div className="mt-2 flex items-center gap-2 flex-wrap" data-testid={`${testIdPrefix}-weekday-inputs`}>
          <select
            value={String(delay.weekday ?? 0)}
            onChange={(e) => onChange?.({ mode: "on_weekday", weekday: Number(e.target.value), time_local: delay.time_local || "09:00" })}
            className="px-2 py-1.5 rounded-lg text-sm outline-none"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid={`${testIdPrefix}-weekday-select`}
          >
            {WEEKDAY_LABELS.map((lbl, i) => (
              <option key={i} value={i}>{lbl}</option>
            ))}
          </select>
          <input
            type="time"
            value={delay.time_local || "09:00"}
            onChange={(e) => onChange?.({ mode: "on_weekday", weekday: Number(delay.weekday) || 0, time_local: e.target.value })}
            className="px-2 py-1.5 rounded-lg text-sm outline-none"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid={`${testIdPrefix}-weekday-time`}
          />
          <span className="text-xs" style={{ color: colors.muted }}>
            local time
          </span>
        </div>
      ) : null}
    </div>
  );
}
