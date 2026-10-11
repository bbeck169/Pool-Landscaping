/**
 * Phase 39A · revenueRange date math — parity with web
 * ``RevenueDateRangeFilter.jsx::rangeFromPreset`` (presets, tenant-tz
 * Today/Tomorrow, Monday-start weeks, month/year rollovers, leap years,
 * year boundaries) + validation + AsyncStorage persistence.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  RANGE_PRESETS, RANGE_STORAGE_KEY, rangeFromPreset, isValidIsoDate, isoDateInTz,
  loadPersistedRange, persistRange,
} from "@/src/lib/revenueRange";

const local = (y: number, m: number, d: number) => new Date(y, m - 1, d, 12, 0, 0); // noon local
const r = (p: string, now: Date, extra: any = {}) => rangeFromPreset(p, extra.custom, { now, tenantTimezone: extra.tz });

describe("presets list", () => {
  it("9 presets in web order with web labels", () => {
    expect(RANGE_PRESETS.map((p) => p.label)).toEqual([
      "Today", "Tomorrow", "This Week", "Next Week", "This Month", "Last Month", "This Year", "Last Year", "Custom Range",
    ]);
    expect(RANGE_PRESETS.map((p) => p.key)).toEqual([
      "today", "tomorrow", "this_week", "next_week", "this_month", "last_month", "this_year", "last_year", "custom",
    ]);
  });
});

describe("Today / Tomorrow — tenant timezone (P15)", () => {
  it("Phoenix evening = previous UTC day; Tomorrow rolls month via UTC math", () => {
    const now = new Date("2026-03-01T05:30:00Z"); // Feb 28 22:30 in Phoenix
    expect(r("today", now, { tz: "America/Phoenix" })).toEqual({ start: "2026-02-28", end: "2026-02-28" });
    expect(r("tomorrow", now, { tz: "America/Phoenix" })).toEqual({ start: "2026-03-01", end: "2026-03-01" });
  });
  it("defaults to America/Phoenix when no tenant tz", () => {
    expect(r("today", new Date("2026-03-01T05:30:00Z"))).toEqual({ start: "2026-02-28", end: "2026-02-28" });
  });
  it("leap day: Tomorrow from Feb 28 2028 is Feb 29; from Feb 29 is Mar 1", () => {
    expect(r("tomorrow", new Date("2028-02-28T18:00:00Z"), { tz: "UTC" })).toEqual({ start: "2028-02-29", end: "2028-02-29" });
    expect(r("tomorrow", new Date("2028-02-29T18:00:00Z"), { tz: "UTC" })).toEqual({ start: "2028-03-01", end: "2028-03-01" });
  });
  it("year boundary: Tomorrow from Dec 31 is Jan 1 next year", () => {
    expect(r("tomorrow", new Date("2026-12-31T18:00:00Z"), { tz: "UTC" })).toEqual({ start: "2027-01-01", end: "2027-01-01" });
  });
  it("invalid tz falls back to device-local date (no throw)", () => {
    expect(isoDateInTz(local(2026, 5, 4), "Not/AZone")).toBe("2026-05-04");
  });
});

describe("weeks — Monday start", () => {
  it("Sunday belongs to the week that started the previous Monday", () => {
    expect(r("this_week", local(2026, 3, 1))).toEqual({ start: "2026-02-23", end: "2026-03-01" });
    expect(r("next_week", local(2026, 3, 1))).toEqual({ start: "2026-03-02", end: "2026-03-08" });
  });
  it("Monday is the first day", () => {
    expect(r("this_week", local(2026, 3, 2))).toEqual({ start: "2026-03-02", end: "2026-03-08" });
  });
  it("week spanning the year boundary", () => {
    expect(r("this_week", local(2025, 12, 31))).toEqual({ start: "2025-12-29", end: "2026-01-04" });
    expect(r("next_week", local(2025, 12, 31))).toEqual({ start: "2026-01-05", end: "2026-01-11" });
  });
});

describe("months", () => {
  it("This Month inclusive; Feb in leap vs non-leap years", () => {
    expect(r("this_month", local(2028, 2, 10))).toEqual({ start: "2028-02-01", end: "2028-02-29" });
    expect(r("this_month", local(2026, 2, 10))).toEqual({ start: "2026-02-01", end: "2026-02-28" });
    expect(r("this_month", local(2026, 12, 31))).toEqual({ start: "2026-12-01", end: "2026-12-31" });
  });
  it("Last Month: January rolls back to December of the previous year", () => {
    expect(r("last_month", local(2026, 1, 15))).toEqual({ start: "2025-12-01", end: "2025-12-31" });
    expect(r("last_month", local(2028, 3, 31))).toEqual({ start: "2028-02-01", end: "2028-02-29" });
  });
  it("unknown preset falls through to This Month (web default branch)", () => {
    expect(r("bogus", local(2026, 7, 4))).toEqual({ start: "2026-07-01", end: "2026-07-31" });
  });
});

describe("years (web Phase 34)", () => {
  it("This Year / Last Year are Jan 1 → Dec 31 inclusive", () => {
    expect(r("this_year", local(2026, 1, 1))).toEqual({ start: "2026-01-01", end: "2026-12-31" });
    expect(r("this_year", local(2026, 12, 31))).toEqual({ start: "2026-01-01", end: "2026-12-31" });
    expect(r("last_year", local(2026, 1, 1))).toEqual({ start: "2025-01-01", end: "2025-12-31" });
    expect(r("last_year", local(2029, 6, 1))).toEqual({ start: "2028-01-01", end: "2028-12-31" });
  });
});

describe("custom + validation", () => {
  it("custom passes through; missing parts fall back to today", () => {
    expect(r("custom", local(2026, 5, 4), { custom: { start: "2026-01-05", end: "2026-02-10" } }))
      .toEqual({ start: "2026-01-05", end: "2026-02-10" });
    expect(r("custom", local(2026, 5, 4), { custom: null })).toEqual({ start: "2026-05-04", end: "2026-05-04" });
  });
  it("isValidIsoDate rejects malformed and impossible dates", () => {
    expect(isValidIsoDate("2028-02-29")).toBe(true);
    expect(isValidIsoDate("2026-02-29")).toBe(false);
    expect(isValidIsoDate("2026-13-01")).toBe(false);
    expect(isValidIsoDate("2026-1-5")).toBe(false);
    expect(isValidIsoDate("")).toBe(false);
  });
});

describe("persistence (AsyncStorage, web key)", () => {
  beforeEach(() => AsyncStorage.clear());
  it("round-trips preset + custom under admin.dashboard.revenue.range.v1", async () => {
    await persistRange({ preset: "last_year", custom: { start: "2026-01-05", end: "2026-02-10" } });
    expect(JSON.parse((await AsyncStorage.getItem(RANGE_STORAGE_KEY)) as string).preset).toBe("last_year");
    expect(await loadPersistedRange()).toEqual({ preset: "last_year", custom: { start: "2026-01-05", end: "2026-02-10" } });
  });
  it("ignores corrupt JSON and unknown presets; repairs invalid custom dates", async () => {
    await AsyncStorage.setItem(RANGE_STORAGE_KEY, "{not json");
    expect(await loadPersistedRange()).toBeNull();
    await AsyncStorage.setItem(RANGE_STORAGE_KEY, JSON.stringify({ preset: "fortnight" }));
    expect(await loadPersistedRange()).toBeNull();
    await AsyncStorage.setItem(RANGE_STORAGE_KEY, JSON.stringify({ preset: "custom", custom: { start: "2026-02-30", end: "x" } }));
    const v = await loadPersistedRange();
    expect(v?.preset).toBe("custom");
    expect(isValidIsoDate(v!.custom.start) && isValidIsoDate(v!.custom.end)).toBe(true);
  });
});
