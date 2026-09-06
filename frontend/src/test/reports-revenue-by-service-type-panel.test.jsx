/**
 * Phase R1.b · Feb-2026 — RevenueByServiceTypePanel renders rows,
 * threads lens into the API query, and exports CSV in the locked
 * column order.
 */
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("react-apexcharts", () => ({ __esModule: true, default: () => <div /> }));
vi.mock("@/components/reports/downloadCsv", () => ({
  downloadCsv: vi.fn(),
}));

import { api } from "@/api";
import { downloadCsv } from "@/components/reports/downloadCsv";
import RevenueByServiceTypePanel from "@/components/reports/RevenueByServiceTypePanel";

describe("RevenueByServiceTypePanel (R1.b)", () => {
  beforeEach(() => { api.get.mockReset(); downloadCsv.mockReset(); });

  it("renders category rows and includes Uncategorized bucket", async () => {
    api.get.mockResolvedValue({
      total: 5000, row_count: 2,
      rows: [
        { service_category_id: "svc-pool", service_category_name: "Pool cleaning",
          revenue: 3200, invoice_count: 10 },
        { service_category_id: null, service_category_name: "Uncategorized",
          revenue: 1800, invoice_count: 4 },
      ],
      lens: "invoiced",
    });
    render(<RevenueByServiceTypePanel filters={{ period: "mtd" }} />);
    await waitFor(() => {
      expect(screen.getByTestId("rev-svc-panel-row-svc-pool")).toBeInTheDocument();
      expect(screen.getByTestId("rev-svc-panel-row-uncat")).toBeInTheDocument();
    });
  });

  it("threads lens=collected into the API when the parent supplies it", async () => {
    api.get.mockResolvedValue({ rows: [] });
    render(<RevenueByServiceTypePanel filters={{ period: "mtd", lens: "collected" }} />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(api.get.mock.calls[0][0]).toMatch(/lens=collected/);
  });

  it("CSV export produces the locked column order", async () => {
    api.get.mockResolvedValue({
      rows: [{ service_category_id: "x", service_category_name: "X", revenue: 1, invoice_count: 1 }],
    });
    render(<RevenueByServiceTypePanel filters={{ period: "mtd" }} />);
    await waitFor(() => screen.getByTestId("rev-svc-panel-row-x"));
    fireEvent.click(screen.getByTestId("rev-svc-panel-export"));
    expect(downloadCsv).toHaveBeenCalledTimes(1);
    const [, headers] = downloadCsv.mock.calls[0];
    expect(headers).toEqual(["Service Category", "Category ID", "Revenue", "Invoices"]);
  });
});
