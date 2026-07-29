/**
 * IncomeByServiceCategoryTile · Feb-2026 · Vitest.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";

const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));

vi.mock("@/api", () => ({ api: { get: (...a) => getSpy(...a) } }));

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {} unobserve() {} disconnect() {}
  };
}

beforeEach(() => { getSpy.mockReset(); });
afterEach(() => cleanup());

import IncomeByServiceCategoryTile from "@/components/dashboard/IncomeByServiceCategoryTile";

describe("IncomeByServiceCategoryTile", () => {
  it("renders donut + legend when data returned", async () => {
    getSpy.mockResolvedValue({
      items: [
        { category: "Pool",        amount: 400, count: 5, color: "#0ea5e9" },
        { category: "Landscaping", amount: 100, count: 1, color: "#22c55e" },
      ],
      total: 500, currency: "USD",
    });
    render(<IncomeByServiceCategoryTile
              range={{ start: "2026-02-01", end: "2026-02-28" }} />);
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(1));
    expect(getSpy.mock.calls[0][0]).toContain(
      "/admin/dashboard/income-by-service-category?start=2026-02-01&end=2026-02-28");
    await waitFor(() => screen.getByTestId("income-svc-legend"));
    expect(screen.getByTestId("income-svc-legend-Pool")).toBeTruthy();
    expect(screen.getByTestId("income-svc-legend-Landscaping")).toBeTruthy();
    expect(screen.getByTestId("income-svc-item-count").textContent)
      .toContain("2 units");
  });

  it("refetches when the shared range changes", async () => {
    getSpy.mockResolvedValue({ items: [], total: 0, currency: "USD" });
    const { rerender } = render(
      <IncomeByServiceCategoryTile
        range={{ start: "2026-02-01", end: "2026-02-28" }} />
    );
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(1));
    rerender(<IncomeByServiceCategoryTile
                range={{ start: "2026-03-01", end: "2026-03-31" }} />);
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(2));
    expect(getSpy.mock.calls[1][0]).toContain(
      "start=2026-03-01&end=2026-03-31");
  });

  it("renders empty state when total is zero", async () => {
    getSpy.mockResolvedValue({ items: [], total: 0, currency: "USD" });
    render(<IncomeByServiceCategoryTile
              range={{ start: "2026-02-01", end: "2026-02-28" }} />);
    await waitFor(() => screen.getByTestId("income-svc-empty"));
  });
});
