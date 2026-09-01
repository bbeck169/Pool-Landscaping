/**
 * Phase I2 · Feb-2026 — RevenueForecastTile MoM badge.
 *
 * Source-body contract check (mirrors the H4 / H10 pattern). Locks
 * the invariants for the tile-local MoM comparison badge that
 * renders only on the monthly tabs (this_month | next_month).
 *
 *   - Badge is scoped to the two monthly tabs.
 *   - Prior-period fetch is triggered from the tab-change effect.
 *   - Badge testid + tone thresholds are stable.
 *   - Prior-period math: this_month vs previous month, next_month vs
 *     this month.
 *   - Badge is hidden silently on non-monthly tabs or prior-fetch
 *     failure (the fetch's ``.catch`` sets ``momPrior`` to null).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(),
    "src/components/dashboard/RevenueForecastTile.jsx"),
  "utf-8",
);


describe("RevenueForecastTile · I2 MoM badge", () => {
  it("declares a momPrior state hook alongside the tab-local state", () => {
    expect(SRC).toMatch(/const\s*\[momPrior,\s*setMomPrior\]\s*=\s*useState\(null\)/);
  });

  it("badge renders only on the monthly tabs (this_month / next_month)", () => {
    // Guard reads: activeTab === "this_month" || activeTab === "next_month"
    expect(SRC).toMatch(
      /activeTab\s*===\s*"this_month"\s*\|\|\s*activeTab\s*===\s*"next_month"/,
    );
  });

  it("badge testid is ``revenue-forecast-mom-badge``", () => {
    expect(SRC).toMatch(/data-testid="revenue-forecast-mom-badge"/);
  });

  it("prior-period fetch is triggered for the two monthly tabs only", () => {
    // The tab-change effect kicks off a second GET when the active
    // tab is monthly, and clears momPrior otherwise.
    expect(SRC).toMatch(
      /if\s*\(activeTab\s*===\s*"this_month"\s*\|\|\s*activeTab\s*===\s*"next_month"\)/,
    );
    expect(SRC).toMatch(/setMomPrior\(null\)/);
  });

  it("this_month compares vs the previous calendar month (offset = -1)", () => {
    // The offset ternary must produce -1 for this_month and 0 for
    // next_month so the ``first`` calendar-month math lines up.
    expect(SRC).toMatch(
      /activeTab\s*===\s*"this_month"\s*\?\s*-1\s*:\s*0/,
    );
  });

  it("badge label wording covers +, -, and 'Flat vs Last Month'", () => {
    // Delta thresholding uses |delta| < 50 for the flat bucket.
    expect(SRC).toMatch(/Math\.abs\(delta\)\s*<\s*50/);
    expect(SRC).toMatch(/Flat vs Last Month/);
    expect(SRC).toMatch(/vs Last Month/);
  });

  it("tone map covers green / red / gray fills", () => {
    // Positive = green (#DCFCE7), negative = red (#FEE2E2), flat = gray (#F1F5F9)
    expect(SRC).toMatch(/#DCFCE7/);
    expect(SRC).toMatch(/#FEE2E2/);
    expect(SRC).toMatch(/#F1F5F9/);
  });

  it("prior-fetch failure silently clears momPrior (no toast)", () => {
    // The .catch on the prior-period fetch must fall back to null
    // so the badge disappears gracefully — never surface an error.
    expect(SRC).toMatch(/\.catch\(\(\)\s*=>\s*setMomPrior\(null\)\)/);
  });
});


describe("I2 · regression guards for the H10 tab set", () => {
  it("preserves the 5-tab quick-view surface (today | tomorrow | week | this_month | next_month)", () => {
    expect(SRC).toMatch(/key:\s*"today"/);
    expect(SRC).toMatch(/key:\s*"tomorrow"/);
    expect(SRC).toMatch(/key:\s*"week"/);
    expect(SRC).toMatch(/key:\s*"this_month"/);
    expect(SRC).toMatch(/key:\s*"next_month"/);
  });

  it("keeps the recurring_jobs caption clause untouched", () => {
    expect(SRC).toMatch(/recurring_job_count/);
  });
});
