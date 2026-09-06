/**
 * Phase R1.b · Feb-2026 — PnlPanel renders the scalar KPI card
 * on the left and the line-item table on the right, and exports
 * CSV via the downloadCsv helper.
 */
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("react-apexcharts", () => ({
  __esModule: true,
  default: () => <div data-testid="apex-stub" />,
}));
vi.mock("@/components/reports/downloadCsv", () => ({
  downloadCsv: vi.fn(),
}));

import { api } from "@/api";
import { downloadCsv } from "@/components/reports/downloadCsv";
import PnlPanel from "@/components/reports/PnlPanel";

describe("PnlPanel (R1.b)", () => {
  beforeEach(() => {
    api.get.mockReset();
    downloadCsv.mockReset();
  });

  it("renders the KPI card and line-item rows", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("pnl_by_period")) {
        return Promise.resolve({
          value: 4200, prior_value: 3800, delta_pct: 10.5,
          label: "Net Income", format: "currency",
        });
      }
      if (url.includes("pnl_line_items")) {
        return Promise.resolve({
          rows: [
            { label: "Revenue",       value: 12000, format: "currency" },
            { label: "COGS",          value: -3000, format: "currency" },
            { label: "Gross Profit",  value: 9000,  format: "currency" },
            { label: "OpEx",          value: -4800, format: "currency" },
            { label: "EBIT",          value: 4200,  format: "currency" },
            { label: "EBIT margin",   value: 35,    format: "percent" },
          ],
        });
      }
      return Promise.resolve({});
    });

    render(<PnlPanel filters={{ period: "mtd" }} />);

    await waitFor(() => {
      expect(screen.getByTestId("pnl-panel-row-revenue")).toBeInTheDocument();
      expect(screen.getByTestId("pnl-panel-row-ebit")).toBeInTheDocument();
      expect(screen.getByTestId("pnl-panel-row-ebit-margin")).toBeInTheDocument();
    });
    // EBIT row is emphasized (matches "ebit\b").
    const ebitRow = screen.getByTestId("pnl-panel-row-ebit");
    expect(ebitRow.textContent).toMatch(/EBIT/);
    // Percent formatter engaged for the margin row.
    expect(screen.getByTestId("pnl-panel-row-ebit-margin").textContent).toMatch(/35\.0%/);
  });

  it("empty state when the backend returns zero rows", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("pnl_by_period")) return Promise.resolve({ value: 0 });
      return Promise.resolve({ rows: [] });
    });
    render(<PnlPanel filters={{ period: "mtd" }} />);
    await waitFor(() => {
      expect(screen.getByTestId("pnl-panel-empty")).toBeInTheDocument();
    });
  });

  it("CSV export invokes downloadCsv with header + rows", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("pnl_by_period")) return Promise.resolve({ value: 4200 });
      if (url.includes("pnl_line_items")) return Promise.resolve({
        rows: [{ label: "Revenue", value: 12000, format: "currency" }],
      });
      return Promise.resolve({});
    });
    render(<PnlPanel filters={{ period: "mtd" }} />);
    await waitFor(() => expect(screen.getByTestId("pnl-panel-row-revenue")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("pnl-panel-export"));
    expect(downloadCsv).toHaveBeenCalledTimes(1);
    const [filename, headers, body] = downloadCsv.mock.calls[0];
    expect(filename).toMatch(/^pnl-mtd\.csv$/);
    expect(headers).toEqual(["Label", "Value", "Format"]);
    expect(body[0][0]).toBe("Revenue");
  });
});
