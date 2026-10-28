/**
 * Phase (Feb-2026) · mobile revenue-tile parity.
 *
 * Locks the three new admin-facing entry points at the top of
 * ``mobile/app/reports.tsx``:
 *
 *   1. Revenue by Category (reuses the existing full-parity
 *      ``mobile/app/income-by-category.tsx`` screen — same
 *      ``/api/finances/income-by-category`` endpoint the web
 *      ``IncomeByCategoryPage`` hits).
 *   2. Revenue by Service (extracted from the previous inline
 *      chart in ``reports.tsx`` into a dedicated
 *      ``mobile/app/reports/revenue-by-service.tsx`` — data
 *      source is the shared ``GET /api/reports`` payload).
 *   3. Forecast Revenue (new ``mobile/app/reports/forecast.tsx``
 *      mirroring the web ``Forecast.jsx`` — ``/reports/forecast``
 *      + ``/reports/forecast-cards``). Ships a five-chip filter
 *      row: Today, Tomorrow, This Week, This Month, Custom Range.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, "../../..", p), "utf-8");
const E = (p) => fs.existsSync(path.resolve(__dirname, "../../..", p));

describe("Phase (Feb-2026) · mobile revenue-tile parity", () => {
  describe("Screen files", () => {
    it("reuses existing income-by-category screen for Revenue by Category", () => {
      expect(E("mobile/app/income-by-category.tsx")).toBe(true);
      const src = R("mobile/app/income-by-category.tsx");
      // Web parity — same endpoint, same title.
      expect(src).toMatch(/\/finances\/income-by-category/);
      expect(src).toMatch(/title="Income by Category"/);
    });

    it("creates mobile/app/reports/revenue-by-service.tsx", () => {
      expect(E("mobile/app/reports/revenue-by-service.tsx")).toBe(true);
      const src = R("mobile/app/reports/revenue-by-service.tsx");
      // Uses the shared reports endpoint (mirrors admin/Dashboard.jsx
      // and BusinessSummary.jsx which both source ``revenue_by_service``).
      expect(src).toMatch(/api\.get\(["']\/reports["']\)/);
      expect(src).toMatch(/<Header[\s\S]*?title="Revenue by Service"/);
      expect(src).toMatch(/testID="revenue-by-service-page"/);
    });

    it("creates mobile/app/reports/forecast.tsx", () => {
      expect(E("mobile/app/reports/forecast.tsx")).toBe(true);
      const src = R("mobile/app/reports/forecast.tsx");
      expect(src).toMatch(/<Header[\s\S]*?title="Forecast Revenue"/);
      expect(src).toMatch(/testID="forecast-revenue-page"/);
      // Web endpoints for both the timeseries and companion cards.
      expect(src).toMatch(/\/reports\/forecast\?range=/);
      expect(src).toMatch(/\/reports\/forecast-cards/);
    });
  });

  describe("Forecast screen · five preset filter chips", () => {
    const src = R("mobile/app/reports/forecast.tsx");

    it("renders all five filter chip testIDs", () => {
      expect(src).toMatch(/testID:\s*"forecast-filter-today"/);
      expect(src).toMatch(/testID:\s*"forecast-filter-tomorrow"/);
      expect(src).toMatch(/testID:\s*"forecast-filter-this-week"/);
      expect(src).toMatch(/testID:\s*"forecast-filter-this-month"/);
      expect(src).toMatch(/testID:\s*"forecast-filter-custom"/);
    });

    it("defaults the selected preset to 'week' (This Week)", () => {
      expect(src).toMatch(/useState<RangeKey>\(\s*["']week["']\s*\)/);
    });

    it("Custom Range chip opens a picker modal", () => {
      // The custom-range picker modal is testID='forecast-custom-range-picker'.
      expect(src).toMatch(/testID="forecast-custom-range-picker"/);
      // Uses the existing @react-native-community/datetimepicker dep — no
      // new dependency added.
      expect(src).toMatch(
        /from ["']@react-native-community\/datetimepicker["']/,
      );
    });

    it("API call includes date range params for custom mode", () => {
      // Web parity — ``?range=custom&date_from&date_to`` for a bespoke
      // window, plain ``?range={preset}`` otherwise.
      expect(src).toMatch(/\?range=custom&date_from=\$\{customFrom\}&date_to=\$\{customTo\}/);
      expect(src).toMatch(/\?range=\$\{preset\}/);
    });

    it("shows a busy indicator while the fetch re-runs", () => {
      expect(src).toMatch(/testID="forecast-refetching"/);
    });
  });

  describe("Revenue-by-Service screen · sort + export", () => {
    const src = R("mobile/app/reports/revenue-by-service.tsx");
    it("offers three sort chips and a CSV export", () => {
      expect(src).toMatch(/testID={`rbs-sort-\$\{k\}`}/);
      expect(src).toMatch(/testID="rbs-export"/);
    });
  });

  describe("Dashboard · three parity tiles at the top (correction Feb-2026)", () => {
    const src = R("mobile/app/(app)/index.tsx");
    const reports = R("mobile/app/reports.tsx");

    // ZZ-A mobile · Phase 39A (b9a3338c4) replaced the 3 shortcut tiles with
    // the web-parity Revenue insights donuts; mobile jest
    // phase39a-dashboard-revenue-insights.test.tsx locks them as gone. The 3
    // screens stay reachable from the drawer (adminNav.ts).
    it("Phase 39A · the three shortcut tiles are gone (screens stay drawer-reachable)", () => {
      for (const id of ["admin-tile-revenue-by-category", "admin-tile-revenue-by-service", "admin-tile-forecast-revenue", "dashboard-revenue-tiles"]) {
        expect(src).not.toContain(`testID="${id}"`);
      }
      const nav = R("mobile/src/nav/adminNav.ts");
      expect(nav).toMatch(/route:\s*"\/income-by-category"/);
      expect(nav).toMatch(/route:\s*"\/reports\/revenue-by-service"/);
      expect(nav).toMatch(/route:\s*"\/reports\/forecast"/);
    });

    it("Revenue insights section renders BEFORE Weather / Budget Health", () => {
      const idxSection = src.indexOf('testID="revenue-tiles-section"');
      expect(idxSection).toBeGreaterThan(-1);
      expect(src.indexOf("<WeatherWidget")).toBeGreaterThan(idxSection);
      expect(src.indexOf("<BudgetHealthCard")).toBeGreaterThan(idxSection);
    });

    it("Revenue insights section is gated to super_admin / admin (isRevenueAdmin)", () => {
      // Phase 39A · backend revenue endpoints are admin / super_admin only.
      expect(src).toMatch(/const isRevenueAdmin = user\?\.role === "super_admin" \|\| user\?\.role === "admin";/);
      expect(src).toMatch(/\{isRevenueAdmin \? \(\s*<View style=\{styles\.revenueSection\} testID="revenue-tiles-section">/);
    });

    it("Reports page no longer references the three tile testIDs (moved, not duplicated)", () => {
      expect(reports).not.toMatch(/testID="admin-tile-revenue-by-category"/);
      expect(reports).not.toMatch(/testID="admin-tile-revenue-by-service"/);
      expect(reports).not.toMatch(/testID="admin-tile-forecast-revenue"/);
    });

    it("regression · Reports page still renders KPIs + Technician Performance", () => {
      expect(reports).toMatch(/<Kpi[^>]*label="Revenue"/);
      expect(reports).toMatch(/Technician Performance/);
      expect(reports).toMatch(/testID={`report-tech-/);
    });

    it("regression · Reports page keeps the inline Revenue by Service chart removed", () => {
      // The extracted screen lives at /reports/revenue-by-service — the
      // old inline card must stay deleted (svcMax gone, cardTitle text gone).
      expect(reports).not.toMatch(/style=\{styles\.cardTitle\}>Revenue by Service</);
      expect(reports).not.toMatch(/const\s+svcMax\s*=/);
    });
  });
});
