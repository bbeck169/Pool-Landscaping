/**
 * Phase 39A · mobile dashboard — web section order + Revenue Insights wiring.
 *   - Order: Revenue insights → KPI grid → Topline (Forecast + EBIT) →
 *     Weather → Requested banner → Referral → Revenue chart → Payments →
 *     Revenue by Service → Recent Jobs → mobile-only extras.
 *   - Removed: Total Paid Revenue hero + 3 revenue shortcut tiles.
 *   - Shared range drives both donuts + Forecast headline; preset change,
 *     Custom Range (apply + validation) and persistence.
 *   - Donut tiles: loading / empty / error / UUID label / legend tap.
 *   - Role gates: revenue + forecast admin/super_admin only (backend 403s others).
 */
import React from "react";
import { render, waitFor, act, fireEvent, within } from "@testing-library/react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

jest.setTimeout(20000);

const mockApiGet = jest.fn();
const mockPush = jest.fn();
let mockRole = "admin";
let mockDash: any = null;

jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockApiGet(...a), post: jest.fn(), patch: jest.fn() } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: mockRole, name: "Test Admin" } }) }));
jest.mock("@/src/hooks/useOfflineQuery", () => ({
  useOfflineQuery: () => ({ data: mockDash, isLoading: false, error: null, refetch: jest.fn() }),
}));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
  useFocusEffect: (cb: any) => require("react").useEffect(() => { const c = cb(); return typeof c === "function" ? c : undefined; }, []),
  Redirect: () => null,
}));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("@react-native-community/datetimepicker", () => {
  const { View } = require("react-native");
  return function MockPicker(p: any) { return <View testID={p.testID} onChange={p.onChange} />; };
});
jest.mock("@/src/components/widgets", () => {
  const { Text } = require("react-native");
  return { Header: ({ title }: any) => <Text testID="mock-header">{title}</Text> };
});
jest.mock("@/src/components/ui", () => {
  const { View, Text, Pressable } = require("react-native");
  return {
    Loading: (p: any) => <View testID={p.testID || "loading"} />,
    StatusChip: ({ status }: any) => <Text>{status}</Text>,
    Sheet: ({ visible, children, testID }: any) => (visible ? <View testID={testID}>{children}</View> : null),
    PrimaryButton: ({ title, onPress }: any) => <Pressable onPress={onPress}><Text>{title}</Text></Pressable>,
  };
});
jest.mock("@/src/components/ui/AppTextInput", () => {
  const { TextInput } = require("react-native");
  return function MockInput(p: any) { return <TextInput {...p} />; };
});
const stub = (id: string) => () => { const { View } = require("react-native"); return <View testID={id} />; };
jest.mock("@/src/components/SyncStatusPill", () => () => null);
jest.mock("@/src/components/sync/PendingChangesChip", () => ({ PendingChangesChip: () => null }));
jest.mock("@/src/components/ai/CreditsBudgetChip", () => () => null);
jest.mock("@/src/components/BudgetHealthCard", () => stub("stub-budget-health"));
jest.mock("@/src/components/LandscapingClockWidget", () => stub("stub-landscaping-clock"));
jest.mock("@/src/components/weather/WeatherWidget", () => stub("stub-weather"));
jest.mock("@/src/components/dashboard/EbitTile", () => stub("stub-ebit"));
jest.mock("@/src/utils/formatCustomerName", () => ({ formatCustomerName: (r: any) => r?.customer_name || "Customer" }));

import Dashboard from "@/app/(app)/index";
import { rangeFromPreset } from "@/src/lib/revenueRange";
import RevenueByCategoryTile from "@/src/components/dashboard/RevenueByCategoryTile";

const DASH = {
  active_jobs: 10, pending_jobs: 3, outstanding: 200, requested_jobs: 2, active_customers_count: 100,
  inactive_customers_count: 50, revenue: 5000, revenue_series: [{ label: "Jan", value: 10 }],
  revenue_by_service: [{ label: "Pool", value: 900 }], recent_jobs: [{ id: "j1", title: "Clean", status: "scheduled", customer_name: "A" }],
};
const CAT = { total: 1000, items: [
  { category_id: "c1", category_name: "Chemicals", amount: 600, count: 4, color: "#0891B2" },
  { category_id: "c2", category_name: "3f2b8a10-1234-4abc-9def-0123456789ab", amount: 400, count: 1, color: "#7C3AED" },
] };
const SVC = { total: 700, items: [{ category: "Pool", amount: 700, count: 3, color: "#16A34A" }] };
const FC = { combined_total: 4321, booked: { amount: 3000, job_count: 1 }, recurring: { amount: 1321, subscription_count: 2, recurring_job_count: 0, cycle_count: 3 } };

function route(path: string) {
  if (path.startsWith("/admin/dashboard/revenue-by-category")) return Promise.resolve(CAT);
  if (path.startsWith("/admin/dashboard/income-by-service-category")) return Promise.resolve(SVC);
  if (path.startsWith("/admin/dashboard/revenue-forecast")) return Promise.resolve(FC);
  if (path === "/maintenance/digest") return Promise.resolve({ overdue: 1, due_this_week: 2, items: [] });
  if (path === "/payments/summary") return Promise.resolve({ collected_this_month: 0, outstanding_total: 0, outstanding_count: 0, month_label: "Oct", overdue: [] });
  if (path.startsWith("/referrals/admin/analytics")) return Promise.resolve({ revenue_attribution: { total_usd: 10 }, funnel: { converted: 1 } });
  return Promise.resolve([]);
}
const calls = (prefix: string) => mockApiGet.mock.calls.map((c) => c[0] as string).filter((u) => u.startsWith(prefix));
const qs = (r: { start: string; end: string }) => `?start=${r.start}&end=${r.end}`;

function ids(node: any, out: string[] = []): string[] {
  if (!node) return out;
  if (Array.isArray(node)) { node.forEach((n) => ids(n, out)); return out; }
  if (node.props?.testID) out.push(node.props.testID);
  (node.children || []).forEach((c: any) => typeof c === "object" && ids(c, out));
  return out;
}

async function mount() {
  const r = render(<Dashboard />);
  await waitFor(() => r.getByTestId("revenue-cat-legend"));
  await act(async () => {});
  return r;
}

beforeEach(async () => {
  jest.clearAllMocks();
  await AsyncStorage.clear();
  mockRole = "admin";
  mockDash = DASH;
  mockApiGet.mockImplementation(route);
});

describe("Phase 39A · section order + removals", () => {
  it("renders web order top → bottom, mobile-only extras last", async () => {
    const r = await mount();
    const o = ids(r.toJSON());
    const seq = ["revenue-tiles-section", "revenue-by-category-tile", "income-by-service-category-tile",
      "dashboard-topline-tiles", "revenue-forecast-tile", "dashboard-ebit-tile-slot", "dashboard-kpi-grid", "stub-weather", "new-requests-banner",
      "tile-referral-revenue", "revenue-chart", "payments-widget", "revenue-by-service", "see-all-jobs",
      "dashboard-mobile-extras", "stub-budget-health", "maintenance-digest"];
    const pos = seq.map((id) => [id, o.indexOf(id)] as const);
    pos.forEach(([id, i]) => expect([id, i >= 0]).toEqual([id, true]));
    const idx = pos.map(([, i]) => i);
    expect([...idx].sort((a, b) => a - b)).toEqual(idx);
  });

  it("Total Paid Revenue hero + 3 revenue shortcut tiles are gone", async () => {
    const r = await mount();
    for (const id of ["dashboard-revenue", "dashboard-revenue-tiles", "admin-tile-revenue-by-category", "admin-tile-revenue-by-service", "admin-tile-forecast-revenue"]) {
      expect([id, r.queryByTestId(id)]).toEqual([id, null]);
    }
    expect(r.queryByText(/Total Paid Revenue/)).toBeNull();
  });

  it("mobile-only extras live inside the extras block (Landscaping clock hidden for admin)", async () => {
    const r = await mount();
    const ex = within(r.getByTestId("dashboard-mobile-extras"));
    expect(ex.getByTestId("stub-budget-health")).toBeTruthy();
    expect(ex.getByTestId("maintenance-digest")).toBeTruthy();
    expect(ex.queryByTestId("stub-landscaping-clock")).toBeNull();
  });

  it("manager: no revenue insights / forecast / EBIT; Landscaping clock shown in extras", async () => {
    mockRole = "manager";
    const r = render(<Dashboard />);
    await waitFor(() => r.getByTestId("dashboard-kpi-grid"));
    await act(async () => {});
    for (const id of ["revenue-tiles-section", "revenue-forecast-tile", "dashboard-ebit-tile-slot"]) expect(r.queryByTestId(id)).toBeNull();
    expect(within(r.getByTestId("dashboard-mobile-extras")).getByTestId("stub-landscaping-clock")).toBeTruthy();
    expect(calls("/admin/dashboard/")).toEqual([]);
  });

  it("KPI grid = web's 7 tiles in web order; taps carry web's deep-links (admin jobs → /admin/jobs)", async () => {
    const r = await mount();
    const KEYS = ["kpi-active-jobs", "kpi-pending", "kpi-inactive-customers", "kpi-active-accounts",
      "kpi-pool-properties", "kpi-landscaping-properties", "kpi-both-properties"];
    const o = ids(r.toJSON()).filter((id) => KEYS.includes(id));
    expect(o.filter((v, i, a) => a.indexOf(v) === i)).toEqual(KEYS);
    expect(r.queryByTestId("kpi-active-customers")).toBeNull(); // removed on web (P2 cleanup)
    KEYS.forEach((k) => fireEvent.press(r.getByTestId(k)));
    expect(mockPush.mock.calls.map((c) => c[0])).toEqual([
      { pathname: "/admin/jobs", params: { status: "active" } }, { pathname: "/admin/jobs", params: { status: "pending" } },
      { pathname: "/(app)/customers", params: { status: "inactive" } },
      { pathname: "/properties", params: { is_active: "true" } },
      { pathname: "/properties", params: { is_active: "true", service_category: "pool" } },
      { pathname: "/properties", params: { is_active: "true", service_category: "landscaping" } },
      { pathname: "/properties", params: { is_active: "true", service_category: "both" } },
    ]);
  });

  it("manager: job tiles keep /(app)/jobs (web /admin/jobs is AdminOnly)", async () => {
    mockRole = "manager";
    const r = render(<Dashboard />);
    await waitFor(() => r.getByTestId("dashboard-kpi-grid"));
    await act(async () => {});
    fireEvent.press(r.getByTestId("kpi-active-jobs"));
    fireEvent.press(r.getByTestId("kpi-pending"));
    expect(mockPush.mock.calls.map((c) => c[0])).toEqual([
      { pathname: "/(app)/jobs", params: { status: "active" } }, { pathname: "/(app)/jobs", params: { status: "pending" } },
    ]);
  });
});

describe("Phase 39A · shared range wiring", () => {
  it("default This Month drives all three range endpoints with the same start/end", async () => {
    await mount();
    const q = qs(rangeFromPreset("this_month"));
    expect(calls("/admin/dashboard/revenue-by-category")).toEqual([`/admin/dashboard/revenue-by-category${q}`]);
    expect(calls("/admin/dashboard/income-by-service-category")).toEqual([`/admin/dashboard/income-by-service-category${q}`]);
    expect(calls("/admin/dashboard/revenue-forecast")).toEqual([`/admin/dashboard/revenue-forecast${q}`]);
  });

  it("dropdown lists 9 presets; picking Last Year refetches all three + persists", async () => {
    const r = await mount();
    fireEvent.press(r.getByTestId("revenue-range-toggle"));
    const sheet = within(r.getByTestId("revenue-range-popover"));
    expect(["today", "tomorrow", "this_week", "next_week", "this_month", "last_month", "this_year", "last_year", "custom"]
      .every((k) => sheet.queryByTestId(`revenue-range-preset-${k}`))).toBe(true);
    mockApiGet.mockClear();
    await act(async () => { fireEvent.press(r.getByTestId("revenue-range-preset-last_year")); });
    await waitFor(() => r.getByTestId("revenue-cat-legend"));
    const q = qs(rangeFromPreset("last_year"));
    expect(calls("/admin/dashboard/revenue-by-category")).toEqual([`/admin/dashboard/revenue-by-category${q}`]);
    expect(calls("/admin/dashboard/income-by-service-category")).toEqual([`/admin/dashboard/income-by-service-category${q}`]);
    expect(calls("/admin/dashboard/revenue-forecast")).toEqual([`/admin/dashboard/revenue-forecast${q}`]);
    expect(r.queryByTestId("revenue-range-popover")).toBeNull();
    expect(within(r.getByTestId("revenue-range-toggle")).getByText("Last Year")).toBeTruthy();
    expect(JSON.parse((await AsyncStorage.getItem("admin.dashboard.revenue.range.v1")) as string).preset).toBe("last_year");
  });

  it("persisted preset hydrates on mount", async () => {
    await AsyncStorage.setItem("admin.dashboard.revenue.range.v1", JSON.stringify({ preset: "last_month", custom: { start: "2026-01-01", end: "2026-01-02" } }));
    const r = await mount();
    expect(calls("/admin/dashboard/revenue-by-category")).toEqual([`/admin/dashboard/revenue-by-category${qs(rangeFromPreset("last_month"))}`]);
    expect(within(r.getByTestId("revenue-range-toggle")).getByText("Last Month")).toBeTruthy();
  });

  it("Custom Range: pick dates → Apply refetches with that range; summary shown; start > end blocks Apply", async () => {
    const r = await mount();
    fireEvent.press(r.getByTestId("revenue-range-toggle"));
    fireEvent.press(r.getByTestId("revenue-range-preset-custom"));
    fireEvent.press(r.getByTestId("revenue-range-custom-start"));
    fireEvent(r.getByTestId("revenue-range-custom-start-picker"), "change", { type: "set" }, new Date(2026, 0, 5, 12));
    fireEvent.press(r.getByTestId("revenue-range-custom-end"));
    fireEvent(r.getByTestId("revenue-range-custom-end-picker"), "change", { type: "set" }, new Date(2026, 0, 2, 12));
    expect(r.getByTestId("revenue-range-custom-apply").props.accessibilityState).toMatchObject({ disabled: true });
    // iOS inline picker stays open after a pick (tap the field again to collapse).
    fireEvent(r.getByTestId("revenue-range-custom-end-picker"), "change", { type: "set" }, new Date(2026, 1, 10, 12));
    mockApiGet.mockClear();
    await act(async () => { fireEvent.press(r.getByTestId("revenue-range-custom-apply")); });
    await waitFor(() => r.getByTestId("revenue-cat-legend"));
    expect(calls("/admin/dashboard/revenue-by-category")).toEqual(["/admin/dashboard/revenue-by-category?start=2026-01-05&end=2026-02-10"]);
    expect(calls("/admin/dashboard/revenue-forecast")).toEqual(["/admin/dashboard/revenue-forecast?start=2026-01-05&end=2026-02-10"]);
    expect(r.getByTestId("revenue-range-custom-summary").props.children).toBe("2026-01-05 → 2026-02-10");
  });

  it("Forecast headline renders combined total, chips + caption; tabs preserved", async () => {
    const r = await mount();
    await waitFor(() => r.getByTestId("revenue-forecast-combined"));
    expect(r.getByTestId("revenue-forecast-combined").props.children).toBe("$4,321.00");
    expect(r.getByTestId("revenue-forecast-booked")).toBeTruthy();
    expect(r.getByTestId("revenue-forecast-recurring")).toBeTruthy();
    expect(r.getByText("Based on 1 booked job + 2 active subscriptions across 3 billing cycles.")).toBeTruthy();
    expect(r.getByTestId("revenue-forecast-tab-this_month")).toBeTruthy();
  });
});

describe("Phase 39A · donut tiles", () => {
  it("legend: amounts + %; UUID label coerced to Uncategorized; tap highlights + swaps center", async () => {
    const r = await mount();
    const legend = within(r.getByTestId("revenue-cat-legend"));
    expect(legend.getByText("$600.00 · 60.0%")).toBeTruthy();
    expect(legend.getByTestId("revenue-cat-legend-Uncategorized")).toBeTruthy();
    expect(r.queryByText(/3f2b8a10/)).toBeNull();
    expect(r.getByTestId("revenue-cat-item-count").props.children).toBe("2 categories");
    expect(within(r.getByTestId("revenue-cat-center")).getByText("Total")).toBeTruthy();
    fireEvent.press(legend.getByTestId("revenue-cat-legend-Chemicals"));
    const center = within(r.getByTestId("revenue-cat-center"));
    expect(center.getByText("Chemicals")).toBeTruthy();
    expect(center.getByText("60.0% · 4 line item(s)")).toBeTruthy();
    fireEvent.press(legend.getByTestId("revenue-cat-legend-Chemicals"));
    expect(within(r.getByTestId("revenue-cat-center")).getByText("Total")).toBeTruthy();
    expect(within(r.getByTestId("income-svc-legend")).getByTestId("income-svc-legend-Pool")).toBeTruthy();
    expect(r.getByTestId("income-svc-item-count").props.children).toBe("1 unit");
  });

  it("loading → empty and error states (web copy)", async () => {
    let resolve!: (v: any) => void;
    mockApiGet.mockImplementationOnce(() => new Promise((res) => { resolve = res; }));
    const r = render(<RevenueByCategoryTile range={{ start: "2026-01-01", end: "2026-01-31" }} />);
    expect(r.getByTestId("revenue-cat-loading")).toBeTruthy();
    await act(async () => { resolve({ total: 0, items: [] }); });
    expect(r.getByText("No invoiced revenue in this range yet.")).toBeTruthy();
    mockApiGet.mockRejectedValueOnce(new Error("admin_only"));
    const r2 = render(<RevenueByCategoryTile range={{ start: "2026-02-01", end: "2026-02-28" }} />);
    await waitFor(() => r2.getByTestId("revenue-cat-error"));
    expect(r2.getByText("admin_only")).toBeTruthy();
  });

  it("stale response for an old range is ignored", async () => {
    const pend: Record<string, (v: any) => void> = {};
    mockApiGet.mockImplementation((u: string) => new Promise((res) => { pend[u] = res; }));
    const r = render(<RevenueByCategoryTile range={{ start: "2026-01-01", end: "2026-01-31" }} />);
    r.rerender(<RevenueByCategoryTile range={{ start: "2025-01-01", end: "2025-12-31" }} />);
    await act(async () => { pend["/admin/dashboard/revenue-by-category?start=2026-01-01&end=2026-01-31"]({ total: 5, items: [{ category_name: "Old", amount: 5, color: "#000" }] }); });
    expect(r.getByTestId("revenue-cat-loading")).toBeTruthy();
    await act(async () => { pend["/admin/dashboard/revenue-by-category?start=2025-01-01&end=2025-12-31"]({ total: 9, items: [{ category_name: "New", amount: 9, color: "#000" }] }); });
    expect(r.getByTestId("revenue-cat-legend-New")).toBeTruthy();
    expect(r.queryByTestId("revenue-cat-legend-Old")).toBeNull();
  });
});
