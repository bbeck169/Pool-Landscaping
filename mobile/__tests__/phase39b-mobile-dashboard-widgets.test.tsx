/**
 * Phase 39B · mobile dashboard — 7 missing web widgets.
 *   Order: Mass Messaging → Revenue insights → Action Cards → KPI grid →
 *   Topline → Soshie → Weather → Requested banner → BulkOps → Crew →
 *   Routing Cost → Warranties → Referral.
 *   Role gates (web Dashboard.jsx): Mass Messaging admin/super_admin;
 *   Action Cards admin/super_admin/manager; Soshie + 4 admin tiles
 *   super_admin/admin/owner.
 */
import React from "react";
import { render, waitFor, act, fireEvent } from "@testing-library/react-native";
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
  return function MockPicker(p: any) { return <View testID={p.testID} />; };
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
jest.mock("@/src/components/dashboard/RevenueByCategoryTile", () => stub("stub-rev-cat"));
jest.mock("@/src/components/dashboard/IncomeByServiceCategoryTile", () => stub("stub-income-svc"));
jest.mock("@/src/components/dashboard/RevenueForecastTile", () => stub("stub-forecast"));
jest.mock("@/src/utils/formatCustomerName", () => ({ formatCustomerName: (r: any) => r?.customer_name || "Customer" }));

import Dashboard from "@/app/(app)/index";

const DASH = {
  active_jobs: 1, pending_jobs: 1, outstanding: 0, requested_jobs: 2, active_customers_count: 1, inactive_customers_count: 1,
  revenue_series: [], recent_jobs: [], bulk_actions_24h: 5, bulk_actions_undone_24h: 1, bulk_actions_expired_24h: 2,
};
const CARDS = { today_routes: 3, pending_checkins: 0, unpaid_invoices: 0, overdue_invoices: 2, new_leads_today: 0, open_alerts: 0, missed_services_today: 0 };
const CREW = (range: string) => ({
  range,
  crews: [
    { crew_id: "c1", crew_name: "Blue Crew", color: "#3B82F6", member_count: 2, jobs_completed: 4, revenue_subtotal: 1234.5 },
    { crew_id: "c2", crew_name: "Idle Crew", member_count: 1, jobs_completed: 0, revenue_subtotal: 0 },
  ],
  totals: { jobs_completed: 4, revenue_subtotal: 1234.5 },
});
const ROUTING = { total_calls: 10, traffic_aware_calls: 6, traffic_unaware_calls: 4, est_traffic_aware_cost_usd: 0.3 };
const WARR = { items: [{ id: "w1", contract_name: "Annual Plan", customer_id: "cust1", customer_name: "Aimee", days_remaining: 5 }] };
const SOSHIE = { scheduled: 2, published: 1, flagged: 1, blocked: 0, failed: 0, next_up: [{ post_id: "p1", platform: "facebook", scheduled_at: "2026-10-11T15:00:00Z", preview: "Pool tips" }] };

function route(path: string) {
  if (path === "/dashboard/action-cards") return Promise.resolve(CARDS);
  if (path.startsWith("/admin/crew-productivity")) return Promise.resolve(CREW(path.split("range=")[1]));
  if (path.startsWith("/reports/routing-cost-telemetry")) return Promise.resolve(ROUTING);
  if (path.startsWith("/warranties/expiring-soon")) return Promise.resolve(WARR);
  if (path === "/soshie/publishing/today-summary") return Promise.resolve(SOSHIE);
  if (path === "/maintenance/digest") return Promise.resolve({ overdue: 0, due_this_week: 0, items: [] });
  if (path === "/payments/summary") return Promise.resolve({ collected_this_month: 0, outstanding_total: 0, outstanding_count: 0, month_label: "Oct", overdue: [] });
  if (path.startsWith("/referrals/admin/analytics")) return Promise.resolve({ revenue_attribution: { total_usd: 1 }, funnel: { converted: 1 } });
  return Promise.resolve([]);
}
const called = (p: string) => mockApiGet.mock.calls.map((c) => c[0] as string).filter((u) => u.startsWith(p));

function ids(node: any, out: string[] = []): string[] {
  if (!node) return out;
  if (Array.isArray(node)) { node.forEach((n) => ids(n, out)); return out; }
  if (node.props?.testID) out.push(node.props.testID);
  (node.children || []).forEach((c: any) => typeof c === "object" && ids(c, out));
  return out;
}

async function mount() {
  const r = render(<Dashboard />);
  await waitFor(() => r.getByTestId("dashboard-kpi-grid"));
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

describe("Phase 39B · mount + section order", () => {
  it("admin: all 7 widgets render in web order", async () => {
    const r = await mount();
    await waitFor(() => r.getByTestId("dashboard-action-cards"));
    await waitFor(() => r.getByTestId("crew-productivity-tile-table"));
    const o = ids(r.toJSON());
    const seq = ["mass-messaging-card", "revenue-tiles-section", "dashboard-topline-tiles", "dashboard-kpi-grid", "dashboard-action-cards",
      "soshie-publishing-tile", "stub-weather", "new-requests-banner", "bulk-ops-audit-tile", "crew-productivity-tile",
      "routing-cost-tile", "warranties-expiring-tile", "tile-referral-revenue", "revenue-chart"];
    const idx = seq.map((id) => { const i = o.indexOf(id); expect([id, i >= 0]).toEqual([id, true]); return i; });
    expect([...idx].sort((a, b) => a - b)).toEqual(idx);
  });

  it("fetches each widget endpoint with web query params", async () => {
    await mount();
    expect(called("/dashboard/action-cards")).toEqual(["/dashboard/action-cards"]);
    expect(called("/admin/crew-productivity")).toEqual(["/admin/crew-productivity?range=this_week"]);
    expect(called("/reports/routing-cost-telemetry")).toEqual(["/reports/routing-cost-telemetry?window_days=30"]);
    expect(called("/warranties/expiring-soon")).toEqual(["/warranties/expiring-soon?days=30"]);
    expect(called("/soshie/publishing/today-summary")).toEqual(["/soshie/publishing/today-summary"]);
  });
});

describe("Phase 39B · role gates", () => {
  const ADMIN_TILES = ["soshie-publishing-tile", "bulk-ops-audit-tile", "crew-productivity-tile", "routing-cost-tile", "warranties-expiring-tile"];

  it("manager: Action Cards only — no Mass Messaging / Soshie / admin tiles", async () => {
    mockRole = "manager";
    const r = await mount();
    await waitFor(() => r.getByTestId("dashboard-action-cards"));
    expect(r.queryByTestId("mass-messaging-card")).toBeNull();
    ADMIN_TILES.forEach((id) => expect([id, r.queryByTestId(id)]).toEqual([id, null]));
    expect(called("/admin/crew-productivity")).toEqual([]);
    expect(called("/soshie/publishing")).toEqual([]);
  });

  it("owner: Soshie + admin tiles; no Mass Messaging / Action Cards", async () => {
    mockRole = "owner";
    const r = await mount();
    ADMIN_TILES.forEach((id) => expect(r.getByTestId(id)).toBeTruthy());
    expect(r.queryByTestId("mass-messaging-card")).toBeNull();
    expect(r.queryByTestId("dashboard-action-cards")).toBeNull();
    expect(called("/dashboard/action-cards")).toEqual([]);
  });

  it("super_admin: everything", async () => {
    mockRole = "super_admin";
    const r = await mount();
    await waitFor(() => r.getByTestId("dashboard-action-cards"));
    ["mass-messaging-card", ...ADMIN_TILES].forEach((id) => expect(r.getByTestId(id)).toBeTruthy());
  });
});

describe("Phase 39B · widget behaviour", () => {
  it("Mass Messaging Compose → /marketing/broadcasts", async () => {
    const r = await mount();
    fireEvent.press(r.getByTestId("mass-messaging-compose-btn"));
    expect(mockPush).toHaveBeenCalledWith("/marketing/broadcasts");
  });

  it("Action Cards: zero counts hidden except Intelligence Alerts; tap navigates", async () => {
    const r = await mount();
    await waitFor(() => r.getByTestId("dashboard-action-cards"));
    expect(r.getByTestId("dashboard-action-card-today_routes-count").props.children).toBe(3);
    expect(r.getByTestId("dashboard-action-card-overdue_invoices")).toBeTruthy();
    expect(r.getByTestId("dashboard-action-card-open_alerts")).toBeTruthy();
    for (const k of ["pending_checkins", "unpaid_invoices", "new_leads_today", "missed_services_today"]) {
      expect([k, r.queryByTestId(`dashboard-action-card-${k}`)]).toEqual([k, null]);
    }
    fireEvent.press(r.getByTestId("dashboard-action-card-overdue_invoices"));
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/invoices", params: { status: "overdue" } });
  });

  it("Bulk Ops reads /dashboard fields; hides when a field is missing", async () => {
    const r = await mount();
    expect(r.getByTestId("bulk-ops-audit-tile-total-value").props.children).toBe(5);
    expect(r.getByTestId("bulk-ops-audit-tile-undone-value").props.children).toBe(1);
    expect(r.getByTestId("bulk-ops-audit-tile-expired-value").props.children).toBe(2);
    r.unmount();
    mockDash = { ...DASH, bulk_actions_expired_24h: undefined };
    const r2 = await mount();
    expect(r2.queryByTestId("bulk-ops-audit-tile")).toBeNull();
  });

  it("Crew Productivity: hides idle crews, totals, range tab refetches", async () => {
    const r = await mount();
    await waitFor(() => r.getByTestId("crew-productivity-row-c1"));
    expect(r.queryByTestId("crew-productivity-row-c2")).toBeNull();
    expect(r.getByTestId("crew-productivity-row-c1-revenue").props.children).toBe("$1,234.50");
    expect(r.getByTestId("crew-productivity-tile-totals-jobs").props.children).toBe(4);
    await act(async () => { fireEvent.press(r.getByTestId("crew-productivity-range-option-last_week")); });
    expect(called("/admin/crew-productivity")).toContain("/admin/crew-productivity?range=last_week");
    expect(r.getByText("Crew Productivity (Last Week)")).toBeTruthy();
  });

  it("Routing Cost window chip refetches; Warranties row opens customer; Soshie attention badge", async () => {
    const r = await mount();
    await waitFor(() => r.getByTestId("routing-cost-extra-row"));
    await act(async () => { fireEvent.press(r.getByTestId("routing-cost-window-7")); });
    expect(called("/reports/routing-cost-telemetry")).toContain("/reports/routing-cost-telemetry?window_days=7");
    fireEvent.press(r.getByTestId("warranties-expiring-row-0"));
    expect(mockPush).toHaveBeenCalledWith("/customer/cust1");
    expect(r.getByTestId("soshie-publishing-tile-attention")).toBeTruthy();
    expect(r.getByTestId("soshie-publishing-tile-next-p1")).toBeTruthy();
  });
});
