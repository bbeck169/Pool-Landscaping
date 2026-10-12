/**
 * scheduleRangePresets · mobile port
 * ============================================================
 * Line-for-line port of web ``frontend/src/lib/scheduleRangePresets.js``
 * (054633ec0). Same keys, labels, order, resolver math and output
 * shape ``{ start: Date, end: Date }`` so mobile + web agree at any
 * fixed ``now`` anchor (verified identical across date-fns 4.1.0 /
 * 4.3.0, UTC / America/New_York / Australia/Sydney incl. DST).
 *
 * Conventions (same as web):
 *   • ``now`` is JS-local ``new Date()`` — no tenant-TZ awareness.
 *   • "This Week" is Sunday-start (date-fns ``weekStartsOn: 0``).
 *   • Day-count windows are INCLUSIVE both ends ("Next 7 Days" =
 *     today + the following 6 days).
 *   • "This Quarter" mirrors web/Schedule verbatim —
 *     ``startOfQuarter(now)`` → ``endOfMonth(month + 2)`` (diverges from
 *     ``endOfQuarter`` off the first month of a quarter; intentional).
 *
 * Consumers: ``app/finance/recurring-jobs.tsx`` (5 keys). ``next_90_days``
 * + ``this_quarter`` are ported for symmetry (web Schedule-only).
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

export type RangeWindow = { start: Date; end: Date };
export type RangePresetKey =
  | "today" | "this_week" | "next_7_days" | "next_30_days"
  | "this_month" | "next_90_days" | "this_quarter";
export type RangePreset = { key: RangePresetKey; label: string; resolve: (now?: Date) => RangeWindow };

function _dayWindow(now: Date, daysFromToday: number): RangeWindow {
  const start = startOfDay(now);
  return { start, end: endOfDay(addDays(start, daysFromToday - 1)) };
}

function _quarterWindow(now: Date): RangeWindow {
  const anchor = startOfDay(now);
  return {
    start: startOfQuarter(anchor),
    end: endOfMonth(new Date(anchor.getFullYear(), anchor.getMonth() + 2, 1)),
  };
}

export const PRESETS: RangePreset[] = [
  { key: "today", label: "Today", resolve: (now = new Date()) => _dayWindow(now, 1) },
  {
    key: "this_week",
    label: "This Week",
    resolve: (now = new Date()) => {
      const anchor = startOfDay(now);
      return {
        start: startOfWeek(anchor, { weekStartsOn: 0 }),
        end: endOfWeek(anchor, { weekStartsOn: 0 }),
      };
    },
  },
  { key: "next_7_days", label: "Next 7 Days", resolve: (now = new Date()) => _dayWindow(now, 7) },
  { key: "next_30_days", label: "Next 30 Days", resolve: (now = new Date()) => _dayWindow(now, 30) },
  {
    key: "this_month",
    label: "This Month",
    resolve: (now = new Date()) => {
      const anchor = startOfDay(now);
      return { start: startOfMonth(anchor), end: endOfMonth(anchor) };
    },
  },
  { key: "next_90_days", label: "Next 90 Days", resolve: (now = new Date()) => _dayWindow(now, 90) },
  { key: "this_quarter", label: "This Quarter", resolve: (now = new Date()) => _quarterWindow(now) },
];

export function presetByKey(key: string): RangePreset | null {
  return PRESETS.find((p) => p.key === key) || null;
}
