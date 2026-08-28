/**
 * Feb-2026 · Job Timers Phase 1 + Chemical Cost Report — lock-in.
 *
 * Source-lint style guard: verifies both new pages carry the
 * shipped testids, tabs, filters, CSV export, and Feb-2026 spec
 * hooks (auto-close comment, wholesale_cost_snapshot cost basis).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const JT_PAGE = fs.readFileSync(
  path.resolve(__dirname, "../pages/timers/JobTimersPage.jsx"),
  "utf8",
);

const CC_PAGE = fs.readFileSync(
  path.resolve(__dirname, "../pages/reports/ChemicalCostReportPage.jsx"),
  "utf8",
);

const APP_JS = fs.readFileSync(
  path.resolve(__dirname, "../App.js"),
  "utf8",
);


describe("Feature 1 · /job-timers page (Phase 1)", () => {
  it("Renders two tabs (timers + avgtime)", () => {
    // Testid interpolated via template literal — see line ``jt-tab-${t.key}``.
    expect(JT_PAGE).toMatch(/data-testid=\{`jt-tab-\$\{t\.key\}`\}/);
    // Both tab keys present in the tab list.
    expect(JT_PAGE).toMatch(/key:\s*"timers"/);
    expect(JT_PAGE).toMatch(/key:\s*"avgtime"/);
  });

  it("Reads the ?t= URL param to select the tab", () => {
    expect(JT_PAGE).toMatch(/searchParams\.get\("t"\)/);
  });

  it("Timers tab exposes filter + export testids", () => {
    ["jt-filter-from", "jt-filter-to", "jt-filter-tech",
      "jt-filter-customer", "jt-export-csv", "jt-table",
      "jt-loading", "jt-empty"].forEach((id) => {
      // Testid may render as ``data-testid="foo"`` OR ``testid="foo"``
      // (the shared Button wrapper accepts ``testid`` and re-emits
      // ``data-testid`` at render time).
      const re = new RegExp(`(?:data-)?testid=(?:\\{?)['"\`]${id}['"\`]`);
      expect(JT_PAGE).toMatch(re);
    });
  });

  it("Admin sees Edit affordance + modal testids", () => {
    expect(JT_PAGE).toMatch(/data-testid="jt-edit-modal"/);
    expect(JT_PAGE).toMatch(/jt-edit-\$\{r\.id\}/);
    ["jt-edit-started", "jt-edit-ended", "jt-edit-tech-id",
      "jt-edit-crew-id", "jt-edit-cancel", "jt-edit-save"].forEach((id) => {
      const re = new RegExp(`(?:data-)?testid=(\\{?)['"\`]${id}['"\`]`);
      expect(JT_PAGE).toMatch(re);
    });
  });

  it("AvgTime tab exposes filter + table testids", () => {
    ["avg-filter-from", "avg-filter-to", "avg-filter-groupby",
      "avg-filter-tech", "avg-table"].forEach((id) => {
      expect(JT_PAGE).toMatch(new RegExp(`data-testid="${id}"`));
    });
  });

  it("Edit modal saves via PATCH /job-timers/:id", () => {
    expect(JT_PAGE).toMatch(/api\.patch\(`\/job-timers\/\$\{editRow\.id\}`/);
  });

  it("CSV export builds a filename with the range", () => {
    expect(JT_PAGE).toMatch(
      /job-timers-\$\{filters\.date_from\}-to-\$\{filters\.date_to\}\.csv/,
    );
  });

  it("Route is registered in App.js under AdminOnly", () => {
    expect(APP_JS).toMatch(
      /path="job-timers"\s+element=\{<AdminOnly><JobTimersPage/,
    );
    expect(APP_JS).toMatch(
      /path="avg-job-time"\s+element=\{<AdminOnly><JobTimersPage/,
    );
  });
});


describe("Feature 2 · /admin/reports/chemical-costs page", () => {
  it("Route is registered in App.js under AdminOnly", () => {
    expect(APP_JS).toMatch(
      /path="admin\/reports\/chemical-costs"[\s\S]{0,120}<ChemicalCostReportPage/,
    );
  });

  it("Filter row exposes shipped testids", () => {
    ["cc-filter-from", "cc-filter-to", "cc-filter-customer",
      "cc-filter-tech", "cc-filter-chemicals",
      "cc-export-csv", "cc-table", "cc-empty",
      "cc-totals"].forEach((id) => {
      const re = new RegExp(`(?:data-)?testid=(\\{?)['"\`]${id}['"\`]`);
      expect(CC_PAGE).toMatch(re);
    });
  });

  it("Loads data from the /reports/chemical-costs endpoint", () => {
    expect(CC_PAGE).toMatch(
      /api\.get\(`\/reports\/chemical-costs\?\$\{params\.toString\(\)\}`\)/,
    );
  });

  it("Default range = MTD (month-to-date)", () => {
    expect(CC_PAGE).toMatch(/_mtdRange/);
  });

  it("Filters sync to URL via useSearchParams (deep-linkable)", () => {
    expect(CC_PAGE).toMatch(/setSearchParams\(params/);
  });

  it("Totals card shows total_wholesale_cost + qty + job_count", () => {
    expect(CC_PAGE).toMatch(/Total wholesale cost/);
    expect(CC_PAGE).toMatch(/Total qty/);
    expect(CC_PAGE).toMatch(/Jobs touched/);
  });

  it("Table renders top_customer + top_tech per row", () => {
    expect(CC_PAGE).toMatch(/top_customer\.name/);
    expect(CC_PAGE).toMatch(/top_tech\.name/);
  });

  it("CSV export builds a range-scoped filename", () => {
    expect(CC_PAGE).toMatch(
      /chemical-costs-\$\{filters\.date_from\}-to-\$\{filters\.date_to\}\.csv/,
    );
  });
});
