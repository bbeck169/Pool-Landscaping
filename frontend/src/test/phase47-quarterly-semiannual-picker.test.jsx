/**
 * Feb-2026 · P47 — quarterly + semi_annual recurrence picker pins.
 *
 * Directly asserts the exported option arrays on ``RecurringJobs.jsx``
 * and ``JobNew.jsx`` include both new values with the agreed labels.
 * A future refactor that drops either value fails the pin immediately.
 */
import { describe, it, expect } from "vitest";


describe("Recurrence pickers · P47", () => {
  it("RecurringJobs.jsx FREQ_OPTS exposes quarterly + semi_annual",
      async () => {
    const mod = await import(
      "@/pages/admin/RecurringJobs.jsx?raw");
    const src = mod.default;
    expect(src).toMatch(/value:\s*"quarterly"/);
    expect(src).toMatch(
      /label:\s*"Quarterly \(every 3 months\)"/);
    expect(src).toMatch(/value:\s*"semi_annual"/);
    expect(src).toMatch(
      /label:\s*"Semi-annual \(every 6 months\)"/);
  });

  it("JobNew.jsx CADENCE_OPTS exposes quarterly + semi_annual",
      async () => {
    const mod = await import(
      "@/pages/jobs/JobNew.jsx?raw");
    const src = mod.default;
    expect(src).toMatch(/k:\s*"quarterly"/);
    expect(src).toMatch(
      /label:\s*"Quarterly \(every 3 months\)"/);
    expect(src).toMatch(/k:\s*"semi_annual"/);
    expect(src).toMatch(
      /label:\s*"Semi-annual \(every 6 months\)"/);
  });
});
