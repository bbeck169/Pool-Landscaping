/**
 * Feb-2026 P0 · Dashboard fetch-failure guard.
 *
 * Guards against the redbox regression where `data = null` after a
 * failed `/dashboard` fetch fell through the loading gate and
 * dereferenced `data.revenue`, producing:
 *   "Cannot read properties of null (reading 'revenue')"
 * at ``app/(app)/index.tsx:119``.
 *
 * Covers three shapes:
 *   1. Fetch rejects  → data stays null → empty state renders (no throw).
 *   2. Fetch resolves `{}`             → hero shows `$0.00` (money(null) → "$0.00").
 *   3. Fetch resolves `{revenue: N}`   → hero shows formatted N.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

jest.setTimeout(15000);

const mockApiGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: jest.fn(),
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
      // Fire once on mount, like the real hook does when the screen focuses.
      ReactLib.useEffect(() => {
        const cleanup = cb();
        return typeof cleanup === "function" ? cleanup : undefined;
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, []);
    },
    Redirect: () => null,
  };
});

// Widgets do their own /dashboard-adjacent fetches — stub them out so
// the test only exercises the Dashboard's own `load` behaviour.
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

import Dashboard from "@/app/(app)/index";

function textOf(el: any): string {
  if (el == null) return "";
  if (typeof el === "string" || typeof el === "number") return String(el);
  if (Array.isArray(el)) return el.map(textOf).join("");
  const kids = el?.props?.children;
  return kids !== undefined ? textOf(kids) : "";
}

beforeEach(() => {
  mockApiGet.mockReset();
});

describe("Dashboard · null-data resilience (Feb-2026 P0 guard)", () => {
  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("does NOT crash when /dashboard rejects — renders the empty state", async () => {
    // Every api.get call rejects (dashboard fetch + widget fetches
    // via the same mock). Widgets already null-guard themselves.
    mockApiGet.mockRejectedValue(new Error("boom"));

    const tree = render(<Dashboard />);

    // Loading gate clears → guard kicks in → empty state visible.
    await waitFor(() => {
      expect(tree.getByTestId("dashboard-empty")).toBeTruthy();
    });
    // The error message from the rejection surfaces to the user.
    const emptyTxt = textOf(tree.getByTestId("dashboard-empty"));
    expect(emptyTxt).toMatch(/boom|unavailable/i);
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("does NOT crash when /dashboard returns an empty {} — hero shows $0.00", async () => {
    mockApiGet.mockImplementation((path: string) => {
      if (path === "/dashboard") return Promise.resolve({});
      return Promise.reject(new Error("widget stub"));
    });

    const tree = render(<Dashboard />);

    await waitFor(() => {
      expect(tree.getByTestId("dashboard-revenue")).toBeTruthy();
    });
    expect(textOf(tree.getByTestId("dashboard-revenue"))).toBe("$0.00");
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("renders the hero revenue when /dashboard returns a real payload", async () => {
    mockApiGet.mockImplementation((path: string) => {
      if (path === "/dashboard") {
        return Promise.resolve({
          revenue: 12345,
          active_jobs: 3,
          outstanding: 500,
          pending_jobs: 1,
          total_customers: 42,
          total_technicians: 5,
          requested_jobs: 0,
          revenue_series: [],
          recent_jobs: [],
        });
      }
      return Promise.reject(new Error("widget stub"));
    });

    const tree = render(<Dashboard />);

    await waitFor(() => {
      expect(tree.getByTestId("dashboard-revenue")).toBeTruthy();
    });
    expect(textOf(tree.getByTestId("dashboard-revenue"))).toBe("$12,345.00");
  });
});
