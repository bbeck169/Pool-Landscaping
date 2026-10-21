/**
 * TD-84 b2 · Uncategorized banner + report screen (E3(b): per-row assign +
 * bulk-assign; bulk-hard-delete / CSV deliberately absent).
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPush = jest.fn();
const mockToast = jest.fn();
let mockRole = "admin";

jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u), post: (u: string, b: any) => mockPost(u, b) } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: mockRole } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush }),
  Redirect: ({ href }: any) => { const { Text } = require("react-native"); return <Text testID="redirect">{href}</Text>; },
  useFocusEffect: (cb: any) => { const R = require("react"); R.useEffect(() => cb(), []); },
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("@/src/components/widgets", () => ({ Header: ({ right }: any) => right || null }));
jest.mock("@/src/components/ui", () => {
  const { View } = require("react-native");
  return { Loading: () => null, Sheet: ({ visible, children, testID }: any) => (visible ? <View testID={testID}>{children}</View> : null) };
});
jest.mock("@/src/components/ui/AppTextInput", () => {
  const { TextInput } = require("react-native");
  return { __esModule: true, default: (p: any) => <TextInput {...p} /> };
});

import UncategorizedBanner from "@/src/components/dashboard/UncategorizedBanner";
import UncategorizedItemsScreen from "@/app/reports/uncategorized-items";
import { bannerText, chunk, keyToItem, rowKey } from "@/src/lib/uncategorized";

const ROW = (i: number, over: any = {}) => ({
  invoice_id: `inv-${i}`, line_item_index: 0, invoice_number: `INV-${i}`, customer_name: `Cust ${i}`,
  created_at: "2026-08-28T18:21:24Z", description: `Item ${i}`, amount: 100,
  income_category_id: "", income_category_name: "", service_category_id: "", service_category_name: "",
  missing_income: true, missing_service: true, ...over,
});
const INCOME = { items: [{ id: "ic1", name: "Pool" }, { id: "ic2", name: "Gone", is_archived: true }], total: 2 };
const SERVICE = { items: [{ id: "sc1", name: "Weekly Service" }], total: 1 };

beforeEach(() => {
  mockRole = "admin";
  [mockPush, mockToast].forEach((m) => m.mockReset());
  mockGet.mockReset().mockImplementation(async (u: string) => {
    if (u.startsWith("/reports/uncategorized-items")) return { items: [ROW(1), ROW(2), ROW(3, { missing_income: false, income_category_id: "ic1", income_category_name: "Pool" })], total: 3 };
    if (u === "/income-categories") return INCOME;
    if (u === "/service-categories") return SERVICE;
    if (u === "/reports/uncategorized-count") return { count: 80 };
    throw new Error(`unexpected GET ${u}`);
  });
  mockPost.mockReset().mockImplementation(async (u: string, b: any) => {
    if (u.endsWith("/assign")) return { income_category: b.income_category_id ? { id: "ic1", name: "Pool" } : null, service_category: b.service_category_id ? { id: "sc1", name: "Weekly Service" } : null };
    if (u === "/reports/uncategorized-items/bulk-assign") return { assigned: b.items.length, failed: 0, income_category: { id: "ic1", name: "Pool" } };
    throw new Error(`unexpected POST ${u}`);
  });
});

it("U1 · helpers: banner grammar, key round-trip, 200-row chunks", () => {
  expect(bannerText(1)).toBe("1 line item is uncategorized.");
  expect(bannerText(80)).toBe("80 line items are uncategorized.");
  expect(keyToItem(rowKey({ invoice_id: "a::b", line_item_index: 7 }))).toEqual({ invoice_id: "a::b", line_item_index: 7 });
  expect(chunk(Array.from({ length: 450 }, (_, i) => i)).map((c) => c.length)).toEqual([200, 200, 50]);
});

it("U2 · banner: count > 0 renders + taps through; count 0 / error renders nothing", async () => {
  const q = render(<UncategorizedBanner />);
  await waitFor(() => expect(q.getByTestId("uncategorized-banner-text").props.children).toBe("80 line items are uncategorized."));
  fireEvent.press(q.getByTestId("uncategorized-banner"));
  expect(mockPush).toHaveBeenCalledWith("/reports/uncategorized-items");
  mockGet.mockRejectedValueOnce(new Error("403"));
  const q2 = render(<UncategorizedBanner />);
  await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  expect(q2.queryByTestId("uncategorized-banner")).toBeNull();
});

it("U3 · report loads range=all&missing=either; filters refetch; archived categories hidden from pickers", async () => {
  const q = render(<UncategorizedItemsScreen />);
  await waitFor(() => expect(q.getByTestId("uncat-row-inv-1::0")).toBeTruthy());
  expect(mockGet).toHaveBeenCalledWith("/reports/uncategorized-items?range=all&missing=either");
  fireEvent.press(q.getByTestId("uncategorized-range-this_month"));
  fireEvent.press(q.getByTestId("uncategorized-missing-income"));
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/reports/uncategorized-items?range=this_month&missing=income"));
  await waitFor(() => expect(q.getByTestId("uncat-row-inv-1::0")).toBeTruthy());
  fireEvent.press(q.getByTestId("uncat-assign-income-inv-1::0"));
  expect(q.getByTestId("bu-option-ic1")).toBeTruthy();
  expect(q.queryByTestId("bu-option-ic2")).toBeNull();
});

it("U4 · per-row assign POSTs …/{invoice_id}/{idx}/assign and flips that taxonomy only", async () => {
  const q = render(<UncategorizedItemsScreen />);
  await waitFor(() => expect(q.getByTestId("uncat-assign-service-inv-2::0")).toBeTruthy());
  fireEvent.press(q.getByTestId("uncat-assign-service-inv-2::0"));
  await act(async () => { fireEvent.press(q.getByTestId("bu-option-sc1")); });
  expect(mockPost).toHaveBeenCalledWith("/reports/uncategorized-items/inv-2/0/assign", { service_category_id: "sc1" });
  await waitFor(() => expect(q.getByLabelText("Service category Weekly Service")).toBeTruthy());
  expect(mockToast).toHaveBeenCalledWith("Categorized as Weekly Service · still missing Income category", "success");
});

it("U5 · bulk: Select → select-all → Set Income → one bulk-assign call with every visible row", async () => {
  const q = render(<UncategorizedItemsScreen />);
  await waitFor(() => expect(q.getByTestId("uncat-row-inv-1::0")).toBeTruthy());
  fireEvent.press(q.getByTestId("uncat-select-toggle"));
  fireEvent.press(q.getByTestId("uncategorized-select-all"));
  fireEvent.press(q.getByTestId("uncategorized-bulk-assign-income"));
  await act(async () => { fireEvent.press(q.getByTestId("bu-option-ic1")); });
  expect(mockPost).toHaveBeenCalledTimes(1);
  expect(mockPost).toHaveBeenCalledWith("/reports/uncategorized-items/bulk-assign", {
    items: [1, 2, 3].map((i) => ({ invoice_id: `inv-${i}`, line_item_index: 0 })), income_category_id: "ic1",
  });
  expect(mockToast).toHaveBeenCalledWith("Bulk-assigned 3 rows — income = Pool", "success");
  expect(q.queryByTestId("bulk-action-bar")).toBeNull();
});

it("U6 · non-admin (manager) is redirected; no report fetch", async () => {
  mockRole = "manager";
  const q = render(<UncategorizedItemsScreen />);
  expect(q.getByTestId("redirect")).toBeTruthy();
  await act(async () => {});
  expect(mockGet).not.toHaveBeenCalled();
});

it("U7 · scope guard: no hard-delete / CSV in the mobile report; banner mounted inside revenue insights", () => {
  const src = fs.readFileSync(path.resolve(__dirname, "..", "app", "reports", "uncategorized-items.tsx"), "utf-8").replace(/\/\*\*[\s\S]*?\*\//, "");
  expect(src).not.toMatch(/bulk-hard-delete|exportCsv|api\.del/);
  const dash = fs.readFileSync(path.resolve(__dirname, "..", "app", "(app)", "index.tsx"), "utf-8");
  const section = dash.indexOf('testID="revenue-tiles-section"');
  const banner = dash.indexOf("<UncategorizedBanner />");
  expect(banner).toBeGreaterThan(section);
  expect(banner).toBeLessThan(dash.indexOf("<RevenueByCategoryTile range={revenueRange} />"));
});
