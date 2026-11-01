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

// Tile overflow fix — StatLine (Active jobs / MTD revenue) on every stat tile.
it("S7 · stat lines wrap + shrink-to-fit instead of bleeding past the tile (small + large values)", async () => {
  const { StyleSheet } = require("react-native");
  const { STAT_VALUE_MIN_FONT_SCALE } = require("@/src/components/dashboard/ServiceCategoryTileRow");
  mockGet.mockResolvedValue({
    pool: { customers: 1234, active_jobs: 999, mtd_revenue: 1234567.89 },
    landscaping: { customers: 7, active_jobs: 3, mtd_revenue: 0 },
    both: { customers: 2, active_jobs: 12345, mtd_revenue: 98765.43 },
    unset: { customers: 529 },
  });
  const q = render(<ServiceCategoryTileRow width={138} />);
  await waitFor(() => expect(q.getByTestId("kpi-service-category-pool-mtd-value")).toBeTruthy());
  const text = (id: string) => q.getByTestId(id).props.children;
  expect(text("kpi-service-category-pool-mtd-value")).toBe("$1,234,567.89");
  expect(text("kpi-service-category-pool-active-jobs-value")).toBe("999");
  expect(text("kpi-service-category-landscaping-mtd-value")).toBe("$0.00");
  expect(text("kpi-service-category-landscaping-active-jobs-value")).toBe("3");
  expect(text("kpi-service-category-both-active-jobs-value")).toBe("12,345");
  expect(STAT_VALUE_MIN_FONT_SCALE).toBe(0.7);
  for (const k of ["pool", "landscaping", "both"]) {
    for (const suf of ["active-jobs", "mtd"]) {
      const row = StyleSheet.flatten(q.getByTestId(`kpi-service-category-${k}-${suf}`).props.style);
      expect(row.flexDirection).toBe("row");
      expect(row.flexWrap).toBe("wrap");
      const label = q.getByTestId(`kpi-service-category-${k}-${suf}-label`);
      expect(StyleSheet.flatten(label.props.style).flexShrink).toBe(1);
      const value = q.getByTestId(`kpi-service-category-${k}-${suf}-value`);
      expect(value.props.numberOfLines).toBe(1);
      expect(value.props.adjustsFontSizeToFit).toBe(true);
      expect(value.props.minimumFontScale).toBe(0.7);
      const vs = StyleSheet.flatten(value.props.style);
      expect(vs.flexShrink).toBe(1);
      expect(vs.maxWidth).toBe("100%");
    }
  }
  // Regression lock — tile identity, header count + Not-set tile untouched.
  expect(q.getByTestId("kpi-service-category-pool-customers").props.children).toBe("1,234");
  expect(q.queryByTestId("kpi-service-category-unset-mtd")).toBeNull();
  const pool = StyleSheet.flatten(q.getByTestId("kpi-service-category-pool").props.style);
  expect(pool).toMatchObject({ width: 138, backgroundColor: "#ECFEFF", borderColor: "#06B6D4", borderLeftWidth: 4 });
});
