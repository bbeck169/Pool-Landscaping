/**
 * Mobile `src/lib/scheduleRangePresets.ts` — pins all 7 presets at fixed
 * JS-local anchors so mobile stays byte-equivalent to web
 * `frontend/src/lib/scheduleRangePresets.js` (054633ec0).
 */
import { format } from "date-fns";
import { PRESETS, presetByKey } from "@/src/lib/scheduleRangePresets";

const F = "yyyy-MM-dd HH:mm:ss.SSS";
const fmt = (w: { start: Date; end: Date }) => [format(w.start, F), format(w.end, F)];
const at = (y: number, m: number, d: number, h = 14, min = 37) => new Date(y, m - 1, d, h, min, 12, 345);

describe("scheduleRangePresets · shape", () => {
  it("7 keys + labels in web order", () => {
    expect(PRESETS.map((p) => [p.key, p.label])).toEqual([
      ["today", "Today"], ["this_week", "This Week"], ["next_7_days", "Next 7 Days"],
      ["next_30_days", "Next 30 Days"], ["this_month", "This Month"],
      ["next_90_days", "Next 90 Days"], ["this_quarter", "This Quarter"],
    ]);
  });
  it("presetByKey returns the entry or null; resolve returns {start: Date, end: Date}", () => {
    expect(presetByKey("today")?.label).toBe("Today");
    expect(presetByKey("nope")).toBeNull();
    const w = presetByKey("today")!.resolve(at(2026, 10, 12));
    expect(Object.keys(w)).toEqual(["start", "end"]);
    expect(w.start).toBeInstanceOf(Date);
    expect(w.end).toBeInstanceOf(Date);
  });
  it("default `now` is JS-local new Date()", () => {
    jest.useFakeTimers().setSystemTime(at(2026, 10, 12));
    try {
      expect(fmt(presetByKey("today")!.resolve())).toEqual(["2026-10-12 00:00:00.000", "2026-10-12 23:59:59.999"]);
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("scheduleRangePresets · pinned windows", () => {
  // Monday 2026-10-12 (the smoke-test anchor).
  const MON = at(2026, 10, 12);
  it.each([
    ["today", ["2026-10-12 00:00:00.000", "2026-10-12 23:59:59.999"]],
    ["this_week", ["2026-10-11 00:00:00.000", "2026-10-17 23:59:59.999"]],
    ["next_7_days", ["2026-10-12 00:00:00.000", "2026-10-18 23:59:59.999"]],
    ["next_30_days", ["2026-10-12 00:00:00.000", "2026-11-10 23:59:59.999"]],
    ["this_month", ["2026-10-01 00:00:00.000", "2026-10-31 23:59:59.999"]],
    ["next_90_days", ["2026-10-12 00:00:00.000", "2027-01-09 23:59:59.999"]],
    ["this_quarter", ["2026-10-01 00:00:00.000", "2026-12-31 23:59:59.999"]],
  ])("%s @ Mon 2026-10-12", (key, expected) => {
    expect(fmt(presetByKey(key as string)!.resolve(MON))).toEqual(expected);
  });

  it("This Week is Sunday-start: Sunday anchors its own week, Saturday ends it", () => {
    expect(fmt(presetByKey("this_week")!.resolve(at(2026, 10, 11)))).toEqual(["2026-10-11 00:00:00.000", "2026-10-17 23:59:59.999"]);
    expect(fmt(presetByKey("this_week")!.resolve(at(2026, 10, 17, 23, 59)))).toEqual(["2026-10-11 00:00:00.000", "2026-10-17 23:59:59.999"]);
  });

  it("This Week crosses a month/year boundary", () => {
    expect(fmt(presetByKey("this_week")!.resolve(at(2026, 12, 31)))).toEqual(["2026-12-27 00:00:00.000", "2027-01-02 23:59:59.999"]);
  });

  it("This Month handles Feb in leap / non-leap years", () => {
    expect(fmt(presetByKey("this_month")!.resolve(at(2028, 2, 10)))).toEqual(["2028-02-01 00:00:00.000", "2028-02-29 23:59:59.999"]);
    expect(fmt(presetByKey("this_month")!.resolve(at(2027, 2, 10)))).toEqual(["2027-02-01 00:00:00.000", "2027-02-28 23:59:59.999"]);
  });

  it("This Quarter mirrors web's month+2 math (diverges from endOfQuarter off the first month)", () => {
    expect(fmt(presetByKey("this_quarter")!.resolve(at(2026, 1, 15)))).toEqual(["2026-01-01 00:00:00.000", "2026-03-31 23:59:59.999"]);
    // Feb anchor → end = endOfMonth(Apr), NOT Mar 31 — intentional web parity.
    expect(fmt(presetByKey("this_quarter")!.resolve(at(2026, 2, 15)))).toEqual(["2026-01-01 00:00:00.000", "2026-04-30 23:59:59.999"]);
    expect(fmt(presetByKey("this_quarter")!.resolve(at(2026, 12, 5)))).toEqual(["2026-10-01 00:00:00.000", "2027-02-28 23:59:59.999"]);
  });

  it("day windows are inclusive: Next 7 Days at 00:00 and 23:59 give the same window", () => {
    const a = fmt(presetByKey("next_7_days")!.resolve(at(2026, 10, 12, 0, 0)));
    const b = fmt(presetByKey("next_7_days")!.resolve(at(2026, 10, 12, 23, 59)));
    expect(a).toEqual(b);
  });
});
