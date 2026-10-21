/**
 * TD-84 b1 · Customers by Service Category row + Customers `?service_category=`.
 * Web parity: components/dashboard/ServiceCategoryTileRow.jsx (tiles, testids,
 * deep links, hide-on-error) and CustomersList.jsx (param → GET /customers).
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPush = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u) } }));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockPush }) }));

import ServiceCategoryTileRow, { parseServiceCategory } from "@/src/components/dashboard/ServiceCategoryTileRow";

const BREAKDOWN = {
  pool: { customers: 12, active_jobs: 3, mtd_revenue: 1500 },
  landscaping: { customers: 7, active_jobs: 1, mtd_revenue: 250 },
  both: { customers: 2, active_jobs: 0, mtd_revenue: 0 },
  unset: { customers: 529 },
};

beforeEach(() => { mockGet.mockReset(); mockPush.mockReset(); });

it("S1 · renders the 4 web tiles from /dashboard/service-category-breakdown; Not set has no stat lines", async () => {
  mockGet.mockResolvedValue(BREAKDOWN);
  const q = render(<ServiceCategoryTileRow width={160} />);
  await waitFor(() => expect(q.getByTestId("kpi-service-category-pool-customers").props.children).toBe("12"));
  expect(mockGet).toHaveBeenCalledWith("/dashboard/service-category-breakdown");
  expect(q.getByTestId("kpi-service-category-landscaping-customers").props.children).toBe("7");
  expect(q.getByTestId("kpi-service-category-both-customers").props.children).toBe("2");
  expect(q.getByTestId("kpi-service-category-unset-customers").props.children).toBe("529");
  expect(q.getByTestId("kpi-service-category-pool-active-jobs")).toBeTruthy();
  expect(q.getByTestId("kpi-service-category-pool-mtd")).toBeTruthy();
  expect(q.queryByTestId("kpi-service-category-unset-active-jobs")).toBeNull();
  expect(q.queryByTestId("kpi-service-category-unset-mtd")).toBeNull();
});

it("S2 · each tile deep-links the Customers list with ?service_category=<key>", async () => {
  mockGet.mockResolvedValue(BREAKDOWN);
  const q = render(<ServiceCategoryTileRow width={160} />);
  await waitFor(() => expect(q.getByTestId("kpi-service-category-unset")).toBeTruthy());
  for (const key of ["pool", "landscaping", "both", "unset"]) {
    fireEvent.press(q.getByTestId(`kpi-service-category-${key}`));
    expect(mockPush).toHaveBeenLastCalledWith({ pathname: "/(app)/customers", params: { service_category: key } });
  }
});

it("S3 · skeletons while loading; hidden entirely on error (e.g. 403)", async () => {
  let reject: (e: any) => void = () => {};
  mockGet.mockReturnValue(new Promise((_, r) => { reject = r; }));
  const q = render(<ServiceCategoryTileRow width={160} />);
  expect(q.getAllByTestId(/^service-category-skeleton-/)).toHaveLength(4);
  reject(Object.assign(new Error("Forbidden"), { status: 403 }));
  await waitFor(() => expect(q.queryByTestId("dashboard-service-category-row")).toBeNull());
});

it("S4 · parseServiceCategory accepts only pool/landscaping/both/unset", () => {
  expect(["pool", "landscaping", "both", "unset"].map(parseServiceCategory)).toEqual(["pool", "landscaping", "both", "unset"]);
  expect([undefined, "", "all", "Pool", "toString", ["pool"]].map(parseServiceCategory)).toEqual([null, null, null, null, null, null]);
});

const read = (...p: string[]) => fs.readFileSync(path.resolve(__dirname, "..", ...p), "utf-8");

it("S5 · customers.tsx forwards the param to GET /customers, shows a clearable chip, Clear all resets it", () => {
  const src = read("app", "(app)", "customers.tsx");
  expect(src).toMatch(/parseServiceCategory\(\(routeParams as any\)\?\.service_category\)/);
  expect(src).toMatch(/if \(serviceCategory\) qp\.set\("service_category", serviceCategory\)/);
  expect(src).toMatch(/tileKey, serviceCategory\]\)/);
  expect(src).toMatch(/testID="customers-service-category-chip"/);
  expect(src.match(/router\.setParams\(\{ service_category: undefined \}/g)).toHaveLength(2);
});

it("S6 · dashboard mounts the row after the KPI grid, gated to admin + manager (endpoint gate)", () => {
  const src = read("app", "(app)", "index.tsx");
  const grid = src.indexOf('testID="dashboard-kpi-grid"');
  const row = src.indexOf("{isManagerPlus ? <ServiceCategoryTileRow width={kpiWidth} /> : null}");
  expect(grid).toBeGreaterThan(0);
  expect(row).toBeGreaterThan(grid);
  expect(src.indexOf("<DashboardActionCards />")).toBeGreaterThan(row);
});
