/**
 * Phase 34 · Feb-2026 — Vitest coverage for the "This Year" + "Last
 * Year" presets added to ``RevenueDateRangeFilter``.
 *
 * Mirrors the ``revenue-date-range-last-month.test.jsx`` pattern:
 * pure-function assertions against ``rangeFromPreset`` (no React
 * mount, no auth context) + a lightweight source-inspection check
 * for popover ordering + testid stability.
 *
 * Assertions:
 *   1. ``PRESETS`` lists "This Year" and "Last Year" between
 *      "Last Month" and "Custom Range" (preserves the dropdown's
 *      "narrow → wide" day → week → month → year → arbitrary flow).
 *   2. ``rangeFromPreset("this_year")`` returns Jan 1 .. Dec 31 of
 *      the browser-local current year (inclusive at both ends).
 *   3. ``rangeFromPreset("last_year")`` returns Jan 1 .. Dec 31
 *      of the previous browser-local year.
 *   4. Year-rollover edge — January 1 still produces the right
 *      year math for both presets.
 *   5. Leap-year edge — ``this_year`` for 2024 covers the full
 *      366-day span (Jan 1 to Dec 31; Feb 29 intentionally
 *      *inside* the range).
 *   6. Pre-Phase-34 presets (this_month / last_month / custom /
 *      fall-through default) still return byte-identical shapes.
 *   7. The rendered popover emits buttons with the testids
 *      ``revenue-range-preset-this_year`` and
 *      ``revenue-range-preset-last_year`` (source-inspection).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import { rangeFromPreset }
  from "@/components/dashboard/RevenueDateRangeFilter";


const COMPONENT_PATH = resolve(__dirname,
  "../components/dashboard/RevenueDateRangeFilter.jsx");
const componentSrc = readFileSync(COMPONENT_PATH, "utf8");


describe("RevenueDateRangeFilter · year-preset PRESETS ordering", () => {
  it("contains This Year AND Last Year between Last Month and Custom Range", () => {
    const lastMonthIdx = componentSrc.indexOf('"last_month"');
    const thisYearIdx = componentSrc.indexOf('"this_year"');
    const lastYearIdx = componentSrc.indexOf('"last_year"');
    const customIdx = componentSrc.indexOf('"custom"');
    expect(lastMonthIdx).toBeGreaterThan(-1);
    expect(thisYearIdx).toBeGreaterThan(-1);
    expect(lastYearIdx).toBeGreaterThan(-1);
    expect(customIdx).toBeGreaterThan(-1);
    // Precise ordering: last_month → this_year → last_year → custom
    expect(lastMonthIdx).toBeLessThan(thisYearIdx);
    expect(thisYearIdx).toBeLessThan(lastYearIdx);
    expect(lastYearIdx).toBeLessThan(customIdx);
  });

  it("exposes This Year with a human-readable label", () => {
    expect(componentSrc).toMatch(
      /key:\s*"this_year"[\s\S]{0,40}label:\s*"This Year"/,
    );
  });

  it("exposes Last Year with a human-readable label", () => {
    expect(componentSrc).toMatch(
      /key:\s*"last_year"[\s\S]{0,40}label:\s*"Last Year"/,
    );
  });

  it("preserves the templated testid prefix that auto-emits "
     + "revenue-range-preset-this_year and -last_year", () => {
    // Popover map yields ``revenue-range-preset-${p.key}`` for every
    // entry — adding the new PRESETS entries auto-produces the
    // testids. Source-check anchor keeps the template intact.
    expect(componentSrc).toMatch(
      /data-testid=\{`revenue-range-preset-\$\{p\.key\}`\}/,
    );
  });
});


describe("rangeFromPreset(\"this_year\") · date math", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("mid-year — July 15 2026 → 2026-01-01..2026-12-31", () => {
    vi.setSystemTime(new Date(2026, 6, 15, 12, 0, 0));
    const r = rangeFromPreset("this_year");
    expect(r.start).toBe("2026-01-01");
    expect(r.end).toBe("2026-12-31");
  });

  it("Jan 1 edge — new year boundary still resolves correctly", () => {
    vi.setSystemTime(new Date(2026, 0, 1, 0, 0, 1));
    const r = rangeFromPreset("this_year");
    expect(r.start).toBe("2026-01-01");
    expect(r.end).toBe("2026-12-31");
  });

  it("Dec 31 edge — last second of year still inside the range", () => {
    vi.setSystemTime(new Date(2026, 11, 31, 23, 59, 59));
    const r = rangeFromPreset("this_year");
    expect(r.start).toBe("2026-01-01");
    expect(r.end).toBe("2026-12-31");
  });

  it("leap year — 2024 covers Feb 29 inside the range", () => {
    vi.setSystemTime(new Date(2024, 2, 15, 12, 0, 0)); // March 15 2024
    const r = rangeFromPreset("this_year");
    expect(r.start).toBe("2024-01-01");
    expect(r.end).toBe("2024-12-31");
    // Feb 29 2024 is lexicographically inside [2024-01-01, 2024-12-31]
    expect("2024-02-29" >= r.start && "2024-02-29" <= r.end).toBe(true);
  });
});


describe("rangeFromPreset(\"last_year\") · date math", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("mid-year — July 15 2026 → 2025-01-01..2025-12-31", () => {
    vi.setSystemTime(new Date(2026, 6, 15, 12, 0, 0));
    const r = rangeFromPreset("last_year");
    expect(r.start).toBe("2025-01-01");
    expect(r.end).toBe("2025-12-31");
  });

  it("Jan 1 2026 — last_year resolves to 2025-01-01..2025-12-31", () => {
    vi.setSystemTime(new Date(2026, 0, 1, 12, 0, 0));
    const r = rangeFromPreset("last_year");
    expect(r.start).toBe("2025-01-01");
    expect(r.end).toBe("2025-12-31");
  });

  it("Dec 31 2026 — last_year still returns 2025-01-01..2025-12-31", () => {
    vi.setSystemTime(new Date(2026, 11, 31, 23, 59, 0));
    const r = rangeFromPreset("last_year");
    expect(r.start).toBe("2025-01-01");
    expect(r.end).toBe("2025-12-31");
  });

  it("leap-year prior — March 15 2025 → last_year = 2024 "
     + "(leap, 366 days inclusive of Feb 29)", () => {
    vi.setSystemTime(new Date(2025, 2, 15, 12, 0, 0));
    const r = rangeFromPreset("last_year");
    expect(r.start).toBe("2024-01-01");
    expect(r.end).toBe("2024-12-31");
    expect("2024-02-29" >= r.start && "2024-02-29" <= r.end).toBe(true);
  });
});


describe("rangeFromPreset · pre-Phase-34 presets unaffected by insertion", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("this_month still returns the current calendar month", () => {
    vi.setSystemTime(new Date(2026, 6, 15, 12, 0, 0));
    const r = rangeFromPreset("this_month");
    expect(r.start).toBe("2026-07-01");
    expect(r.end).toBe("2026-07-31");
  });

  it("last_month still returns the previous calendar month", () => {
    vi.setSystemTime(new Date(2026, 6, 15, 12, 0, 0));
    const r = rangeFromPreset("last_month");
    expect(r.start).toBe("2026-06-01");
    expect(r.end).toBe("2026-06-30");
  });

  it("custom still returns the explicit custom range", () => {
    vi.setSystemTime(new Date(2026, 6, 15, 12, 0, 0));
    const r = rangeFromPreset(
      "custom",
      { start: "2026-05-10", end: "2026-05-20" },
    );
    expect(r.start).toBe("2026-05-10");
    expect(r.end).toBe("2026-05-20");
  });

  it("unknown preset still falls through to this_month default", () => {
    vi.setSystemTime(new Date(2026, 6, 15, 12, 0, 0));
    const r = rangeFromPreset("not_a_real_preset");
    expect(r.start).toBe("2026-07-01");
    expect(r.end).toBe("2026-07-31");
  });
});
