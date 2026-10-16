/**
 * EBITDA-SOFT-ADD · Feb-2026 — FE headline swap (Option 3).
 *
 * Phase 7 Commit 2. Paired with BE 73f5fbc9a which added
 * ``ebitda`` as an additive field on every EBIT endpoint response.
 *
 * Scope guards:
 *   * Headline metric renamed to EBITDA on the two primary UI
 *     surfaces (EbitPanel header + total row; EbitTile dashboard
 *     value). EBIT stays visible as a secondary chip for operators
 *     who track both.
 *   * Tooltip on the EBITDA label carries the user-provided copy:
 *     "EBITDA: Earnings Before Interest, Taxes, Depreciation, and
 *      Amortization. A financial metric used to measure a company's
 *      overall operational profitability and core earning power."
 *   * Legacy payloads where ``ebitda`` is null fall back to
 *     ``ebit + depreciation`` so the UI never shows $NaN.
 *   * Pre-TD-59 testids (ebit-total-value, ebit-panel-title,
 *     dashboard-ebit-tile, dashboard-ebit-tile-value) are
 *     PRESERVED so Playwright scripts targeting them keep working.
 *
 * Covers (8 cases):
 *   1. EbitPanel header renders "EBITDA" (not "EBIT") on the H2.
 *   2. EbitPanel header tooltip carries the exact user-provided
 *      definition copy.
 *   3. EbitPanel total row uses "EBITDA (effective)" as the label
 *      with EBITDA as the primary number + EBIT as the secondary
 *      line below.
 *   4. EbitPanel total row falls back to ``ebit + depreciation``
 *      when the backend payload has null ebitda (legacy
 *      pre-TD-59 compat).
 *   5. EbitTile dashboard label shows the full "Earnings Before
 *      Interest, Taxes, Depreciation & Amortization" expansion
 *      (not the pre-TD-59 "Earnings Before Interest & Taxes").
 *   6. EbitTile headline value renders EBITDA (new ``dashboard-
 *      ebitda-tile-value`` testid).
 *   7. EbitTile keeps the EBIT secondary chip under the
 *      pre-TD-59 ``dashboard-ebit-tile-value`` testid.
 *   8. EbitTile delta % is computed against EBITDA (NOT EBIT) —
 *      regression test for the headline-metric swap.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const PANEL = fs.readFileSync(
  path.resolve(__dirname, "../components/admin/EbitPanel.jsx"),
  "utf8",
);
const TILE = fs.readFileSync(
  path.resolve(__dirname, "../components/dashboard/EbitTile.jsx"),
  "utf8",
);


describe("EBITDA-SOFT-ADD · FE source-parse", () => {
  // ─────────────────────────────────────────────────────────────
  // EbitPanel header + tooltip
  // ─────────────────────────────────────────────────────────────
  it("EbitPanel header H2 reads EBITDA (not EBIT)", () => {
    // Find the h2 ...>EBITDA</h2> literal.
    expect(PANEL).toMatch(
      /<h2[^>]*data-testid="ebit-panel-title"[^>]*>\s*EBITDA\s*<\/h2>/,
    );
    // And no stray <h2>EBIT</h2> stays behind.
    expect(PANEL).not.toMatch(
      /<h2[^>]*>\s*EBIT\s*<\/h2>/,
    );
  });

  it("EbitPanel header tooltip carries the exact user-provided copy", () => {
    expect(PANEL).toContain(
      "EBITDA: Earnings Before Interest, Taxes, Depreciation, " +
      "and Amortization. A financial metric used to measure a " +
      "company's overall operational profitability and core " +
      "earning power.",
    );
  });

  // ─────────────────────────────────────────────────────────────
  // EbitPanel total row
  // ─────────────────────────────────────────────────────────────
  it("EbitPanel total row label swapped to 'EBITDA (effective)'", () => {
    expect(PANEL).toContain("EBITDA (effective)");
    // The pre-TD-59 "EBIT (effective)" label is gone.
    expect(PANEL).not.toContain("EBIT (effective)");
  });

  it("EbitPanel total value falls back to ebit + depreciation when ebitda is null", () => {
    // Fallback logic locked in source: ``effective.ebitda != null
    // ? effective.ebitda : (Number(effective.ebit || 0) +
    // Number(effective.depreciation || 0))``.
    expect(PANEL).toMatch(
      /effective\.ebitda\s*!=\s*null[\s\S]*effective\.ebit[\s\S]*effective\.depreciation/,
    );
    // Primary total testid now points at ebitda; legacy ebit-
    // total-value stays visible as the secondary chip.
    expect(PANEL).toContain('data-testid="ebitda-total-value"');
    expect(PANEL).toContain('data-testid="ebit-total-value"');
  });

  // ─────────────────────────────────────────────────────────────
  // EbitTile dashboard
  // ─────────────────────────────────────────────────────────────
  it("EbitTile label shows the full EBITDA expansion (not the pre-TD-59 'Interest & Taxes')", () => {
    expect(TILE).toContain(
      "Earnings Before Interest, Taxes, Depreciation",
    );
    // Pre-TD-59 label is gone.
    expect(TILE).not.toContain("Earnings Before Interest &amp; Taxes");
  });

  it("EbitTile headline renders EBITDA via dashboard-ebitda-tile-value testid", () => {
    expect(TILE).toContain('data-testid="dashboard-ebitda-tile-value"');
    // Headline value shows curEbitda, not curEbit, under the new
    // testid.
    expect(TILE).toMatch(
      /data-testid="dashboard-ebitda-tile-value"[\s\S]*fmtUSD\(curEbitda\)/,
    );
  });

  it("EbitTile preserves the pre-TD-59 dashboard-ebit-tile-value testid as the EBIT secondary chip", () => {
    // Backward-compat for Playwright scripts: the old testid is
    // still queryable, but now wraps the EBIT secondary chip
    // (EBIT ${fmtUSD(curEbit)}).
    expect(TILE).toContain('data-testid="dashboard-ebit-tile-value"');
    // The pre-TD-59 contract wrapped curEbit directly in the
    // primary ``text-3xl`` display div. Post-TD-59, the testid
    // sits on the inline-chip span.
    expect(TILE).toMatch(
      /data-testid="dashboard-ebit-tile-value"[\s\S]*fmtUSD\(curEbit\)/,
    );
  });

  it("EbitTile delta % is computed against EBITDA (headline metric swap)", () => {
    // Pre-TD-59: ``delta = pctDelta(curEbit, prev?.ebit)``.
    // Post-TD-59: ``delta = pctDelta(curEbitda, _prevEbitda)``.
    expect(TILE).toMatch(
      /const delta = pctDelta\(curEbitda,\s*_prevEbitda\)/,
    );
    // The pre-TD-59 EBIT-based delta line is gone.
    expect(TILE).not.toMatch(
      /const delta = pctDelta\(curEbit,\s*prev\?\.ebit\)/,
    );
  });
});
