/**
 * TD-admin-dashboard-outstanding-invoices-tile-mobile-parity (web 03121b822).
 *   - Admin / super_admin: tile first inside Revenue Insights, money + count,
 *     tap → /invoices?filter=outstanding.
 *   - Manager: standalone row (Revenue Insights hidden), display-only.
 *   - Technician (redirect) / owner (BE 403): no tile, no fetch.
 *   - Tile states: loading (null) / error (undefined) / empty.
 *   - RevenueChart "due" pill reads the same canonical outstanding_total.
 *   - invoices.tsx honours ?filter=<chip key>.
 */
import React from "react";
import { render, waitFor, act, fireEvent, within } from "@testing-library/react-native";

jest.setTimeout(20000);

const mockApiGet = jest.fn();
const mockPush = jest.fn();
let mockRole = "admin";
let mockParams: any = {};
const DASH = {
  active_jobs: 1, pending_jobs: 1, outstanding: 200, requested_jobs: 0, active_customers_count: 1,
  inactive_customers_count: 1, revenue_series: [{ label: "Jan", value: 10 }], recent_jobs: [],
};

jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockApiGet(...a), post: jest.fn(), patch: jest.fn() } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: mockRole, name: "Test Admin" } }) }));
jest.mock("@/src/hooks/useOfflineQuery", () => ({
  useOfflineQuery: () => ({ data: DASH, isLoading: false, error: null, refetch: jest.fn() }),
}));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => mockParams,
  useFocusEffect: (cb: any) => require("react").useEffect(() => { const c = cb(); return typeof c === "function" ? c : undefined; }, []),
  Redirect: () => null,
}));
jest.mock("@expo/vector-icons", () => {
  const { View } = require("react-native");
  return { Ionicons: (p: any) => <View testID={p.testID} /> };
});
jest.mock("@react-native-community/datetimepicker", () => () => null);
jest.mock("@/src/components/widgets", () => {
  const { Text, View } = require("react-native");
  return {
    Header: ({ title }: any) => <Text>{title}</Text>,
    FilterRow: (p: any) => <View testID={p.testID} accessibilityValue={{ text: p.value }} />,
  };
});
jest.mock("@/src/components/ui", () => {
  const { View, Text, Pressable } = require("react-native");
  return {
    Loading: (p: any) => <View testID={p.testID || "loading"} />,
    StatusChip: ({ status }: any) => <Text>{status}</Text>,
    Sheet: ({ visible, children, testID }: any) => (visible ? <View testID={testID}>{children}</View> : null),
    PrimaryButton: ({ title, onPress }: any) => <Pressable onPress={onPress}><Text>{title}</Text></Pressable>,
    EmptyState: (p: any) => <View testID={p.testID} />,
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
jest.mock("@/src/components/dashboard/UncategorizedBanner", () => stub("stub-uncategorized"));
jest.mock("@/src/components/dashboard/RevenueDateRangeFilter", () => stub("stub-range"));
jest.mock("@/src/utils/formatCustomerName", () => ({ formatCustomerName: (r: any) => r?.customer_name || "Customer" }));
jest.mock("@/src/services/readCache", () => ({ writeCache: jest.fn(async () => {}), readCache: jest.fn(async () => null) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("react-native-safe-area-context", () => ({
  ...jest.requireActual("react-native-safe-area-context"),
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

import Dashboard from "@/app/(app)/index";
import Invoices from "@/app/invoices";
import OutstandingInvoicesTile from "@/src/components/dashboard/OutstandingInvoicesTile";

const SUMMARY = { collected_this_month: 0, outstanding_total: 1234.5, outstanding_count: 3, month_label: "Nov", overdue: [] };
let summaryResp: any = SUMMARY;

function route(path: string) {
  if (path === "/payments/summary") {
    return summaryResp instanceof Error ? Promise.reject(summaryResp) : Promise.resolve(summaryResp);
  }
  if (path === "/maintenance/digest") return Promise.resolve({ overdue: 0, due_this_week: 0, items: [] });
  if (path === "/invoices/overview") return Promise.resolve({ summary: null, invoices: [] });
  return Promise.resolve([]);
}
const summaryCalls = () => mockApiGet.mock.calls.filter((c) => c[0] === "/payments/summary").length;

async function mountDash() {
  const r = render(<Dashboard />);
  await act(async () => {});
  return r;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockRole = "admin";
  mockParams = {};
  summaryResp = SUMMARY;
  mockApiGet.mockImplementation(route);
});

describe("Dashboard — Outstanding Invoices tile", () => {
  it.each([["admin"], ["super_admin"]])("%s: first item in Revenue Insights, money + count, tap → /invoices?filter=outstanding", async (role) => {
    mockRole = role;
    const r = await mountDash();
    const section = r.getByTestId("revenue-tiles-section");
    const row = within(section).getByTestId("outstanding-invoices-tile-row");
    expect(within(row).getByTestId("tile-outstanding-invoices-value").props.children).toBe("$1,234.50");
    expect(within(row).getByTestId("tile-outstanding-invoices-sublabel").props.children).toBe("3 invoices · all time");
    expect(r.getByText("Outstanding Invoices")).toBeTruthy();
    // Above the donuts / uncategorized banner.
    const order = section.findAll((n: any) => typeof n.props?.testID === "string")
      .map((n: any) => n.props.testID).filter((v: string, i: number, a: string[]) => a.indexOf(v) === i);
    expect(order.indexOf("outstanding-invoices-tile-row")).toBeLessThan(order.indexOf("stub-uncategorized"));
    expect(order.indexOf("outstanding-invoices-tile-row")).toBeLessThan(order.indexOf("stub-rev-cat"));
    fireEvent.press(r.getByTestId("tile-outstanding-invoices"));
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/invoices", params: { filter: "outstanding" } });
  });

  it("singular sublabel for 1 invoice", async () => {
    summaryResp = { ...SUMMARY, outstanding_total: 50, outstanding_count: 1 };
    const r = await mountDash();
    expect(r.getByTestId("tile-outstanding-invoices-sublabel").props.children).toBe("1 invoice · all time");
  });

  it("empty payload → $0.00 · 0 invoices, still tappable", async () => {
    summaryResp = { ...SUMMARY, outstanding_total: 0, outstanding_count: 0 };
    const r = await mountDash();
    expect(r.getByTestId("tile-outstanding-invoices-value").props.children).toBe("$0.00");
    expect(r.getByTestId("tile-outstanding-invoices-sublabel").props.children).toBe("0 invoices · all time");
    fireEvent.press(r.getByTestId("tile-outstanding-invoices"));
    expect(mockPush).toHaveBeenCalledTimes(1);
  });

  it("fetch fails → '—' / unavailable, tap disabled", async () => {
    summaryResp = new Error("boom");
    const r = await mountDash();
    await waitFor(() => expect(r.getByTestId("tile-outstanding-invoices-sublabel").props.children).toBe("unavailable"));
    expect(r.getByTestId("tile-outstanding-invoices-value").props.children).toBe("—");
    fireEvent.press(r.getByTestId("tile-outstanding-invoices"));
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("manager: standalone row outside Revenue Insights, display-only (no chevron, no tap)", async () => {
    mockRole = "manager";
    const r = await mountDash();
    expect(r.queryByTestId("revenue-tiles-section")).toBeNull();
    expect(r.getByTestId("outstanding-invoices-tile-row")).toBeTruthy();
    expect(r.getByTestId("tile-outstanding-invoices-value").props.children).toBe("$1,234.50");
    expect(r.queryByTestId("tile-outstanding-invoices-chevron")).toBeNull();
    fireEvent.press(r.getByTestId("tile-outstanding-invoices"));
    expect(mockPush).not.toHaveBeenCalled();
  });

  it.each([["technician"], ["owner"]])("%s: no tile and no lifted fetch", async (role) => {
    mockRole = role;
    const r = await mountDash();
    expect(r.queryByTestId("tile-outstanding-invoices")).toBeNull();
    // PaymentsWidget's own fetch is the only remaining caller (owner) / none (technician redirect).
    expect(summaryCalls()).toBeLessThanOrEqual(1);
  });

  it("RevenueChart 'due' pill reads canonical outstanding_total (not legacy /dashboard outstanding)", async () => {
    const r = await mountDash();
    const chart = r.getByTestId("revenue-chart");
    expect(within(chart).getByText("$1,234.50 due")).toBeTruthy();
    expect(within(chart).queryByText("$200.00 due")).toBeNull();
  });

  it("RevenueChart falls back to legacy value when the summary is unavailable", async () => {
    summaryResp = new Error("boom");
    const r = await mountDash();
    await waitFor(() => expect(r.getByTestId("tile-outstanding-invoices-sublabel").props.children).toBe("unavailable"));
    expect(within(r.getByTestId("revenue-chart")).getByText("$200.00 due")).toBeTruthy();
  });

  it("admin: one lifted fetch + PaymentsWidget's own (untouched)", async () => {
    const r = await mountDash();
    expect(summaryCalls()).toBe(2);
    expect(r.getByTestId("widget-outstanding")).toBeTruthy();
  });
});

describe("OutstandingInvoicesTile — loading state", () => {
  it("summary=null → '—' / loading…, disabled", () => {
    const onPress = jest.fn();
    const r = render(<OutstandingInvoicesTile summary={null} onPress={onPress} />);
    expect(r.getByTestId("tile-outstanding-invoices-value").props.children).toBe("—");
    expect(r.getByTestId("tile-outstanding-invoices-sublabel").props.children).toBe("loading…");
    fireEvent.press(r.getByTestId("tile-outstanding-invoices"));
    expect(onPress).not.toHaveBeenCalled();
  });
});

describe("Invoices — ?filter param", () => {
  it("?filter=outstanding pre-selects the Outstanding chip", async () => {
    mockParams = { filter: "outstanding" };
    const r = render(<Invoices />);
    await waitFor(() => r.getByTestId("invoices-filter"));
    expect(r.getByTestId("invoices-filter").props.accessibilityValue.text).toBe("outstanding");
  });

  it.each([[{}], [{ filter: "bogus" }]])("params %j → default 'all'", async (p) => {
    mockParams = p;
    const r = render(<Invoices />);
    await waitFor(() => r.getByTestId("invoices-filter"));
    expect(r.getByTestId("invoices-filter").props.accessibilityValue.text).toBe("all");
  });
});
