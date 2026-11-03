/**
 * Tests for FIX 2: Next Service Day tile on Portal Home
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

// Use getAllByText for elements that appear in both next-service cards

// ── Mocks ────────────────────────────────────────────────────────────
const mockPush = jest.fn();
const mockApiGet = jest.fn();

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { name: "Test User", role: "customer" }, token: "tok" }),
}));
jest.mock("@/src/api", () => ({
  api: { get: (...args: any[]) => mockApiGet(...args) },
}));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn(), back: jest.fn() }),
  useFocusEffect: (cb: any) => {
    const { useEffect } = require("react");
    useEffect(() => { cb(); }, []);
  },
  usePathname: () => "/portal/home",
}));
jest.mock("expo-image", () => {
  const { View } = require("react-native");
  return { Image: (props: any) => <View {...props} /> };
});
jest.mock("expo-linear-gradient", () => {
  const { View } = require("react-native");
  return { LinearGradient: (props: any) => <View {...props} /> };
});
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn().mockResolvedValue("1"),
  setItem: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("@/src/components/ui", () => {
  const { View, Text } = require("react-native");
  return {
    Loading: (props: any) => (
      <View testID={props.testID}>
        <Text>Loading</Text>
      </View>
    ),
    StatusChip: (props: any) => (
      <View>
        <Text>{props.status}</Text>
      </View>
    ),
  };
});
jest.mock("@/src/components/widgets", () => {
  const { View, Text } = require("react-native");
  return {
    Header: (props: any) => (
      <View>
        <Text>{props.title}</Text>
      </View>
    ),
    NotificationBell: () => <View />,
  };
});
jest.mock("@/src/components/Tour", () => {
  const { View } = require("react-native");
  const Tour = () => <View />;
  return { __esModule: true, default: Tour };
});
jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff", brand: "#0284C7", muted: "#999", error: "#DC2626",
    border: "#E5E7EB", onSurface: "#111", onSurfaceSecondary: "#555",
    surfaceSecondary: "#F9FAFB", brandTertiary: "#EFF6FF", divider: "#E5E7EB",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32, "3xl": 48 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { sm: 12, base: 14, lg: 16, xl: 18, "2xl": 24 },
  IMAGES: { dashboardHero: "https://example.com/hero.jpg" },
  money: (v: number) => `$${(v || 0).toFixed(2)}`,
}));

import PortalHome from "../app/portal/home";

const DASHBOARD_WITH_NEXT = {
  active_jobs: 1,
  completed_jobs: 2,
  outstanding: 149,
  unpaid_invoices: 1,
  pending_estimates: 0,
  unread_messages: 0,
  next_service: {
    id: "job-123",
    title: "Weekly Pool Cleaning",
    service_type: "Pool",
    technician_name: "Mike Rivera",
    scheduled_date: "2026-08-01T10:00:00Z",
    status: "pending",
    address: "123 Main St",
  },
  past_due: 0,
};

const DASHBOARD_NO_NEXT = {
  ...DASHBOARD_WITH_NEXT,
  next_service: null,
};

function mockDashboardApi(dashboard: any) {
  mockApiGet.mockImplementation((url: string) => {
    if (url === "/dashboard") return Promise.resolve(dashboard);
    if (url.includes("ai-employees")) return Promise.resolve({ employees: [] });
    if (url.includes("config/public")) return Promise.resolve({});
    if (url.includes("credits/balance")) return Promise.resolve({ balance_cents: 0 });
    return Promise.resolve({});
  });
}

describe("Portal Home — Next Service Day Tile", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders Next Service Day tile with service details", async () => {
    mockDashboardApi(DASHBOARD_WITH_NEXT);
    const { getByTestId, getByText, getAllByText } = render(<PortalHome />);

    await waitFor(() => {
      expect(getByTestId("portal-next-service-day")).toBeTruthy();
    }, { timeout: 10000 });

    expect(getByTestId("portal-next-service-day-detail")).toBeTruthy();
    expect(getByText("Next Service Day")).toBeTruthy();
    expect(getAllByText(/Weekly Pool Cleaning/).length).toBeGreaterThanOrEqual(1);
  }, 15000);

  it("renders empty state when no next_service", async () => {
    mockDashboardApi(DASHBOARD_NO_NEXT);
    const { getByTestId, getByText } = render(<PortalHome />);

    await waitFor(() => {
      expect(getByTestId("portal-next-service-day")).toBeTruthy();
    });

    expect(getByTestId("portal-next-service-day-empty")).toBeTruthy();
    expect(getByText("No upcoming service scheduled")).toBeTruthy();
  });

  it("navigates to job detail on tap", async () => {
    mockDashboardApi(DASHBOARD_WITH_NEXT);
    const { getByTestId } = render(<PortalHome />);

    await waitFor(() => {
      expect(getByTestId("portal-next-service-day-detail")).toBeTruthy();
    });

    fireEvent.press(getByTestId("portal-next-service-day-detail"));
    expect(mockPush).toHaveBeenCalledWith("/job/job-123");
  });

  it("shows tech name and service type in the tile", async () => {
    mockDashboardApi(DASHBOARD_WITH_NEXT);
    const { getByText } = render(<PortalHome />);

    await waitFor(() => {
      expect(getByText(/Mike Rivera/)).toBeTruthy();
    });
  });
});

// TD-portal-next-service-missing-tile-mobile-parity — /customer-portal/summary
// fallback (projected from recurring templates) when /dashboard has none.
function mockWithSummary(dashboard: any, summary: any) {
  mockApiGet.mockImplementation((url: string) => {
    if (url === "/customer-portal/summary") {
      return summary instanceof Error ? Promise.reject(summary) : Promise.resolve(summary);
    }
    if (url === "/dashboard") return Promise.resolve(dashboard);
    if (url.includes("credits/balance")) return Promise.resolve({ balance_cents: 0 });
    return Promise.resolve({});
  });
}

const PROJECTED_SUMMARY = {
  next_pool_service: { job_id: null, date: "2026-11-16", service_type: "Pool Cleaning", title: null, projected: true },
  next_landscape_service: { job_id: null, date: "2026-12-22", service_type: "Monthly Landscaping", title: null, projected: true },
};

describe("Portal Home — Next Service Day summary fallback", () => {
  beforeEach(() => { jest.clearAllMocks(); });

  it("dashboard empty + projected summary → projected tile (sooner entry) → tap opens request-service", async () => {
    mockWithSummary(DASHBOARD_NO_NEXT, PROJECTED_SUMMARY);
    const { getByTestId, getByText, queryByTestId } = render(<PortalHome />);
    await waitFor(() => expect(getByTestId("portal-next-service-day-projected")).toBeTruthy());
    expect(getByText("Scheduled · Pool Cleaning")).toBeTruthy();
    expect(getByText("16")).toBeTruthy();
    expect(queryByTestId("portal-next-service-day-empty")).toBeNull();
    expect(queryByTestId("portal-next-service-day-detail")).toBeNull();
    fireEvent.press(getByTestId("portal-next-service-day-projected"));
    expect(mockPush).toHaveBeenCalledWith("/request-service");
  });

  it("summary entry with a job_id → tap opens /job/<id>", async () => {
    mockWithSummary(DASHBOARD_NO_NEXT, {
      next_pool_service: { job_id: "job-777", date: "2026-11-20", service_type: "Pool Cleaning", title: "Weekly Pool" },
      next_landscape_service: null,
    });
    const { getByTestId, getByText } = render(<PortalHome />);
    await waitFor(() => expect(getByTestId("portal-next-service-day-projected")).toBeTruthy());
    expect(getByText("Weekly Pool")).toBeTruthy();
    fireEvent.press(getByTestId("portal-next-service-day-projected"));
    expect(mockPush).toHaveBeenCalledWith("/job/job-777");
  });

  it("summary request fails → empty state still renders", async () => {
    mockWithSummary(DASHBOARD_NO_NEXT, new Error("network"));
    const { getByTestId, queryByTestId } = render(<PortalHome />);
    await waitFor(() => expect(getByTestId("portal-next-service-day-empty")).toBeTruthy());
    expect(queryByTestId("portal-next-service-day-projected")).toBeNull();
  });

  it("materialized /dashboard job wins over the summary", async () => {
    mockWithSummary(DASHBOARD_WITH_NEXT, PROJECTED_SUMMARY);
    const { getByTestId, queryByTestId } = render(<PortalHome />);
    await waitFor(() => expect(getByTestId("portal-next-service-day-detail")).toBeTruthy());
    expect(queryByTestId("portal-next-service-day-projected")).toBeNull();
    fireEvent.press(getByTestId("portal-next-service-day-detail"));
    expect(mockPush).toHaveBeenCalledWith("/job/job-123");
  });
});
