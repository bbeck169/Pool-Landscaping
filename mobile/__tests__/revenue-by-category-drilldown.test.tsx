/**
 * Dashboard parity · Revenue by Category legend drill-down (read-only port
 * of web DashboardDrillDownModal variant="income-by-category").
 */
import React from "react";
import { render, waitFor, fireEvent } from "@testing-library/react-native";

const mockPush = jest.fn();
const mockGet = jest.fn(async (_u: string): Promise<any> => ({}));
jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u) } }));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: mockPush }) }));

import RevenueByCategoryTile from "@/src/components/dashboard/RevenueByCategoryTile";

const RANGE = { start: "2026-10-01", end: "2026-10-31" };
const row = (n: number, extra: any = {}) => ({
  invoice_id: `inv-${n}`, invoice_number: `INV-${n}`, line_index: 0, customer_name: "Alice Pool",
  date: "2026-10-05T10:00:00Z", description: `Line ${n}`, extended: 10 * n, ...extra,
});

function routeApi(pages: Record<string, any>) {
  mockGet.mockImplementation(async (u: string) => {
    if (u.startsWith("/admin/dashboard/revenue-by-category")) {
      return { total: 300, items: [{ category: "Cleaning", amount: 200, count: 2 }, { category: "Uncategorized", amount: 100, count: 1 }] };
    }
    if (u.startsWith("/dashboard/income/by-category/rows")) {
      const cur = (u.match(/cursor=([^&]+)/) || [])[1] || "first";
      if (pages[cur] instanceof Error) throw pages[cur];
      return pages[cur];
    }
    throw new Error("unexpected " + u);
  });
}

beforeEach(() => { mockGet.mockReset(); mockPush.mockClear(); });

it("legend drill → GET rows with web params; rows render; row tap → invoice; legend row tap still only highlights", async () => {
  routeApi({ first: { rows: [row(1), row(2, { line_index: 1 })], total: 2, next_cursor: null } });
  const q = render(<RevenueByCategoryTile range={RANGE} />);
  await waitFor(() => q.getByTestId("revenue-cat-legend"));
  fireEvent.press(q.getByTestId("revenue-cat-legend-Cleaning"));
  expect(mockGet.mock.calls.some((c) => String(c[0]).startsWith("/dashboard/income"))).toBe(false);
  fireEvent.press(q.getByTestId("revenue-cat-legend-drill-Cleaning"));
  await waitFor(() => q.getByTestId("income-row-inv-1-0"));
  expect(mockGet).toHaveBeenCalledWith("/dashboard/income/by-category/rows?category=Cleaning&from=2026-10-01&to=2026-10-31&limit=100");
  expect(q.getByText("Cleaning · line items")).toBeTruthy();
  expect(q.getByText("2 line items")).toBeTruthy();
  expect(q.getByText("2026-10-05 · Alice Pool · INV-1")).toBeTruthy();
  expect(q.queryByTestId("drilldown-load-more")).toBeNull();
  fireEvent.press(q.getByTestId("income-row-inv-2-1"));
  expect(mockPush).toHaveBeenCalledWith("/quote/inv-2");
});

it("next_cursor → Load more (N remaining) appends the next page", async () => {
  routeApi({
    first: { rows: [row(1)], total: 2, next_cursor: "c2" },
    c2: { rows: [row(2)], total: 2, next_cursor: null },
  });
  const q = render(<RevenueByCategoryTile range={RANGE} />);
  await waitFor(() => q.getByTestId("revenue-cat-legend"));
  fireEvent.press(q.getByTestId("revenue-cat-legend-drill-Uncategorized"));
  await waitFor(() => q.getByTestId("drilldown-load-more"));
  expect(q.getByText("Load more (1 remaining)")).toBeTruthy();
  fireEvent.press(q.getByTestId("drilldown-load-more"));
  await waitFor(() => q.getByTestId("income-row-inv-2-0"));
  expect(q.getByTestId("income-row-inv-1-0")).toBeTruthy();
  expect(mockGet).toHaveBeenCalledWith("/dashboard/income/by-category/rows?category=Uncategorized&from=2026-10-01&to=2026-10-31&limit=100&cursor=c2");
});

it("empty + error states use web copy / testids", async () => {
  routeApi({ first: { rows: [], total: 0, next_cursor: null } });
  const q = render(<RevenueByCategoryTile range={RANGE} />);
  await waitFor(() => q.getByTestId("revenue-cat-legend"));
  fireEvent.press(q.getByTestId("revenue-cat-legend-drill-Cleaning"));
  await waitFor(() => q.getByTestId("drilldown-empty"));
  expect(q.getByText("No line items in this bucket for the selected range.")).toBeTruthy();

  routeApi({ first: new Error("admin_only") });
  const q2 = render(<RevenueByCategoryTile range={RANGE} />);
  await waitFor(() => q2.getByTestId("revenue-cat-legend"));
  fireEvent.press(q2.getByTestId("revenue-cat-legend-drill-Cleaning"));
  await waitFor(() => q2.getByTestId("drilldown-error"));
});
