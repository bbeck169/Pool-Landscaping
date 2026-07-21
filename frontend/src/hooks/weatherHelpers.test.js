/**
 * weatherHelpers · unit tests — Feb-2026.
 *
 * Covers the deterministic rain-overlap logic used by
 * ``JobRainFlag``. The hook itself (React effect + module-level
 * cache) is exercised via Playwright; these tests only validate
 * the pure JS predicates so they can run offline without a
 * webpack alias resolver.
 */
import { hasRainOnDate, maxRainChanceOnDate } from "./weatherHelpers";

describe("hasRainOnDate", () => {
  const RAINY = {
    hourly: [
      { time: "2026-07-21 09:00", chance_of_rain: 20 },
      { time: "2026-07-21 12:00", chance_of_rain: 75 },
      { time: "2026-07-22 06:00", chance_of_rain: 0 },
    ],
  };
  const DRY = {
    hourly: [
      { time: "2026-07-21 09:00", chance_of_rain: 5 },
      { time: "2026-07-21 15:00", chance_of_rain: 20 },
      { time: "2026-07-22 12:00", chance_of_rain: 40 },
    ],
  };

  test("returns true when a matching hour is >= 60%", () => {
    expect(hasRainOnDate(RAINY, "2026-07-21", 60)).toBe(true);
  });

  test("returns false when no matching hour meets the threshold", () => {
    expect(hasRainOnDate(DRY, "2026-07-21", 60)).toBe(false);
  });

  test("returns false when the date has no hourly rows", () => {
    expect(hasRainOnDate(RAINY, "2026-07-23", 60)).toBe(false);
  });

  test("returns false for null / malformed payloads", () => {
    expect(hasRainOnDate(null, "2026-07-21")).toBe(false);
    expect(hasRainOnDate({}, "2026-07-21")).toBe(false);
    expect(hasRainOnDate({ hourly: null }, "2026-07-21")).toBe(false);
  });

  test("returns false when dateISO is missing", () => {
    expect(hasRainOnDate(RAINY, "")).toBe(false);
    expect(hasRainOnDate(RAINY, null)).toBe(false);
  });

  test("respects custom thresholds", () => {
    expect(hasRainOnDate(DRY, "2026-07-22", 40)).toBe(true);
    expect(hasRainOnDate(DRY, "2026-07-22", 41)).toBe(false);
  });
});

describe("maxRainChanceOnDate", () => {
  const PAYLOAD = {
    hourly: [
      { time: "2026-07-21 09:00", chance_of_rain: 20 },
      { time: "2026-07-21 12:00", chance_of_rain: 75 },
      { time: "2026-07-21 18:00", chance_of_rain: 40 },
    ],
  };

  test("returns the max across matching rows", () => {
    expect(maxRainChanceOnDate(PAYLOAD, "2026-07-21")).toBe(75);
  });

  test("returns null when no rows match", () => {
    expect(maxRainChanceOnDate(PAYLOAD, "2026-07-30")).toBeNull();
  });

  test("returns null for malformed payloads", () => {
    expect(maxRainChanceOnDate(null, "2026-07-21")).toBeNull();
    expect(maxRainChanceOnDate({}, "2026-07-21")).toBeNull();
  });
});
