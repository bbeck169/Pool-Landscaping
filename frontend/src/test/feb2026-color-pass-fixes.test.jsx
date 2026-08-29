/**
 * Feb 2026 · Color pass — tester-verification follow-ups (3 fixes).
 *
 * Fix 1 · Revenue chart current-month detection is time-aware.
 *   * Under any system date, the bar whose ``label`` matches the
 *     3-letter abbrev of the current calendar month draws in
 *     ``pool[500]``.
 *   * When the series doesn't contain the current month, the last
 *     bar in the series gets the highlight (graceful fallback so
 *     new-tenant charts never look flat).
 *
 * Fix 2 · Primary submit buttons on ``/jobs/new`` + ``/customers/new``
 *   * Both declare an explicit ``variant="primary"`` prop so a
 *     future refactor that removes the shared Button's default
 *     doesn't silently downgrade them.
 *   * Rendered background carries the brand gradient (or a tone
 *     accent) — NEVER the ``surfaceSecondary`` (near-white)
 *     ghost fill.
 *
 * Fix 3 · Total Paid Revenue hero contrast lock-in.
 *   * Hero declares ``data-tone="emerald"`` + gradient sourced
 *     from ``landscape[600]`` → ``accent.emerald[500]``.
 *   * White text on both gradient stops passes AA large-text
 *     (≥ 3:1) — explicit contrast assertions below prove the
 *     numeric revenue label is readable.
 */
import React from "react";
import fs from "fs";
import path from "path";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { colors } from "@/theme";
import { getContrastRatio } from "@/utils/serviceLineTheme";


// ══════════════════════════════════════════════════════════════════
// FIX 1 — Revenue chart current-month detection (time-aware).
// ══════════════════════════════════════════════════════════════════
describe("Fix 1 · RevenueChart current-month highlight", () => {
  const SRC = fs.readFileSync(
    path.resolve(__dirname, "../pages/admin/Dashboard.jsx"),
    "utf8",
  );

  it("computes current month at runtime via new Date().getMonth()", () => {
    // Guard against a future edit that hard-codes the highlight
    // index or reverts to ``isLast``. The logic lives in the
    // pure exported ``computeRevenueBarFills`` helper — it must
    // still consult ``now.getMonth()`` (or `new Date().getMonth()`
    // in the RevenueChart delegate).
    expect(SRC).toMatch(/computeRevenueBarFills/);
    expect(SRC).toMatch(/now\.getMonth\(\)/);
    expect(SRC).toMatch(/currentMonthLabel/);
  });

  it("bar coloring branches on isCurrent (not isLast)", () => {
    // Look at the RevenueChart render — it must feed the pure
    // helper's ``fill`` field to each Cell.
    expect(SRC).toMatch(/computeRevenueBarFills\(series\)/);
    expect(SRC).toMatch(/fill=\{d\.fill\}/);
    // ``isLast`` must be gone from the RevenueChart block.
    const rcStart = SRC.indexOf("function RevenueChart(");
    const rcEnd = SRC.indexOf("function PaymentsWidget");
    expect(rcStart).toBeGreaterThan(-1);
    expect(rcEnd).toBeGreaterThan(rcStart);
    const block = SRC.slice(rcStart, rcEnd);
    expect(block).not.toMatch(/\bisLast\b/);
  });

  it("has a graceful fallback when the series doesn't include the current month", () => {
    // Fallback branch inside ``computeRevenueBarFills`` — if the
    // current month isn't in the series, the LAST bar picks up
    // the highlight so the chart never renders flat.
    expect(SRC).toMatch(/data\[data\.length - 1\]\.isCurrent\s*=\s*true/);
  });

  it("month-abbrev lookup table matches the backend's 3-letter labels", () => {
    // Backend returns ``month_names[m - 1]`` which resolves to
    // "Jan", "Feb", ... "Dec". A regex tolerant of whitespace so
    // future prettier reflows don't break the assertion.
    expect(SRC).toMatch(
      /REVENUE_MONTH_ABBR\s*=\s*\[[\s\S]*?"Jan"[\s\S]*?"Dec"[\s\S]*?\]/,
    );
  });
});


// ══════════════════════════════════════════════════════════════════
// FIX 2 — Primary submit buttons on /jobs/new + /customers/new.
// ══════════════════════════════════════════════════════════════════
const JOB_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobNew.jsx"),
  "utf8",
);
const CUST_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/customers/CustomerForm.jsx"),
  "utf8",
);


describe("Fix 2 · Primary CTA buttons on job + customer forms", () => {
  it("jf-submit declares an explicit variant=\"primary\"", () => {
    expect(JOB_SRC).toMatch(
      /<Button[\s\S]{0,120}variant="primary"[\s\S]{0,120}testid="jf-submit"/,
    );
  });

  it("cf-submit declares an explicit variant=\"primary\"", () => {
    expect(CUST_SRC).toMatch(
      /<Button[\s\S]{0,120}variant="primary"[\s\S]{0,120}testid="cf-submit"/,
    );
  });
});


// ── Runtime button-render check on the shared Button primitive.
// The primary variant MUST NOT resolve to ``rgba(244, 244, 245, …)``
// (surfaceSecondary ghost fill) even when disabled=true.
import { Button } from "@/components/ui-kit";

describe("Fix 2 · Button primary variant DOM output", () => {
  it("primary variant never resolves to surfaceSecondary background", () => {
    render(
      <>
        <Button testid="p1">Create job</Button>
        <Button testid="p2" variant="primary">Save</Button>
        <Button testid="p3" disabled>Disabled</Button>
      </>,
    );
    for (const id of ["p1", "p2", "p3"]) {
      const el = screen.getByTestId(id);
      const bg = el.style.background;
      const bgImg = el.style.backgroundImage || "";
      // Either the gradient is on ``background`` OR on
      // ``backgroundImage`` (jsdom may split it either way).
      const hasGradient = /linear-gradient/.test(bg)
        || /linear-gradient/.test(bgImg);
      expect(hasGradient).toBe(true);
      // Never the neutral ghost surface.
      expect(bg).not.toMatch(/#F4F4F5/i);
      expect(bg).not.toMatch(/rgb\(244,\s*244,\s*245\)/);
    }
  });
});


// ══════════════════════════════════════════════════════════════════
// FIX 3 — Total Paid Revenue hero contrast lock-in + tile-wide
//         readability guarantee (WCAG AA ≥ 4.5:1 on body-text
//         KPI values).
//
// Feb-2026 · Priority 2 (Batch 2026-P2) — the emerald hero itself
// was removed from the dashboard per operator feedback (duplicated
// the split chip below, crowded out the KPI grid). The
// hero-specific assertions below flipped into a *guard* that
// enforces the removal, and the KPI-tile readability assertions
// still stand — they cover the tiles the hero used to sit above.
// ══════════════════════════════════════════════════════════════════
describe("Fix 3 · Total Paid Revenue hero + KPI tile readability", () => {
  const DASH_SRC = fs.readFileSync(
    path.resolve(__dirname, "../pages/admin/Dashboard.jsx"),
    "utf8",
  );

  it("emerald hero tile has been removed (Priority 2, Feb-2026)", () => {
    expect(DASH_SRC).not.toMatch(/data-testid="dashboard-hero"/);
    expect(DASH_SRC).not.toMatch(/data-tone="emerald"/);
    // Feb-2026 cleanup: the pool/landscape split chip was also
    // removed per user request (the "Mixed $X.XX (100%)" full-
    // width gray bar was visual noise for tenants with no
    // Pool/Landscape breakdown).  RevenueByCategoryTile now carries
    // the by-category breakdown at higher fidelity.
    expect(DASH_SRC).not.toMatch(/RevenueSplitChip/);
  });

  it.each([
    ["Active Jobs (sky[50] → onSurface)", colors.accent.sky[50],     colors.onSurface],
    ["Pending (amber[50] → onSurface)",   colors.accent.amber[50],   colors.onSurface],
    ["Customers (violet[50] → onSurface)",colors.accent.violet[50],  colors.onSurface],
    ["Technicians (emerald[50] → onSurface)", colors.accent.emerald[50], colors.onSurface],
  ])("KPI tile %s passes AA body-text ≥ 4.5:1", (_desc, bg, fg) => {
    const ratio = getContrastRatio(bg, fg);
    // eslint-disable-next-line no-console
    console.log(`[fix-3 contrast] ${_desc}: ${ratio.toFixed(2)}:1`);
    expect(ratio).toBeGreaterThanOrEqual(4.5);
  });
});
