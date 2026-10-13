/**
 * P2 #9 · scheduleDayKey — single source of truth for "which calendar
 * day does this schedule row / focus date belong to?" on mobile.
 *
 * Mirrors web CalendarSchedule.jsx P13 (dayJobs / mapDayJobs /
 * weekCounts, L1258-1336):
 *   1. ``scheduled_date.slice(0, 10)`` when it is a YYYY-MM-DD prefix
 *      (covers bare dates AND timestamp-shaped values such as
 *      ``2026-09-15T06:40:46+00:00`` — the old exact-equality filter
 *      silently dropped those).
 *   2. else ``scheduled_start`` bucketed into the TENANT-local day.
 *   3. else "" (unplaceable).
 *
 * ``localDateKey`` replaces ``d.toISOString().slice(0, 10)`` for focus
 * keys: the focus ``Date`` is device-local (``new Date()`` / strip tap
 * → ``new Date(y, m-1, d)``), so its key must be read from local
 * calendar fields — same as WeekStrip — or a US device after ~8 pm
 * jumps to tomorrow and an east-of-UTC device slips to yesterday.
 */
import { isoDate, isoDateInTz } from "@/src/lib/revenueRange";
import { tenantTz } from "@/src/utils/tenantTime";

const YMD_PREFIX = /^\d{4}-\d{2}-\d{2}/;

/** Device-local ``YYYY-MM-DD`` for a calendar-day ``Date`` (DST-safe). */
export function localDateKey(d: Date): string {
  return isoDate(d);
}

type DayKeyable = { scheduled_date?: string | null; scheduled_start?: string | null };

/** Tenant-local ``YYYY-MM-DD`` a schedule row belongs to, or "". */
export function jobDayKey(job: DayKeyable, tz: string = tenantTz()): string {
  const sd = job?.scheduled_date || "";
  if (YMD_PREFIX.test(sd)) return sd.slice(0, 10);
  const ss = job?.scheduled_start;
  if (!ss) return "";
  const t = new Date(ss);
  if (Number.isNaN(t.getTime())) return "";
  return isoDateInTz(t, tz);
}
