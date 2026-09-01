/**
 * Phase I2 · Feb-2026 — AnalyticsMonthlyPage YoY drop badge.
 *
 * Source-body contract check (mirrors the H6 pattern). Locks the
 * invariants for the ``↓ XX% YoY`` badge that appears next to any
 * Top-3 charge-template row whose current-month revenue is at least
 * 20% below the same month last year.
 *
 *   - Threshold is strictly > 20% (not ≥) so a 20% drop stays quiet.
 *   - Prior-year revenue is sourced from ``prior_year_revenue_usd``.
 *   - Badge is scoped to rows with cur > 0 AND prior > 0 AND cur < prior.
 *   - Row testid pattern: ``templates-yoy-<template_id>``.
 *   - Badge tone uses the H6 red palette (#FEE2E2 / #991B1B).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(),
    "src/pages/admin/AnalyticsMonthlyPage.jsx"),
  "utf-8",
);


describe("AnalyticsMonthlyPage · I2 YoY drop badge", () => {
  it("row iteration reads current + prior-year revenue in USD", () => {
    expect(SRC).toMatch(/Number\(t\.revenue_contribution_usd/);
    expect(SRC).toMatch(/Number\(t\.prior_year_revenue_usd/);
  });

  it("YoY drop math is (prior - cur) / prior expressed as a percentage", () => {
    expect(SRC).toMatch(
      /Math\.round\(\(\(prior\s*-\s*cur\)\s*\/\s*prior\)\s*\*\s*100\)/,
    );
  });

  it("badge renders only when the drop exceeds 20%", () => {
    // Guard is strictly > 20 so a 20% drop or smaller stays quiet.
    expect(SRC).toMatch(/dropPct\s*>\s*20/);
  });

  it("badge is gated on cur > 0 AND prior > 0 AND cur < prior", () => {
    expect(SRC).toMatch(
      /cur\s*>\s*0\s*&&\s*prior\s*>\s*0\s*&&\s*cur\s*<\s*prior/,
    );
  });

  it("badge testid pattern uses the template id", () => {
    expect(SRC).toMatch(
      /data-testid=\{`templates-yoy-\$\{t\.template_id\}`\}/,
    );
  });

  it("badge uses the H6 red palette", () => {
    // ↓ XX% YoY pill: light-red bg (#FEE2E2) + dark-red fg (#991B1B).
    const idx = SRC.indexOf("templates-yoy-");
    expect(idx).toBeGreaterThan(-1);
    const block = SRC.slice(Math.max(0, idx - 400), idx + 300);
    expect(block).toMatch(/#FEE2E2/);
    expect(block).toMatch(/#991B1B/);
  });

  it("badge copy uses the ``↓ NN% YoY`` shorthand", () => {
    expect(SRC).toMatch(/↓\s*\{dropPct\}%\s*YoY/);
  });
});


describe("I2 · regression guards for the H6 templates card", () => {
  it("preserves the ChargeTemplatesCard structure + top-3 iteration", () => {
    // Card component takes ``testid`` prop and renders ``data-testid`` internally.
    expect(SRC).toMatch(/testid="analytics-card-templates"/);
    expect(SRC).toMatch(/top\.map\(\(t\)\s*=>/);
  });

  it("does not remove the existing revenue_contribution_usd rendering", () => {
    expect(SRC).toMatch(
      /_fmtUsd\(t\.revenue_contribution_usd\)/,
    );
  });
});
