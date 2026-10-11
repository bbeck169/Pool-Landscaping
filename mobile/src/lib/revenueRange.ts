/**
 * Phase 39A · Revenue Insights range presets — port of web
 * ``frontend/src/components/dashboard/RevenueDateRangeFilter.jsx``.
 *
 * Same 9 presets in the same order, same date semantics:
 *   - Today / Tomorrow resolve in the tenant timezone (P15) with an
 *     ``America/Phoenix`` fallback; Tomorrow adds one calendar day with
 *     UTC arithmetic so DST never shifts the date.
 *   - This/Next Week are Monday-start, device-local.
 *   - This/Last Month and This/Last Year are device-local, inclusive
 *     (YYYY-MM-DD end date; backend applies end-of-day).
 * ``now`` is injectable for tests; production callers omit it.
 * Persists the last selection under web's localStorage key.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

export type RangePresetKey =
  | "today" | "tomorrow" | "this_week" | "next_week" | "this_month"
  | "last_month" | "this_year" | "last_year" | "custom";
export type DateRange = { start: string; end: string };
export type PersistedRange = { preset: RangePresetKey; custom: DateRange };

export const RANGE_STORAGE_KEY = "admin.dashboard.revenue.range.v1";
export const TENANT_TZ_FALLBACK = "America/Phoenix";

export const RANGE_PRESETS: { key: RangePresetKey; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "tomorrow", label: "Tomorrow" },
  { key: "this_week", label: "This Week" },
  { key: "next_week", label: "Next Week" },
  { key: "this_month", label: "This Month" },
  { key: "last_month", label: "Last Month" },
  { key: "this_year", label: "This Year" },
  { key: "last_year", label: "Last Year" },
  { key: "custom", label: "Custom Range" },
];

export function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function isoDateInTz(d: Date, timeZone: string): string {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone, year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(d);
    const y = parts.find((p) => p.type === "year")?.value;
    const m = parts.find((p) => p.type === "month")?.value;
    const day = parts.find((p) => p.type === "day")?.value;
    if (y && m && day) return `${y}-${m}-${day}`;
  } catch { /* invalid timeZone — fall through */ }
  return isoDate(d);
}

const ISO_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
/** Strict YYYY-MM-DD that is a real calendar date (rejects 2025-02-29). */
export function isValidIsoDate(s: string): boolean {
  const m = ISO_RE.exec(s || "");
  if (!m) return false;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const dt = new Date(Date.UTC(y, mo - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d;
}

export function rangeFromPreset(
  preset: RangePresetKey | string,
  custom?: Partial<DateRange> | null,
  opts?: { tenantTimezone?: string | null; now?: Date },
): DateRange {
  const now = opts?.now ? new Date(opts.now) : new Date();
  const tz = opts?.tenantTimezone || TENANT_TZ_FALLBACK;
  switch (preset) {
    case "today": {
      const iso = isoDateInTz(now, tz);
      return { start: iso, end: iso };
    }
    case "tomorrow": {
      const [y, m, d] = isoDateInTz(now, tz).split("-").map((v) => parseInt(v, 10));
      const dt = new Date(Date.UTC(y, m - 1, d));
      dt.setUTCDate(dt.getUTCDate() + 1);
      const iso = `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, "0")}-${String(dt.getUTCDate()).padStart(2, "0")}`;
      return { start: iso, end: iso };
    }
    case "this_week": {
      const s = new Date(now); s.setDate(now.getDate() - ((now.getDay() + 6) % 7));
      const e = new Date(s); e.setDate(s.getDate() + 6);
      return { start: isoDate(s), end: isoDate(e) };
    }
    case "next_week": {
      const s = new Date(now); s.setDate(now.getDate() - ((now.getDay() + 6) % 7) + 7);
      const e = new Date(s); e.setDate(s.getDate() + 6);
      return { start: isoDate(s), end: isoDate(e) };
    }
    case "custom":
      return { start: custom?.start || isoDate(now), end: custom?.end || isoDate(now) };
    case "last_month":
      return {
        start: isoDate(new Date(now.getFullYear(), now.getMonth() - 1, 1)),
        end: isoDate(new Date(now.getFullYear(), now.getMonth(), 0)),
      };
    case "this_year":
      return { start: isoDate(new Date(now.getFullYear(), 0, 1)), end: isoDate(new Date(now.getFullYear(), 11, 31)) };
    case "last_year":
      return { start: isoDate(new Date(now.getFullYear() - 1, 0, 1)), end: isoDate(new Date(now.getFullYear() - 1, 11, 31)) };
    case "this_month":
    default:
      return {
        start: isoDate(new Date(now.getFullYear(), now.getMonth(), 1)),
        end: isoDate(new Date(now.getFullYear(), now.getMonth() + 1, 0)),
      };
  }
}

const KEYS = new Set(RANGE_PRESETS.map((p) => p.key));

export async function loadPersistedRange(): Promise<PersistedRange | null> {
  try {
    const raw = await AsyncStorage.getItem(RANGE_STORAGE_KEY);
    if (!raw) return null;
    const p = JSON.parse(raw);
    if (p && KEYS.has(p.preset)) {
      const c = p.custom || {};
      return {
        preset: p.preset,
        custom: isValidIsoDate(c.start) && isValidIsoDate(c.end) ? { start: c.start, end: c.end } : defaultCustom(),
      };
    }
  } catch { /* ignore corrupt / unavailable storage */ }
  return null;
}

export async function persistRange(v: PersistedRange): Promise<void> {
  try { await AsyncStorage.setItem(RANGE_STORAGE_KEY, JSON.stringify(v)); } catch { /* ignore */ }
}

export function defaultCustom(now?: Date): DateRange {
  const iso = isoDate(now || new Date());
  return { start: iso, end: iso };
}
