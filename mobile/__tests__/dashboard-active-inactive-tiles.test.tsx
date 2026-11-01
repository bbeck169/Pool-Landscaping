/**
 * Ship 1 · Dashboard Active/Inactive Customers tile swap.
 *
 * Mocks /api/dashboard with active_customers_count + inactive_customers_count
 * and asserts the new KPI tiles render while legacy Technicians is gone.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

jest.setTimeout(15000);

const mockApiGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: jest.fn().mockResolvedValue({}),
    patch: jest.fn().mockResolvedValue({}),
    del: jest.fn().mockResolvedValue({}),
  },
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "admin", name: "Test Admin" } }),
}));

jest.mock("expo-router", () => {
  const ReactLib = require("react");
  return {
    useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
    useFocusEffect: (cb: () => any) => {
      ReactLib.useEffect(() => {
        const cleanup = cb();
        return typeof cleanup === "function" ? cleanup : undefined;
      }, []);
    },
    Redirect: () => null,
  };
});

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
}));

jest.mock("@/src/theme", () => ({
  colors: {
    bg: "#000", card: "#111", surface: "#222", surfaceHover: "#333",
    surfaceSecondary: "#f5f5f5", onSurfaceSecondary: "#666",
    border: "#444", brand: "#0af", brandTertiary: "#0af",
    text: "#fff", muted: "#888", danger: "#f00", ok: "#0f0",
    warn: "#fa0", info: "#0af", success: "#0f0", onSurface: "#333",
    divider: "#eee",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, "2xl": 24, "3xl": 32 },
  radius: { sm: 4, md: 8, lg: 12, xl: 16, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, md: 14, lg: 16, xl: 20 },
  money: (n: any) => `$${(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
  IMAGES: {},
  // Mirrors src/theme.ts:74 — AppTextInput (via RevenueDateRangeFilter) reads it at module load.
  inputColors: { bg: "#FFFFFF", text: "#000080", placeholder: "rgba(0,0,128,0.55)" },
}));

jest.mock("@/src/components/widgets", () => ({
  Header: ({ title }: any) => {
    const { Text } = require("react-native");
    return <Text testID="mock-header">{title}</Text>;
  },
}));

jest.mock("@/src/components/ui", () => {
  const { View, Text, Pressable } = require("react-native");
  return {
    Loading: (p: any) => <View testID={p.testID || "loading"} />,
    StatusChip: ({ status }: any) => <Text>{status}</Text>,
    Sheet: ({ children }: any) => <View>{children}</View>,
    PrimaryButton: ({ title, onPress }: any) => (
      <Pressable onPress={onPress}><Text>{title}</Text></Pressable>
    ),
  };
});

jest.mock("@/src/components/SyncStatusPill", () => () => null);
jest.mock("@/src/components/BudgetHealthCard", () => () => null);
jest.mock("@/src/components/LandscapingClockWidget", () => () => null);
jest.mock("@/src/components/weather/WeatherWidget", () => () => null);
jest.mock("@/src/components/ai/CreditsBudgetChip", () => () => null);
jest.mock("@/src/components/dashboard/EbitTile", () => () => null);
jest.mock("expo-image", () => ({ Image: () => null }));
jest.mock("expo-linear-gradient", () => ({ LinearGradient: ({ children }: any) => children }));

jest.mock("@/src/utils/formatCustomerName", () => ({
  formatCustomerName: (row: any) =>
    (typeof row === "string" ? row : row?.customer_name) || "Unknown Customer",
}));

import Dashboard from "@/app/(app)/index";

// Recursive text extraction helper.
function textOf(el: any): string {
  if (el == null) return "";
  if (typeof el === "string" || typeof el === "number") return String(el);
  if (Array.isArray(el)) return el.map(textOf).join("");
  const kids = el?.props?.children;
  return kids !== undefined ? textOf(kids) : "";
}

const DASHBOARD_PAYLOAD = {
  revenue: 5000,
  active_jobs: 10,
  pending_jobs: 3,
  outstanding: 200,
  requested_jobs: 0,
  active_customers_count: 100,
  inactive_customers_count: 50,
  total_customers: 150,
  total_technicians: 4,
  revenue_series: [],
  recent_jobs: [],
};

beforeEach(() => {
  mockApiGet.mockReset();
  mockApiGet.mockImplementation((path: string) => {
    if (path === "/dashboard") return Promise.resolve(DASHBOARD_PAYLOAD);
    if (path === "/maintenance/digest") return Promise.resolve({ overdue: 0, due_this_week: 0, items: [] });
    if (path === "/quotes/ready-to-schedule") return Promise.resolve([]);
    if (path === "/payments/summary") return Promise.resolve({ collected_this_month: 0, outstanding_total: 0, outstanding_count: 0, month_label: "Aug", overdue: [] });
    if (path.startsWith("/referrals/analytics")) return Promise.resolve({ revenue_attribution: { total_usd: 0 }, funnel: { converted: 0 } });
    if (path.includes("/technicians")) return Promise.resolve([]);
    return Promise.resolve([]);
  });
});

describe("Dashboard · Active/Inactive Customers tiles (Ship 1)", () => {
  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip('renders "Active Customers" tile with value 100', async () => {
    const tree = render(<Dashboard />);

    await waitFor(() => {
      expect(tree.getByTestId("kpi-active-customers")).toBeTruthy();
    });

    const tile = tree.getByTestId("kpi-active-customers");
    const text = textOf(tile);
    expect(text).toContain("100");
    expect(text).toContain("Active Customers");
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip('renders "Inactive Customers" tile with value 50', async () => {
    const tree = render(<Dashboard />);

    await waitFor(() => {
      expect(tree.getByTestId("kpi-inactive-customers")).toBeTruthy();
    });

    const tile = tree.getByTestId("kpi-inactive-customers");
    const text = textOf(tile);
    expect(text).toContain("50");
    expect(text).toContain("Inactive Customers");
  });

  it('legacy "Technicians" copy is NOT in the tree', async () => {
    const tree = render(<Dashboard />);

    await waitFor(() => {
      expect(tree.getByTestId("kpi-inactive-customers")).toBeTruthy();
    });

    expect(tree.queryByTestId("kpi-technicians")).toBeNull();
  });

  it('legacy total_customers "150" is NOT rendered as a standalone tile (kpi-customers absent)', async () => {
    const tree = render(<Dashboard />);

    await waitFor(() => {
      expect(tree.getByTestId("kpi-inactive-customers")).toBeTruthy();
    });

    expect(tree.queryByTestId("kpi-customers")).toBeNull();
  });

  // Dashboard parity · web P2 tile cleanup removed "Active Customers";
  // Inactive Customers stays as the sole customer-status tile.
  it('"Active Customers" tile is gone (web parity); Inactive Customers shows 50', async () => {
    const tree = render(<Dashboard />);
    await waitFor(() => expect(tree.getByTestId("kpi-inactive-customers")).toBeTruthy());
    expect(tree.queryByTestId("kpi-active-customers")).toBeNull();
    const text = textOf(tree.getByTestId("kpi-inactive-customers"));
    expect(text).toContain("50");
    expect(text).toContain("Inactive Customers");
  });
});
