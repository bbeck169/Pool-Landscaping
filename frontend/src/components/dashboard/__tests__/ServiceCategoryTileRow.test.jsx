/**
 * P2 #6 · Feb-2026 — ServiceCategoryTileRow vitest.
 *
 * Locks four invariants on the admin Dashboard tile row:
 *   1. Renders four tiles after the fetch resolves — Pool / Landscaping /
 *      Both / Not set — with customer counts from the endpoint payload.
 *   2. Pool / Landscaping / Both tiles ALSO render active_jobs + MTD
 *      revenue sub-stats; "Not set" shows only the customer count.
 *   3. Click on each tile navigates to the P2 #6 filter deep-link
 *      (lowercase enum values in the URL).
 *   4. Loading state renders 4 skeletons before the endpoint resolves;
 *      no tiles rendered yet.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup }
  from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { apiGetSpy, navigateMock } = vi.hoisted(() => ({
  apiGetSpy: vi.fn(), navigateMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { get: (...a) => apiGetSpy(...a) },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});

vi.mock("@/theme", () => ({
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
  colors: {},
}));


import ServiceCategoryTileRow
  from "@/components/dashboard/ServiceCategoryTileRow";


const PAYLOAD = {
  pool:        { customers: 12, active_jobs: 7, mtd_revenue: 4500.5 },
  landscaping: { customers:  5, active_jobs: 2, mtd_revenue: 1200.0 },
  both:        { customers:  3, active_jobs: 1, mtd_revenue:  800.0 },
  unset:       { customers: 42 },
};


beforeEach(() => {
  apiGetSpy.mockReset();
  navigateMock.mockReset();
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });


function _mount() {
  return render(
    <MemoryRouter>
      <ServiceCategoryTileRow />
    </MemoryRouter>,
  );
}


describe("P2 #6 · ServiceCategoryTileRow", () => {
  it("renders 4 tiles with customer counts after the fetch resolves", async () => {
    apiGetSpy.mockResolvedValue(PAYLOAD);
    _mount();
    const pool = await screen.findByTestId("kpi-service-category-pool");
    expect(pool).toBeTruthy();
    expect(screen.getByTestId("kpi-service-category-pool-customers").textContent)
      .toContain("12");
    expect(screen.getByTestId("kpi-service-category-landscaping-customers").textContent)
      .toContain("5");
    expect(screen.getByTestId("kpi-service-category-both-customers").textContent)
      .toContain("3");
    expect(screen.getByTestId("kpi-service-category-unset-customers").textContent)
      .toContain("42");
    // Endpoint called once.
    expect(apiGetSpy).toHaveBeenCalledWith("/dashboard/service-category-breakdown");
  });

  it("renders active_jobs + MTD revenue on enum buckets; unset has only customer count", async () => {
    apiGetSpy.mockResolvedValue(PAYLOAD);
    _mount();
    await screen.findByTestId("kpi-service-category-pool");
    expect(screen.getByTestId("kpi-service-category-pool-active-jobs").textContent)
      .toContain("7");
    expect(screen.getByTestId("kpi-service-category-pool-mtd").textContent)
      .toContain("4500.50");
    expect(screen.getByTestId("kpi-service-category-landscaping-active-jobs").textContent)
      .toContain("2");
    expect(screen.getByTestId("kpi-service-category-both-mtd").textContent)
      .toContain("800.00");
    // "Not set" tile has NO active_jobs or MTD sub-stat testid.
    expect(screen.queryByTestId("kpi-service-category-unset-active-jobs")).toBeNull();
    expect(screen.queryByTestId("kpi-service-category-unset-mtd")).toBeNull();
  });

  it("clicks deep-link to /customers?service_category=<key> for each tile", async () => {
    apiGetSpy.mockResolvedValue(PAYLOAD);
    _mount();
    const map = [
      ["kpi-service-category-pool",        "/customers?service_category=pool"],
      ["kpi-service-category-landscaping", "/customers?service_category=landscaping"],
      ["kpi-service-category-both",        "/customers?service_category=both"],
      ["kpi-service-category-unset",       "/customers?service_category=unset"],
    ];
    for (const [tid, href] of map) {
      navigateMock.mockReset();
      const el = await screen.findByTestId(tid);
      fireEvent.click(el);
      await waitFor(() =>
        expect(navigateMock).toHaveBeenCalledWith(href));
    }
  });

  it("renders 4 skeletons while loading, no tiles yet", async () => {
    // Never-resolving fetch to lock the loading state.
    apiGetSpy.mockImplementation(() => new Promise(() => {}));
    _mount();
    await waitFor(() => {
      expect(screen.queryByTestId("service-category-skeleton-0")).toBeTruthy();
      expect(screen.queryByTestId("service-category-skeleton-3")).toBeTruthy();
    });
    expect(screen.queryByTestId("kpi-service-category-pool")).toBeNull();
  });
});
