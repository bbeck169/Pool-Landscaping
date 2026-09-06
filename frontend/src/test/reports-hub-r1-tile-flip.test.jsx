/**
 * Phase R1.b · Feb-2026 — ReportsHub R1 tile flip.
 *
 * The R1 tile was a ComingSoonTile before R1.b. R1.b flips it
 * into a live BuiltTile that renders the pnl_by_period scalar
 * KPI + a deep-link into ``/reports/suite?tab=financial#pnl``.
 * The R1 ComingSoonTile MUST NOT be present after R1.b (asserted
 * by absence — see the K67 grep-lock parity test).
 */
import React from "react";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("react-apexcharts", () => ({ __esModule: true, default: () => <div /> }));
vi.mock("@/components/DateRangePicker", () => ({
  __esModule: true,
  default: () => <div />,
  useDateRange: () => ({ start: "2026-02-01", end: "2026-02-28" }),
}));

import { api } from "@/api";
import ReportsHub from "@/pages/reports/ReportsHub";

const wrap = (ui) => <MemoryRouter>{ui}</MemoryRouter>;

describe("ReportsHub R1 tile flip (R1.b)", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url.includes("pnl_by_period")) {
        return Promise.resolve({
          value: 4200, delta_pct: 8.4, format: "currency", label: "Net Income",
        });
      }
      // Every other KPI resolves with an empty envelope so the
      // hub still renders without spinner-forever.
      return Promise.resolve({ value: 0, total: 0, row_count: 0 });
    });
  });

  it("renders the R1 built tile with a live P&L Net Income value", async () => {
    render(wrap(<ReportsHub />));
    await waitFor(() =>
      expect(screen.getByTestId("reports-tile-r1-financial")).toBeInTheDocument()
    );
    // Coming-soon variant MUST NOT exist for R1 after this phase.
    expect(screen.queryByTestId("reports-tile-coming-r1")).not.toBeInTheDocument();
    // Live headline KPI (currency format from pnl_by_period).
    await waitFor(() => {
      const kpi = screen.getByTestId("reports-tile-r1-financial-kpi");
      expect(kpi.textContent).toMatch(/\$4,200/);
    });
    // Open button deep-links into the Financial tab anchored at
    // the P&L subsection.
    const cta = screen.getByTestId("reports-tile-r1-financial-open");
    expect(cta.getAttribute("href")).toMatch(/tab=financial#pnl$/);
  });

  it("preserves the other 6 R2..R7 coming-soon tiles", async () => {
    render(wrap(<ReportsHub />));
    await waitFor(() =>
      expect(screen.getByTestId("reports-tile-coming-r2")).toBeInTheDocument()
    );
    ["r2","r3","r4","r5","r6","r7"].forEach((k) => {
      expect(screen.getByTestId(`reports-tile-coming-${k}`)).toBeInTheDocument();
    });
  });
});
