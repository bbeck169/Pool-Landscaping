/**
 * Phase 54g-B · Feb-2026 — Mobile supplier analytics render test.
 *
 * Boots the ``app/reports/supplier-syncs.tsx`` screen with every
 * native dependency mocked. Covers:
 *   1. Admin/super_admin/manager see the list of supplier cards.
 *   2. Technician + customer roles hit the shared RoleGate (blocked).
 *   3. Pull-to-refresh re-invokes the ``/suppliers/analytics`` fetch.
 *   4. Failure + retry-queue badges surface only when the endpoint
 *      reports non-zero values.
 */
import React from "react";
import { render, waitFor, act } from "@testing-library/react-native";

jest.setTimeout(15000);

// ── Mocks ────────────────────────────────────────────────────────────
const mockApiGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockApiGet(...a) },
}));

let mockUserRole: any = { id: "u_admin", role: "admin", email: "a@ex.com" };
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockUserRole }),
}));

// The shared ``Header`` component pulls in ``expo-router`` for the
// back button and safe-area insets. Stub it so we don't drag native
// navigation deps into the jest env.
jest.mock("@/src/components/widgets", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactMock = require("react");
  const RN = jest.requireActual("react-native");
  return {
    Header: ({ title }: { title: string }) =>
      ReactMock.createElement(RN.Text, { testID: "test-header" }, title),
  };
});

// react-native-svg is in transformIgnorePatterns but requires no
// mocking for jest — the Svg/Rect/G exports render as plain views
// under jest-expo.

// eslint-disable-next-line import/first
import SupplierSyncsScreen from "@/app/reports/supplier-syncs";

const SAMPLE_ROWS = [
  {
    slug: "poolcorp",
    display_name: "Pool Corp",
    total_runs: 10,
    success_count: 6,
    error_count: 4,
    success_rate: 0.6,
    consecutive_errors: 2,
    last_success_at: "2026-02-10T12:00:00Z",
    last_error_at: "2026-02-14T09:00:00Z",
    last_error_message: "HTTP 500 · upstream",
    trend_daily: [
      { date: "2026-02-10", runs: 3, success: 2, error: 1, items_added: 5, items_updated: 1 },
      { date: "2026-02-11", runs: 2, success: 2, error: 0, items_added: 3, items_updated: 0 },
      { date: "2026-02-12", runs: 5, success: 2, error: 3, items_added: 4, items_updated: 2 },
    ],
    health_signal: "critical",
    health_rationale: "success rate 60% (<60%)",
  },
  {
    slug: "siteone",
    display_name: "SiteOne",
    total_runs: 5,
    success_count: 5,
    error_count: 0,
    success_rate: 1.0,
    consecutive_errors: 0,
    last_success_at: "2026-02-14T08:00:00Z",
    last_error_at: null,
    last_error_message: null,
    trend_daily: [
      { date: "2026-02-13", runs: 2, success: 2, error: 0, items_added: 1, items_updated: 0 },
      { date: "2026-02-14", runs: 3, success: 3, error: 0, items_added: 2, items_updated: 1 },
    ],
    health_signal: "healthy",
    health_rationale: "success rate 100%",
  },
];

beforeEach(() => {
  mockApiGet.mockReset();
  mockUserRole = { id: "u_admin", role: "admin", email: "a@ex.com" };
});

describe("Phase 54g-B · mobile supplier analytics render", () => {
  it("admin sees the analytics list + endpoint is /suppliers/analytics?days=30", async () => {
    mockApiGet.mockResolvedValueOnce({ suppliers: SAMPLE_ROWS });
    const { getByTestId } = render(<SupplierSyncsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    expect(mockApiGet.mock.calls[0][0]).toBe("/suppliers/analytics?days=30");
    await waitFor(() =>
      expect(getByTestId("mobile-analytics-card-poolcorp")).toBeTruthy());
    expect(getByTestId("mobile-analytics-card-siteone")).toBeTruthy();
    expect(getByTestId("mobile-analytics-signal-poolcorp")).toBeTruthy();
    expect(getByTestId("mobile-analytics-sparkline-poolcorp")).toBeTruthy();
    // Retry-queue + failure badges only where non-zero.
    expect(getByTestId("mobile-analytics-failure-badge-poolcorp")).toBeTruthy();
    expect(getByTestId("mobile-analytics-retry-badge-poolcorp")).toBeTruthy();
  });

  it("super_admin + manager also see the analytics list", async () => {
    for (const role of ["super_admin", "manager"]) {
      mockApiGet.mockReset();
      mockApiGet.mockResolvedValueOnce({ suppliers: SAMPLE_ROWS });
      mockUserRole = { id: "u", role, email: "x@x.com" };
      const { getByTestId, unmount } = render(<SupplierSyncsScreen />);
      await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
      await waitFor(() =>
        expect(getByTestId("mobile-supplier-analytics-screen")).toBeTruthy());
      unmount();
    }
  });

  it("technician + customer are blocked by the RoleGate and no fetch runs", () => {
    for (const role of ["technician", "customer"]) {
      mockApiGet.mockReset();
      mockUserRole = { id: "u", role, email: "x@x.com" };
      const { getByTestId, queryByTestId, unmount } = render(<SupplierSyncsScreen />);
      expect(getByTestId("mobile-supplier-analytics-role-gate")).toBeTruthy();
      expect(queryByTestId("mobile-supplier-analytics-screen")).toBeNull();
      expect(mockApiGet).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("aggregate summary tiles reflect the response", async () => {
    mockApiGet.mockResolvedValueOnce({ suppliers: SAMPLE_ROWS });
    const { getByTestId } = render(<SupplierSyncsScreen />);
    await waitFor(() =>
      expect(getByTestId("mobile-analytics-summary")).toBeTruthy());

    const text = (el: any): string => {
      if (el == null) return "";
      if (typeof el === "string" || typeof el === "number") return String(el);
      if (Array.isArray(el)) return el.map(text).join("");
      const k = el?.props?.children;
      return k !== undefined ? text(k) : "";
    };
    // 1 critical (poolcorp), 0 warnings, 2 retries, 4 failures.
    expect(text(getByTestId("mobile-analytics-summary-critical"))).toBe("1");
    expect(text(getByTestId("mobile-analytics-summary-warning"))).toBe("0");
    expect(text(getByTestId("mobile-analytics-summary-retries"))).toBe("2");
    expect(text(getByTestId("mobile-analytics-summary-errors"))).toBe("4");
  });

  it("pull-to-refresh triggers a refetch through the ScrollView RefreshControl", async () => {
    mockApiGet.mockResolvedValue({ suppliers: SAMPLE_ROWS });
    const { getByTestId } = render(<SupplierSyncsScreen />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));

    // Fire the underlying RefreshControl's onRefresh — this is what
    // React Native invokes when the user drags down on the list.
    const scroll = getByTestId("mobile-analytics-scroll");
    const refreshControl = scroll.props.refreshControl;
    expect(refreshControl).toBeDefined();
    await act(async () => { refreshControl.props.onRefresh(); });
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
    // Second call uses the same range (30d default).
    expect(mockApiGet.mock.calls[1][0]).toBe("/suppliers/analytics?days=30");
  });
});
