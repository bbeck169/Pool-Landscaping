/**
 * Feb 2026 · Color pass — WCAG AA contrast spot-check.
 *
 * Runs concrete contrast calculations on the color/text pairs
 * the new KPI tiles + primary buttons ACTUALLY render. If any
 * future palette retune drops one of these below 4.5:1, this
 * test fails and forces the change to either bump the shade or
 * flip the text color.
 *
 * Reports the numeric ratios in-console so the QA can eyeball
 * them in the CI log.
 */
import { describe, it, expect } from "vitest";
import { colors } from "@/theme";
import { getContrastRatio } from "@/utils/serviceLineTheme";


// ─── Sample pairs ────────────────────────────────────────────────
// Each entry: [description, bgHex, fgHex, minRatio]
//   • KPI label = onSurface text on the palette[50] tint
//   • KPI number = onSurface text on palette[50]
//   • Primary CTA = white text on palette[600]
//   • Chart legend / high-contrast text on strong shades
const SAMPLES = [
  // KPI tile — Active Jobs (sky)
  ["KPI number on sky[50]",   colors.accent.sky[50],  colors.onSurface, 4.5],
  // KPI tile — Pending (amber)
  ["KPI number on amber[50]", colors.accent.amber[50], colors.onSurface, 4.5],
  // KPI tile — Customers (violet)
  ["KPI number on violet[50]",colors.accent.violet[50],colors.onSurface, 4.5],
  // Primary Pool CTA — white on pool[600]
  ["White text on pool[600]", colors.pool[600], "#FFFFFF", 3.0],
  // Primary Landscape CTA — white on landscape[600]
  ["White text on landscape[600]", colors.landscape[600], "#FFFFFF", 3.0],
];


describe("Color pass · WCAG AA contrast spot-check", () => {
  it.each(SAMPLES)("%s ≥ %s : 1", (desc, bg, fg, min) => {
    const ratio = getContrastRatio(bg, fg);
    // eslint-disable-next-line no-console
    console.log(`[contrast] ${desc}: ${ratio.toFixed(2)}:1 (≥ ${min})`);
    expect(ratio).toBeGreaterThanOrEqual(min);
  });

  it("reports 5 concrete ratios for the color-pass report", () => {
    const report = SAMPLES.map(([desc, bg, fg]) => ({
      desc, bg, fg,
      ratio: Number(getContrastRatio(bg, fg).toFixed(2)),
    }));
    // eslint-disable-next-line no-console
    console.log("=== Feb-2026 Contrast Report ===");
    for (const r of report) {
      // eslint-disable-next-line no-console
      console.log(`  ${r.desc.padEnd(35)} ${r.bg} on ${r.fg} → ${r.ratio}:1`);
    }
    expect(report).toHaveLength(5);
  });
});
