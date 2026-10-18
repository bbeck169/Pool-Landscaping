/**
 * TD-68 · Feb-2026 — Portal theme bundle structural locks.
 *
 * Operator-ruled theme parity: `/portal/service-reports` (LIST),
 * `/portal/service-reports/:id` (DETAIL), and `/portal/reviews`
 * must all render inside the shared `PortalPageShell` white-card
 * chrome (pixel-matched to the `/portal/home` hero card). Pre-
 * TD-68 these three surfaces rendered on raw dark-navy page bgs
 * with no white chrome break — operator reported it as "all navy
 * unlike home".
 *
 * This file pins the three contracts at source level so a future
 * refactor can't silently un-shell any of them. Source-grep
 * assertions mirror the P49 restyle test convention.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");

const HOME_SRC    = R("../pages/portal/PortalHome.jsx");
const SR_SRC      = R("../pages/portal/PortalServiceReports.jsx");
const REVIEWS_SRC = R("../pages/portal/PortalReviews.jsx");


describe("TD-68 · Portal theme bundle · shared PortalPageShell parity", () => {

  it("portal-home still carries the white-card chrome marker (parity source-of-truth)", () => {
    // The LIST / DETAIL / REVIEWS wraps are meaningful only if
    // PortalHome itself still paints the white dashboard card
    // the operator asked us to parity-match. If this ever flips,
    // the parity contract is broken from the OTHER side first.
    expect(HOME_SRC).toMatch(/portal-dashboard-card/);
    expect(HOME_SRC).toMatch(/backgroundColor:\s*["']#FFFFFF["']/);
  });

  it("LIST (PortalServiceReports) imports and uses PortalPageShell", () => {
    expect(SR_SRC).toMatch(
      /import\s+PortalPageShell\s+from\s+["']@\/components\/portal\/PortalPageShell["']/,
    );
    // The LIST export's top-of-return paints the shell.
    expect(SR_SRC).toMatch(/<PortalPageShell>\s*\n\s*<div\s+data-testid="portal-service-reports"/);
  });

  it("DETAIL (PortalServiceReportDetail) wraps the loaded branch in PortalPageShell", () => {
    // The loaded branch keeps the bg-slate-50 outer wrapper for
    // the pre-existing P49 restyle test; the PortalPageShell wrap
    // nests inside it so content paints on white chrome against
    // the lightened-navy backdrop.
    expect(SR_SRC).toMatch(
      /data-testid="portal-service-report-detail-root"\s*\n\s*>\s*\n\s*<PortalPageShell>\s*\n\s*<div\s+data-testid="portal-service-report-detail"/,
    );
  });

  it("DETAIL error + loading branches each wrap in PortalPageShell with distinct testids", () => {
    // Error branch — surfaces `portal-service-report-error`
    // INSIDE a PortalPageShell wrap; no `portal-service-report-detail`
    // testid on this branch (the Rules-of-Hooks test suite pins
    // the loaded branch as the only owner of that testid).
    expect(SR_SRC).toMatch(/<PortalPageShell>\s*\n\s*<div>\s*\n\s*<button[\s\S]*?data-testid="portal-service-report-back"/);
    // Loading branch — surfaces the Phase 18b skeleton inside
    // the shell + a dedicated `portal-service-report-loading`
    // testid for addressability.
    expect(SR_SRC).toMatch(
      /<PortalPageShell>\s*\n\s*<div\s+data-testid="portal-service-report-loading">\s*\n\s*<Skeleton/,
    );
  });

  it("REVIEWS (PortalReviews) wraps the main return in PortalPageShell", () => {
    expect(REVIEWS_SRC).toMatch(
      /import\s+PortalPageShell\s+from\s+["']@\/components\/portal\/PortalPageShell["']/,
    );
    expect(REVIEWS_SRC).toMatch(/<PortalPageShell\s+testid="portal-reviews-page">/);
    // Negative lock — the ReviewThankYou public branch no longer
    // double-wraps itself in a nested shell (the outer-return
    // wrap already owns the chrome).
    expect(REVIEWS_SRC).not.toMatch(
      /<PortalPageShell>\s*\n\s*<div\s+className="rounded-2xl p-6 text-center"\s*\n\s*style=\{\{\s*\n\s*backgroundColor:\s*colors\.surface,\s*\n\s*border:\s*`1px solid \$\{colors\.border\}`,\s*\n\s*\}\}\s*\n\s*data-testid="portal-review-thankyou-google"/,
    );
  });

});
