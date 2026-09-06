/**
 * Phase R1.b · Feb-2026 — CashFlowPanel renders the summary line
 * and the multi-series trend chart from cashflow_by_period.
 */
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("react-apexcharts", () => ({
  __esModule: true,
  default: (props) => (
    <div data-testid="apex-stub" data-series-count={props.series?.length || 0} />
  ),
}));
vi.mock("@/components/reports/downloadCsv", () => ({
  downloadCsv: vi.fn(),
}));

import { api } from "@/api";
import { downloadCsv } from "@/components/reports/downloadCsv";
import CashFlowPanel from "@/components/reports/CashFlowPanel";

describe("CashFlowPanel (R1.b)", () => {
  beforeEach(() => {
    api.get.mockReset();
    downloadCsv.mockReset();
  });

  it("renders the trend chart with three series and shows totals", async () => {
    api.get.mockResolvedValue({
      rows: [
        { bucket: "2026-01", invoiced: 5000, collected: 3200, net: 3200, running_balance: 3200 },
        { bucket: "2026-02", invoiced: 6000, collected: 4800, net: 4800, running_balance: 8000 },
      ],
      summary: { invoiced_total: 11000, collected_total: 8000, net_total: 8000 },
    });

    render(<CashFlowPanel filters={{ period: "ytd" }} />);
    await waitFor(() => {
      const apex = screen.getByTestId("cash-flow-panel-chart").querySelector('[data-testid="apex-stub"]');
      expect(apex).toBeInTheDocument();
      expect(apex.dataset.seriesCount).toBe("3");
    });
    // Summary line references the totals from the response.
    expect(screen.getByText(/11,000/)).toBeInTheDocument();
  });

  it("empty state when the backend returns zero rows", async () => {
    api.get.mockResolvedValue({ rows: [] });
    render(<CashFlowPanel filters={{ period: "mtd" }} />);
    await waitFor(() =>
      expect(screen.getByTestId("cash-flow-panel-empty")).toBeInTheDocument()
    );
  });

  it("CSV export produces the locked column order", async () => {
    api.get.mockResolvedValue({
      rows: [{ bucket: "2026-02", invoiced: 6, collected: 4, net: 2, running_balance: 8 }],
      summary: {},
    });
    render(<CashFlowPanel filters={{ period: "ytd" }} />);
    await waitFor(() => screen.getByTestId("cash-flow-panel-chart"));
    fireEvent.click(screen.getByTestId("cash-flow-panel-export"));
    expect(downloadCsv).toHaveBeenCalledTimes(1);
    const [, headers] = downloadCsv.mock.calls[0];
    expect(headers).toEqual(["Bucket", "Invoiced", "Collected", "Net", "Running Balance"]);
  });
});
