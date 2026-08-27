/**
 * Feb 2026 · Color pass Fix 1 — RevenueChart CURRENT-month
 * detection is time-aware.
 *
 * We test the pure ``computeRevenueBarFills(series, now)`` helper
 * exported from ``pages/admin/Dashboard.jsx`` — recharts SVGs
 * don't lay out in jsdom, so unit-testing the pure logic is
 * both more reliable AND catches the "isLast vs current month"
 * regression at its true origin.
 */
import { describe, it, expect } from "vitest";

import { colors } from "@/theme";
import { computeRevenueBarFills } from "@/pages/admin/Dashboard";


// Standard 6-row series covering Mar → Aug.
const SERIES_MAR_TO_AUG = [
  { label: "Mar", value: 300 },
  { label: "Apr", value: 550 },
  { label: "May", value: 420 },
  { label: "Jun", value: 700 },
  { label: "Jul", value: 480 },
  { label: "Aug", value: 520 },
];


describe("computeRevenueBarFills (current-month highlight)", () => {
  it("Aug is the highlighted bar when system date is Aug (with value>0)", () => {
    // Aug value > 0 → highlight it directly.
    const now = new Date(2026, 7, 15);   // month is 0-indexed
    const filled = computeRevenueBarFills(SERIES_MAR_TO_AUG, now);
    // Aug is index 5.
    expect(filled[5].isCurrent).toBe(true);
    expect(filled[5].fill).toBe(colors.pool[500]);
    // Only ONE bar in the pool[500] cyan.
    const highlighted = filled.filter((d) => d.fill === colors.pool[500]);
    expect(highlighted.length).toBe(1);
    // The other 5 bars carry accent-500 fills — never pool[500].
    for (let i = 0; i < 5; i += 1) {
      expect(filled[i].fill).not.toBe(colors.pool[500]);
      expect(filled[i].isCurrent).toBe(false);
    }
  });

  it("When current-month has value=0 (Aug=0, not yet invoiced), re-anchor to the most recent non-zero bar", () => {
    // This is the EXACT scenario the tester saw in production:
    // backend returns Aug=0 (tenant hasn't invoiced this month
    // yet). With the naive fix the highlight would land on a
    // zero-height bar → invisible. The smart fallback re-anchors
    // on Jul (most recent non-zero) so the highlight stays
    // visible.
    const SERIES_WITH_EMPTY_AUG = [
      { label: "Mar", value: 324.0 },
      { label: "Apr", value: 583.2 },
      { label: "May", value: 410.4 },
      { label: "Jun", value: 658.8 },
      { label: "Jul", value: 453.6 },
      { label: "Aug", value: 0.0 },
    ];
    const now = new Date(2026, 7, 15);
    const filled = computeRevenueBarFills(SERIES_WITH_EMPTY_AUG, now);
    // Aug NOT highlighted (would be an invisible zero-height bar).
    expect(filled[5].isCurrent).toBe(false);
    expect(filled[5].fill).not.toBe(colors.pool[500]);
    // Jul (most recent non-zero) IS highlighted.
    expect(filled[4].isCurrent).toBe(true);
    expect(filled[4].fill).toBe(colors.pool[500]);
    // Exactly one highlight.
    expect(filled.filter((d) => d.fill === colors.pool[500]).length).toBe(1);
  });

  it("highlights May when now=May (mid-series case that the tester saw pre-fix)", () => {
    const now = new Date(2026, 4, 10);   // May
    const filled = computeRevenueBarFills(SERIES_MAR_TO_AUG, now);
    expect(filled[2].isCurrent).toBe(true);
    expect(filled[2].fill).toBe(colors.pool[500]);
    // Aug (index 5) is NOT highlighted — this is the exact
    // regression the tester flagged. Before the fix, "isLast"
    // would light up Aug (which was correct in Aug but wrong
    // in May).
    expect(filled[5].isCurrent).toBe(false);
    expect(filled[5].fill).not.toBe(colors.pool[500]);
  });

  it("highlights Mar when now=Mar", () => {
    const now = new Date(2026, 2, 3);   // March
    const filled = computeRevenueBarFills(SERIES_MAR_TO_AUG, now);
    expect(filled[0].isCurrent).toBe(true);
    expect(filled[0].fill).toBe(colors.pool[500]);
  });

  it("falls back to the LAST bar when series doesn't include the current month", () => {
    const now = new Date(2026, 11, 1);   // December — not in series
    const filled = computeRevenueBarFills(SERIES_MAR_TO_AUG, now);
    // Last bar (Aug, index 5) gets the highlight so the chart
    // never renders flat.
    expect(filled[5].isCurrent).toBe(true);
    expect(filled[5].fill).toBe(colors.pool[500]);
    // Only that one bar — no double highlight.
    expect(
      filled.filter((d) => d.fill === colors.pool[500]).length,
    ).toBe(1);
  });

  it("empty series produces empty output (no crash)", () => {
    expect(computeRevenueBarFills([], new Date(2026, 7, 15))).toEqual([]);
    expect(computeRevenueBarFills(null, new Date())).toEqual([]);
    expect(computeRevenueBarFills(undefined, new Date())).toEqual([]);
  });

  it("non-current-month bars rotate through the accent palette (violet, amber, sky, emerald, rose)", () => {
    const now = new Date(2026, 7, 15);   // Aug — highlights index 5
    const filled = computeRevenueBarFills(SERIES_MAR_TO_AUG, now);
    // Rotation is [violet, amber, sky, emerald, rose] — indexes
    // 0..4 map onto that; index 5 IS the current month so it
    // takes pool[500].
    expect(filled[0].fill).toBe(colors.accent.violet[500]);
    expect(filled[1].fill).toBe(colors.accent.amber[500]);
    expect(filled[2].fill).toBe(colors.accent.sky[500]);
    expect(filled[3].fill).toBe(colors.accent.emerald[500]);
    expect(filled[4].fill).toBe(colors.accent.rose[500]);
    expect(filled[5].fill).toBe(colors.pool[500]);
  });
});
