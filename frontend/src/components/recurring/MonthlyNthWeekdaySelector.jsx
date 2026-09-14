/**
 * Feb-2026 · Shared recurrence UI helpers.
 *
 * Two small, self-contained pickers used by BOTH:
 *   • ``/admin/recurring-jobs`` (RecurringJobs.jsx modal)
 *   • ``/jobs/new``             (JobNew.jsx recurrence panel)
 *
 * Splitting them here means the wire contract stays canonical in
 * exactly one place and neither surface can drift from the other.
 *
 * Backend contract (see backend/routers/recurring_jobs.py):
 *   monthly_pattern  ∈ {"day_of_month", "nth_weekday"}
 *   monthly_nth_week ∈ {"first","second","third","fourth","last"}  (STRING enum)
 *   monthly_weekday  ∈ 0..6                                        (Mon=0…Sun=6)
 *   recurrence_never_ends: boolean; when true, backend forces end_date=null.
 */
import React from "react";
import { colors } from "@/theme";

// Backend order — Python's ``date.weekday()`` convention.
export const DOW_OPTS = [
  { value: 0, label: "Mon" },
  { value: 1, label: "Tue" },
  { value: 2, label: "Wed" },
  { value: 3, label: "Thu" },
  { value: 4, label: "Fri" },
  { value: 5, label: "Sat" },
  { value: 6, label: "Sun" },
];

export const NTH_WEEK_OPTS = [
  { value: "first",  label: "1st" },
  { value: "second", label: "2nd" },
  { value: "third",  label: "3rd" },
  { value: "fourth", label: "4th" },
  { value: "last",   label: "Last" },
];

const pillStyle = (active) => ({
  padding: "6px 12px",
  borderRadius: 999,
  border: `1px solid ${active ? colors.brand : colors.border}`,
  backgroundColor: active ? colors.brand : colors.surface,
  color: active ? "#fff" : colors.onSurface,
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
});

/**
 * Monthly recurrence pattern selector.
 * Exposes a pattern-radio ("Same day each month" vs "Nth weekday")
 * plus the two Nth-weekday sub-pickers when the latter is chosen.
 *
 * @param value = { monthly_pattern, monthly_nth_week, monthly_weekday }
 * @param onChange (partialPatch) — parent merges into template state.
 * @param testidPrefix — prefixed onto every data-testid. Defaults to "monthly-nth-".
 */
export function MonthlyNthWeekdaySelector({ value, onChange, testidPrefix = "monthly-nth-" }) {
  const pattern = value?.monthly_pattern || "day_of_month";
  const nth = value?.monthly_nth_week || "first";
  const wd = value?.monthly_weekday ?? 0;

  return (
    <div data-testid={`${testidPrefix}selector`}>
      <label className="text-xs font-semibold uppercase tracking-wide"
             style={{ color: colors.muted }}>
        Monthly pattern
      </label>
      <div className="flex gap-2 mt-1 mb-3" role="radiogroup" aria-label="Monthly pattern">
        <button
          type="button" role="radio" aria-checked={pattern === "day_of_month"}
          style={pillStyle(pattern === "day_of_month")}
          onClick={() => onChange({ monthly_pattern: "day_of_month" })}
          data-testid={`${testidPrefix}pattern-day_of_month`}
        >
          Same day each month
        </button>
        <button
          type="button" role="radio" aria-checked={pattern === "nth_weekday"}
          style={pillStyle(pattern === "nth_weekday")}
          onClick={() => onChange({
            monthly_pattern: "nth_weekday",
            // Ensure companion fields are seeded when the user
            // first flips into ``nth_weekday`` — backend rejects
            // the pattern with 422 when either is missing.
            monthly_nth_week: value?.monthly_nth_week || "first",
            monthly_weekday: value?.monthly_weekday ?? 0,
          })}
          data-testid={`${testidPrefix}pattern-nth_weekday`}
        >
          Custom Weekdays
        </button>
      </div>

      {pattern === "day_of_month" ? (
        <div data-testid={`${testidPrefix}day_of_month-input`}>
          <label className="text-xs font-semibold uppercase tracking-wide"
                 style={{ color: colors.muted }}>
            Day of month (1–31)
          </label>
          <input
            type="number"
            min={1}
            max={31}
            value={value?.day_of_month ?? 1}
            onChange={(e) => onChange({ day_of_month: Number(e.target.value) })}
            className="mt-1 px-3 py-1.5 rounded-lg text-sm w-32"
            style={{
              border: `1px solid ${colors.border}`,
              background: colors.surface,
              color: colors.onSurface,
            }}
            data-testid={`${testidPrefix}day_of_month`}
          />
        </div>
      ) : null}

      {pattern === "nth_weekday" ? (
        <div className="grid gap-3" data-testid={`${testidPrefix}subpickers`}>
          <div>
            <label className="text-xs font-semibold uppercase tracking-wide"
                   style={{ color: colors.muted }}>
              Week of month
            </label>
            <div className="flex flex-wrap gap-2 mt-1" role="radiogroup" aria-label="Week of month">
              {NTH_WEEK_OPTS.map((o) => (
                <button
                  key={o.value}
                  type="button" role="radio" aria-checked={nth === o.value}
                  style={pillStyle(nth === o.value)}
                  onClick={() => onChange({ monthly_nth_week: o.value })}
                  data-testid={`${testidPrefix}week-${o.value}`}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-xs font-semibold uppercase tracking-wide"
                   style={{ color: colors.muted }}>
              Weekday
            </label>
            <div className="flex flex-wrap gap-2 mt-1" role="radiogroup" aria-label="Weekday">
              {DOW_OPTS.map((o) => (
                <button
                  key={o.value}
                  type="button" role="radio" aria-checked={wd === o.value}
                  style={pillStyle(wd === o.value)}
                  onClick={() => onChange({ monthly_weekday: o.value })}
                  data-testid={`${testidPrefix}weekday-${o.value}`}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Recurrence-ends radio — "Never" vs "On date".
 *
 * @param value = { recurrence_never_ends, end_date }
 * @param onChange (partialPatch)
 * @param testidPrefix — defaults to "recurrence-ends-".
 */
export function RecurrenceEndsRadio({ value, onChange, testidPrefix = "recurrence-ends-" }) {
  const never = value?.recurrence_never_ends !== false;
  return (
    <fieldset className="border-0 p-0 m-0" data-testid={`${testidPrefix}radio`}>
      <legend className="text-xs font-semibold uppercase tracking-wide px-0"
              style={{ color: colors.muted }}>
        Ends
      </legend>
      <div className="flex flex-col gap-2 mt-1">
        <label className="flex items-center gap-2 text-sm" style={{ color: colors.onSurface }}>
          <input
            type="radio"
            name={`${testidPrefix}mode`}
            checked={!!never}
            onChange={() => onChange({ recurrence_never_ends: true, end_date: null })}
            data-testid={`${testidPrefix}never`}
          />
          <span className="font-semibold">Never</span>
          <span className="text-xs" style={{ color: colors.muted }}>
            {never ? "Series will roll forever" : "Series stops on end date"}
          </span>
        </label>
        <label className="flex items-center gap-2 text-sm" style={{ color: colors.onSurface }}>
          <input
            type="radio"
            name={`${testidPrefix}mode`}
            checked={!never}
            onChange={() => onChange({ recurrence_never_ends: false })}
            data-testid={`${testidPrefix}on-date`}
          />
          <span className="font-semibold">On date</span>
          <input
            type="date"
            disabled={!!never}
            value={value?.end_date || ""}
            onChange={(e) => onChange({
              end_date: e.target.value || null,
              recurrence_never_ends: false,
            })}
            style={{
              padding: "4px 8px",
              borderRadius: 6,
              border: `1px solid ${colors.border}`,
              background: never ? colors.surfaceSecondary : colors.surface,
              color: never ? colors.muted : colors.onSurface,
              opacity: never ? 0.55 : 1,
              fontSize: 12,
            }}
            data-testid={`${testidPrefix}date-input`}
          />
        </label>
      </div>
    </fieldset>
  );
}
