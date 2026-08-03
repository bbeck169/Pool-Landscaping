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

  describe("reports.tsx · three parity tiles at the top", () => {
    const src = R("mobile/app/reports.tsx");

    it("mounts all three testIDs and routes each to the expected screen", () => {
      expect(src).toMatch(/testID="admin-tile-revenue-by-category"[\s\S]{0,500}\/income-by-category/);
      expect(src).toMatch(/testID="admin-tile-revenue-by-service"[\s\S]{0,500}\/reports\/revenue-by-service/);
      expect(src).toMatch(/testID="admin-tile-forecast-revenue"[\s\S]{0,500}\/reports\/forecast/);
    });

    it("tiles appear in the required order and BEFORE the KPI grid", () => {
      const idxCategory = src.indexOf('testID="admin-tile-revenue-by-category"');
      const idxService  = src.indexOf('testID="admin-tile-revenue-by-service"');
      const idxForecast = src.indexOf('testID="admin-tile-forecast-revenue"');
      const idxKpi      = src.indexOf('styles.grid');
      expect(idxCategory).toBeGreaterThan(-1);
      expect(idxService).toBeGreaterThan(idxCategory);
      expect(idxForecast).toBeGreaterThan(idxService);
      expect(idxKpi).toBeGreaterThan(idxForecast);
    });

    it("removes the inline Revenue by Service chart (tile is the entry point now)", () => {
      // The block previously had ``<Text style={styles.cardTitle}>Revenue by Service</Text>``.
      // The tile itself uses a different property (``styles.tileLabel``),
      // so no ``cardTitle`` with that literal text should remain.
      expect(src).not.toMatch(/style=\{styles\.cardTitle\}>Revenue by Service</);
      // The now-unused svcMax variable is gone.
      expect(src).not.toMatch(/const\s+svcMax\s*=/);
    });

    it("regression · legacy KPI + Technician Performance sections still render", () => {
      expect(src).toMatch(/<Kpi[^>]*label="Revenue"/);
      expect(src).toMatch(/Technician Performance/);
      expect(src).toMatch(/testID={`report-tech-/);
    });
  });
});
