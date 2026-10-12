/**
 * scheduleRangePresets · Feb-2026
 * ============================================================
 * Shared quick-select date-range resolvers for Schedule-like
 * pages. Previously inlined in ``pages/schedule/CalendarSchedule.jsx``
 * (``RANGE_PRESETS`` + ``openPreset``). Extracted here so other
 * admin surfaces (Recurring Jobs, future list pages) consume the
 * same date-math without re-implementing it.
 *
 * Conventions (locked by the Feb-2026 brief):
 *   • ``now`` is JS-local ``new Date()``. No tenant-TZ awareness
 *     in this layer — matches Schedule's existing behavior. If
 *     tenant-TZ-correct presets are needed later, that is a
 *     cross-cutting change for both Schedule and Recurring Jobs.
 *   • "This Week" is Sunday-start (US calendar convention; matches
 *     ``date-fns`` ``startOfWeek(..., { weekStartsOn: 0 })`` default).
 *   • Day-count windows are INCLUSIVE both ends. "Next 7 Days" is
 *     today + the following 6 days. Matches Schedule's current
 *     ``addDays(now, daysFromToday - 1)`` math.
 *   • "This Quarter" MIRRORS Schedule's current math verbatim —
 *     ``startOfQuarter(now)`` to ``endOfMonth(month + 2)``. This
 *     diverges from ``endOfQuarter`` when ``now`` is not in the
 *     first month of its quarter; the Feb-2026 brief explicitly
 *     said "Do not 'correct' it in this refactor."
 *
 * Shape:
 *   PRESETS: Array<{ key, label, resolve(now?: Date): {start, end} }>
 *   presetByKey(key): entry — convenience lookup.
 *
 * Each ``resolve`` returns native ``Date`` objects so callers can
 * compare timestamps directly (Schedule) OR format to
 * ``yyyy-MM-dd`` for date-only string compares (RecurringJobs,
 * which filters ``r.upcoming[0]`` — a date-only ISO).
 */
import {
  addDays,
  startOfDay,
  endOfDay,
  startOfWeek,
  endOfWeek,
  startOfMonth,
  endOfMonth,
  startOfQuarter,
} from "date-fns";


/** Byte-equivalent to CalendarSchedule's ``openPreset`` branch for
 *  ``p.daysFromToday``: ``start = startOfDay(now)``,
 *  ``end = endOfDay(addDays(start, daysFromToday - 1))``. */
function _dayWindow(now, daysFromToday) {
  const start = startOfDay(now);
  return { start, end: endOfDay(addDays(start, daysFromToday - 1)) };
}


/** Byte-equivalent to CalendarSchedule's ``isQuarter`` branch:
 *  ``start = startOfQuarter(startOfDay(now))``,
 *  ``end = endOfMonth(new Date(y, m + 2, 1))``.
 *  Preserves the known divergence from ``endOfQuarter`` for
 *  non-first-month-of-quarter ``now`` values per brief. */
function _quarterWindow(now) {
  const anchor = startOfDay(now);
  return {
    start: startOfQuarter(anchor),
    end: endOfMonth(new Date(anchor.getFullYear(), anchor.getMonth() + 2, 1)),
  };
}


export const PRESETS = [
  {
    key: "today",
    label: "Today",
    resolve: (now = new Date()) => _dayWindow(now, 1),
  },
  {
    key: "this_week",
    label: "This Week",
    // Sunday-start per US convention (date-fns default
    // weekStartsOn=0). End is Saturday 23:59:59.999.
    resolve: (now = new Date()) => {
      const anchor = startOfDay(now);
      return {
        start: startOfWeek(anchor, { weekStartsOn: 0 }),
        end: endOfWeek(anchor, { weekStartsOn: 0 }),
      };
    },
  },
  {
    key: "next_7_days",
    label: "Next 7 Days",
    resolve: (now = new Date()) => _dayWindow(now, 7),
  },
  {
    key: "next_30_days",
    label: "Next 30 Days",
    resolve: (now = new Date()) => _dayWindow(now, 30),
  },
  {
    key: "this_month",
    label: "This Month",
    resolve: (now = new Date()) => {
      const anchor = startOfDay(now);
      return { start: startOfMonth(anchor), end: endOfMonth(anchor) };
    },
  },
  {
    key: "next_90_days",
    label: "Next 90 Days",
    resolve: (now = new Date()) => _dayWindow(now, 90),
  },
  {
    key: "this_quarter",
    label: "This Quarter",
    resolve: (now = new Date()) => _quarterWindow(now),
  },
];


export function presetByKey(key) {
  return PRESETS.find((p) => p.key === key) || null;
}
