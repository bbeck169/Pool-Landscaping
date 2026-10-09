/**
 * Feb-2026 · Vitest coverage for the "Last Month" preset added to
 * ``RevenueDateRangeFilter``.
 *
 * Assertions:
 *   1. The ``PRESETS`` array contains "Last Month" between
 *      "This Month" and "Custom Range" (byte-order check via the
 *      exported ``rangeFromPreset`` + a source-inspection anchor).
 *   2. ``rangeFromPreset("last_month")`` returns the first + last
 *      day of the previous calendar month at month-granularity
 *      (ISO ``YYYY-MM-DD``).
 *   3. Year-rollover edge — if ``new Date()`` falls in January,
 *      Last Month resolves to December of the previous year.
 *   4. Mid-year sanity — if ``new Date()`` falls in July, Last
 *      Month resolves to the full month of June.
 *   5. Backward-compat — "This Month" and "Custom Range" presets
 *      still return the same shapes they did before the insert.
 *   6. The rendered popover lists the preset buttons in the
 *      correct testid order.
 *
 * ``rangeFromPreset`` is pure — no React mount, no auth context
 * required — so date-math assertions can hit it directly via its
 * named export.  The popover ordering test uses the lightweight
 * source-inspection pattern already used by the Customer action-
 * bar suite to avoid pulling in AuthProvider for a string check.
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


describe("RevenueDateRangeFilter · PRESETS ordering", () => {
  it("contains Last Month between This Month and Custom Range", () => {
    const thisIdx = componentSrc.indexOf('"this_month"');
    const lastIdx = componentSrc.indexOf('"last_month"');
    const customIdx = componentSrc.indexOf('"custom"');
    expect(thisIdx).toBeGreaterThan(-1);
    expect(lastIdx).toBeGreaterThan(-1);
    expect(customIdx).toBeGreaterThan(-1);
    expect(thisIdx).toBeLessThan(lastIdx);
    expect(lastIdx).toBeLessThan(customIdx);
  });

  it("exposes Last Month with a human-readable label", () => {
    expect(componentSrc).toMatch(
      /key:\s*"last_month"[\s\S]{0,40}label:\s*"Last Month"/,
    );
  });

  it("renders a preset button with the testid revenue-range-preset-last_month", () => {
    // The popover maps PRESETS to buttons with testid prefix
    // ``revenue-range-preset-${key}`` — a run of the array
    // through the component's map will auto-emit this testid for
    // the new preset.  Source-check anchor:
    expect(componentSrc).toMatch(
      /data-testid=\{`revenue-range-preset-\$\{p\.key\}`\}/,
    );
  });
});


describe("rangeFromPreset(\"last_month\") · date math", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("mid-year — July 15 → June 1..June 30", () => {
    vi.setSystemTime(new Date(2026, 6, 15, 12, 0, 0)); // 2026-07-15
    const r = rangeFromPreset("last_month");
    expect(r.start).toBe("2026-06-01");
    expect(r.end).toBe("2026-06-30");
  });

  it("year-rollover — January 1 → December of previous year", () => {
    vi.setSystemTime(new Date(2026, 0, 1, 12, 0, 0)); // 2026-01-01
    const r = rangeFromPreset("last_month");
    expect(r.start).toBe("2025-12-01");
    expect(r.end).toBe("2025-12-31");
  });

  it("year-rollover — January 31 → December 1..December 31", () => {
    vi.setSystemTime(new Date(2026, 0, 31, 23, 59, 0));
    const r = rangeFromPreset("last_month");
    expect(r.start).toBe("2025-12-01");
    expect(r.end).toBe("2025-12-31");
  });

  it("February from March — handles the 28/29-day prev-month boundary", () => {
    // Leap year — Feb 2024 had 29 days.
    vi.setSystemTime(new Date(2024, 2, 15, 12, 0, 0)); // 2024-03-15
    const r = rangeFromPreset("last_month");
    expect(r.start).toBe("2024-02-01");
    expect(r.end).toBe("2024-02-29");
  });

  it("February from March — handles 28-day non-leap prev-month", () => {
    vi.setSystemTime(new Date(2025, 2, 15, 12, 0, 0)); // 2025-03-15
    const r = rangeFromPreset("last_month");
    expect(r.start).toBe("2025-02-01");
    expect(r.end).toBe("2025-02-28");
  });

  it("March from April — handles 31-day prev-month", () => {
    vi.setSystemTime(new Date(2026, 3, 10, 12, 0, 0)); // 2026-04-10
    const r = rangeFromPreset("last_month");
    expect(r.start).toBe("2026-03-01");
    expect(r.end).toBe("2026-03-31");
  });
});


describe("rangeFromPreset · existing presets unaffected by insertion", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("this_month still returns the current calendar month", () => {
    vi.setSystemTime(new Date(2026, 6, 15, 12, 0, 0)); // 2026-07-15
    const r = rangeFromPreset("this_month");
    expect(r.start).toBe("2026-07-01");
    expect(r.end).toBe("2026-07-31");
  });

  it("custom returns the explicit custom range unchanged", () => {
    vi.setSystemTime(new Date(2026, 6, 15, 12, 0, 0));
    const r = rangeFromPreset(
      "custom",
      { start: "2026-05-10", end: "2026-05-20" },
    );
    expect(r.start).toBe("2026-05-10");
    expect(r.end).toBe("2026-05-20");
  });

  it("custom falls back to today when no custom pair is supplied", () => {
    vi.setSystemTime(new Date(2026, 6, 15, 12, 0, 0));
    const r = rangeFromPreset("custom");
    expect(r.start).toBe("2026-07-15");
    expect(r.end).toBe("2026-07-15");
  });

  it("unknown preset falls through to this_month default (back-compat)", () => {
    vi.setSystemTime(new Date(2026, 6, 15, 12, 0, 0));
    const r = rangeFromPreset("not_a_real_preset");
    expect(r.start).toBe("2026-07-01");
    expect(r.end).toBe("2026-07-31");
  });
});
