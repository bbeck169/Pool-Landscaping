/**
 * Phase K66 · Feb-2026 — ReportsHub quick-access tile grid tests.
 *
 * Covers:
 *   1. Tile grid renders 3 built tiles + 7 coming-soon placeholders.
 *   2. Built tiles show the live KPI value formatted via the shared
 *      ``formatValue`` helper (currency, count).
 *   3. Built tile links navigate to /reports/suite with the correct
 *      tab query param + hash for revenue-by-* deep links.
 *   4. Coming-soon tiles show the "Coming soon" ribbon, are marked
 *      ``aria-disabled="true"``, and expose NO clickable
 *      "Open report" affordance.
 *   5. Role gating is preserved via the ``AdminOnly`` route wrapper
 *      in ``App.js`` — regression assertion on the route config
 *      snapshot.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";
import fs from "fs";
import path from "path";

vi.mock("@/api", () => ({
  api: { get: vi.fn() },
}));

import { api } from "@/api";
import ReportsHub from "../pages/reports/ReportsHub";

function mountHub() {
  return render(
    <MemoryRouter initialEntries={["/reports"]}>
      <ReportsHub />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  api.get.mockReset();
  // Route the three parallel API calls by URL prefix.
  api.get.mockImplementation((url) => {
    if (url.startsWith("/reports/kpi/revenue_total")) {
      return Promise.resolve({
        key: "revenue_total",
        label: "Total Revenue",
        format: "currency",
        direction: "up_is_good",
        value: 124_500.75,
        prior_value: 100_000,
        delta_pct: 24.5,
      });
    }
    if (url.startsWith("/reports/kpi/revenue_by_customer")) {
      return Promise.resolve({
        key: "revenue_by_customer",
        format: "currency",
        is_grouped: true,
        total: 82_300.5,
        row_count: 42,
        rows: [],
      });
    }
    if (url.startsWith("/reports/kpi/revenue_by_city")) {
      return Promise.resolve({
        key: "revenue_by_city",
        format: "currency",
        is_grouped: true,
        total: 55_000,
        row_count: 7,
        rows: [],
      });
    }
    return Promise.reject(new Error(`unexpected api.get(${url})`));
  });
});

describe("K66 · ReportsHub quick-access tiles", () => {
  it("renders the 3 built tiles + 7 coming-soon placeholders", async () => {
    mountHub();
    // Grid container present.
    expect(screen.getByTestId("reports-hub-grid")).toBeInTheDocument();
    // Built tiles (identified by their KPI test-ids).
    await waitFor(() => {
      expect(screen.getByTestId("reports-tile-revenue-total-kpi")).toBeInTheDocument();
      expect(screen.getByTestId("reports-tile-revenue-by-customer-kpi")).toBeInTheDocument();
      expect(screen.getByTestId("reports-tile-revenue-by-city-kpi")).toBeInTheDocument();
    });
    // Coming-soon tiles — one per R1–R7.
    for (const phase of ["r1", "r2", "r3", "r4", "r5", "r6", "r7"]) {
      expect(screen.getByTestId(`reports-tile-coming-${phase}`)).toBeInTheDocument();
      expect(screen.getByTestId(`reports-tile-coming-${phase}-ribbon`)).toHaveTextContent(
        /Coming soon/i,
      );
    }
  });

  it("formats headline KPIs via the shared formatter", async () => {
    mountHub();
    await waitFor(() => {
      expect(screen.getByTestId("reports-tile-revenue-total-kpi")).toHaveTextContent("$124,500.75");
      expect(screen.getByTestId("reports-tile-revenue-by-customer-kpi")).toHaveTextContent(
        "$82,300.50",
      );
      expect(screen.getByTestId("reports-tile-revenue-by-city-kpi")).toHaveTextContent("$55,000.00");
    });
    // Grouped-tile subtitles surface the row counts with the right
    // singular/plural agreement.
    expect(screen.getByTestId("reports-tile-revenue-by-customer-kpi-sub")).toHaveTextContent(
      "42 customers",
    );
    expect(screen.getByTestId("reports-tile-revenue-by-city-kpi-sub")).toHaveTextContent(
      "7 cities",
    );
    // Delta subtitle on the scalar tile.
    expect(screen.getByTestId("reports-tile-revenue-total-kpi-sub")).toHaveTextContent(
      "+24.5% vs prior",
    );
  });

  it("deep-links each built tile to the correct suite tab + anchor", async () => {
    mountHub();
    await waitFor(() =>
      expect(screen.getByTestId("reports-tile-revenue-total-open")).toBeInTheDocument(),
    );
    const totalHref = screen
      .getByTestId("reports-tile-revenue-total-open")
      .getAttribute("href");
    expect(totalHref).toContain("/reports/suite");
    expect(totalHref).toContain("tab=overview");

    const custHref = screen
      .getByTestId("reports-tile-revenue-by-customer-open")
      .getAttribute("href");
    expect(custHref).toContain("tab=financial");
    expect(custHref).toContain("#revenue-by-customer");

    const cityHref = screen
      .getByTestId("reports-tile-revenue-by-city-open")
      .getAttribute("href");
    expect(cityHref).toContain("tab=financial");
    expect(cityHref).toContain("#revenue-by-city");
  });

  it("coming-soon tiles are non-interactive (no Open button, aria-disabled)", async () => {
    mountHub();
    for (const phase of ["r1", "r7"]) {
      const tile = screen.getByTestId(`reports-tile-coming-${phase}`);
      expect(tile.getAttribute("aria-disabled")).toBe("true");
      // No open-report affordance rendered inside the coming-soon tile.
      const opener = within(tile).queryByTestId(`reports-tile-coming-${phase}-open`);
      expect(opener).toBeNull();
      // Also assert there's no anchor tag inside — keyboard nav
      // must skip the placeholder entirely.
      const anchors = within(tile).queryAllByRole("link");
      expect(anchors.length).toBe(0);
    }
  });
});

describe("K66 · role gating regression", () => {
  it("the /reports route is still wrapped in AdminOnly", () => {
    // Source-level snapshot — we don't spin up the router; we just
    // assert the App.js contract stays intact so K66 doesn't
    // accidentally open the surface to non-admins.
    const appSrc = fs.readFileSync(
      path.resolve(__dirname, "../App.js"),
      "utf8",
    );
    // Grab the /reports route line + one lookahead line to also
    // capture the element attribute even if a formatter linebreaks.
    const line = appSrc.match(/path="reports"[\s\S]{0,200}/);
    expect(line).not.toBeNull();
    expect(line[0]).toMatch(/AdminOnly/);
    expect(line[0]).toMatch(/ReportsHub/);
  });
});
