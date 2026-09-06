/**
 * Phase R1.b · Feb-2026 — OverviewStrip renders the four
 * financial header tiles from three parallel KPI fetches.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api", () => ({
  api: { get: vi.fn() },
}));

import { api } from "@/api";
import OverviewStrip from "@/components/reports/OverviewStrip";

describe("OverviewStrip (R1.b)", () => {
  beforeEach(() => {
    api.get.mockReset();
  });

  it("renders revenue, collected, AR balance and top-3 aging buckets", async () => {
    api.get.mockImplementation((url) => {
      if (url.includes("revenue_total")) {
        return Promise.resolve({ value: 12500.5, delta_pct: 8.4, format: "currency" });
      }
      if (url.includes("cashflow_by_period")) {
        return Promise.resolve({
          rows: [{ collected: 4000 }, { collected: 2500 }],
          summary: { collected_total: 6500 },
        });
      }
      if (url.includes("ar_aging")) {
        return Promise.resolve({
          total: 8200,
          net_terms_days: 30,
          rows: [
            { bucket: "0-30", amount: 5000, invoice_count: 4 },
            { bucket: "31-60", amount: 2000, invoice_count: 2 },
            { bucket: "61-90", amount: 1200, invoice_count: 1 },
            { bucket: "90+", amount: 0, invoice_count: 0 },
          ],
        });
      }
      return Promise.resolve({});
    });

    render(<OverviewStrip filters={{ period: "mtd" }} />);

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
    await waitFor(() => {
      expect(screen.getByTestId("financial-overview-strip-revenue-value").textContent).toMatch(/12,500/);
      expect(screen.getByTestId("financial-overview-strip-collected-value").textContent).toMatch(/6,500/);
      expect(screen.getByTestId("financial-overview-strip-ar-balance-value").textContent).toMatch(/8,200/);
    });
    // Only 3 non-zero buckets sourced from the response.
    expect(screen.getByTestId("financial-overview-strip-buckets-row-0-30-amount").textContent).toMatch(/\$5(k|,000)/);
    expect(screen.getByTestId("financial-overview-strip-buckets-row-31-60")).toBeInTheDocument();
    expect(screen.getByTestId("financial-overview-strip-buckets-row-61-90")).toBeInTheDocument();
  });

  it("renders loading state before responses resolve", () => {
    api.get.mockImplementation(() => new Promise(() => {}));
    render(<OverviewStrip filters={{ period: "mtd" }} />);
    expect(screen.getByTestId("financial-overview-strip-revenue-value").textContent).toMatch(/…/);
  });

  it("re-fetches when filters change", async () => {
    api.get.mockResolvedValue({});
    const { rerender } = render(<OverviewStrip filters={{ period: "mtd" }} />);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
    rerender(<OverviewStrip filters={{ period: "ytd" }} />);
    await waitFor(() => expect(api.get.mock.calls.length).toBeGreaterThanOrEqual(6));
    const called = api.get.mock.calls.some((c) => String(c[0]).includes("period=ytd"));
    expect(called).toBe(true);
  });
});
