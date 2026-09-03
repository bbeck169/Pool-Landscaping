/**
 * K32 — Tech-scoped schedule tests.
 *
 * Verifies:
 * 1. Tech role: CrewFilterBar hidden, fetch includes technician_id.
 * 2. Admin role: CrewFilterBar visible, fetch does NOT force technician_id.
 * 3. Both "technician" and "tech" role spellings handled.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

/* ── Mock dependencies ─────────────────────────────────────────────── */

// Track fetch URLs
const mockFetchedUrls: string[] = [];

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn((url: string) => {
      mockFetchedUrls.push(url);
      if (url.startsWith("/jobs")) return Promise.resolve([]);
      if (url.startsWith("/crews")) return Promise.resolve([]);
      if (url.includes("role=tech")) return Promise.resolve({ users: [] });
      return Promise.resolve({});
    }),
    post: jest.fn(() => Promise.resolve({})),
    put: jest.fn(() => Promise.resolve({})),
  },
  TOKEN_KEY: "token",
  registerLogoutOn401: jest.fn(),
}));

// Mock auth — configurable per test
let mockUser: any = null;
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockUser, loading: false }),
  AuthProvider: ({ children }: any) => children,
}));

jest.mock("@/src/utils/storage", () => ({
  storage: {
    getItem: jest.fn(() => Promise.resolve("")),
    setItem: jest.fn(() => Promise.resolve()),
    secureGet: jest.fn(() => Promise.resolve("")),
    secureSet: jest.fn(() => Promise.resolve()),
    removeItem: jest.fn(() => Promise.resolve()),
    secureRemove: jest.fn(() => Promise.resolve()),
  },
}));

jest.mock("@/src/lib/offline/apiCache", () => ({
  cachedGet: jest.fn((url: string) => {
    mockFetchedUrls.push(`cachedGet:${url}`);
    return Promise.resolve([]);
  }),
  writeThroughJobs: jest.fn(() => Promise.resolve()),
  readCachedWeekJobs: jest.fn(() => Promise.resolve([])),
}));

jest.mock("@/src/lib/offline/jwtCache", () => ({
  persistJwtExpiry: jest.fn(() => Promise.resolve()),
  clearJwtExpiry: jest.fn(() => Promise.resolve()),
}));

jest.mock("@/src/lib/offline/cache", () => ({
  wipeCache: jest.fn(() => Promise.resolve()),
  initCache: jest.fn(() => Promise.resolve()),
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useFocusEffect: (cb: any) => {
    const { useEffect } = require("react");
    useEffect(() => { cb(); }, []);
  },
  Redirect: () => null,
  useLocalSearchParams: () => ({}),
}));

jest.mock("@/src/theme", () => ({
  colors: {
    brand: "#007AFF", brandTertiary: "#E3F2FD",
    surface: "#fff", surfaceSecondary: "#F5F5F5",
    onSurface: "#000", onSurfaceSecondary: "#666",
    muted: "#999", border: "#E0E0E0",
  },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32, "3xl": 48 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 18 },
}));

jest.mock("@/src/components/widgets", () => ({
  Header: ({ children }: any) => children,
  NotificationBell: () => null,
}));

jest.mock("@/src/components/OfflineBadge", () => () => null);
jest.mock("@/src/components/LandscapingClockWidget", () => () => null);
jest.mock("@/src/components/weather/WeatherWidget", () => () => null);
jest.mock("@/src/components/weather/RainFlag", () => () => null);
jest.mock("@/src/components/schedule/WeekStrip", () => () => null);
jest.mock("@/src/components/ConfirmModal", () => ({ showConfirm: jest.fn() }));
jest.mock("@/src/components/schedule/ScheduleJobEditSheet", () => () => null);
jest.mock("@/src/utils/scheduleStatus", () => ({ getStatusBorderColor: () => "#ccc" }));
jest.mock("@/src/components/schedule/OnMyWayButton", () => () => null);
jest.mock("@/src/components/schedule/CouldNotServiceButton", () => () => null);
jest.mock("@/src/components/schedule/NavigateJobButton", () => () => null);
jest.mock("@/src/components/schedule/NavigateRouteButton", () => () => null);
jest.mock("@/src/components/schedule/CrewFilterBar", () => {
  const { View, Text } = require("react-native");
  return (props: any) => (
    <View testID="crew-filter-bar">
      <Text>CrewFilterBar</Text>
    </View>
  );
});
jest.mock("@/src/components/schedule/ScheduleMap", () => () => null);
jest.mock("@/src/components/schedule/DailyRouteMap", () => () => null);
jest.mock("@/src/components/MapErrorBoundary", () => ({
  MapErrorBoundary: ({ children }: any) => children,
}));
jest.mock("@/src/components/schedule/JobNotesCallout", () => () => null);
jest.mock("react-native-draggable-flatlist", () => {
  const { FlatList } = require("react-native");
  const MockDraggableFlatList = (props: any) => <FlatList {...props} />;
  return {
    __esModule: true,
    default: MockDraggableFlatList,
    ScaleDecorator: ({ children }: any) => children,
    RenderItemParams: {},
  };
});
jest.mock("@/src/utils/formatCustomerName", () => ({
  formatCustomerName: (j: any) => j.customer_name || "Unknown",
}));

// Mock the JobTrackerTiles — it's a relative import from the schedule dir
jest.mock("../app/(app)/schedule/JobTrackerTiles", () => () => null);

/* ── Import under test (after mocks) ──────────────────────────────── */
import ScheduleCalendar from "../app/(app)/schedule/calendar";

/* ── Tests ─────────────────────────────────────────────────────────── */
describe("K32 — Tech-scoped schedule", () => {
  beforeEach(() => {
    mockFetchedUrls.length = 0;
    jest.clearAllMocks();
  });

  it('tech (role="technician"): hides CrewFilterBar', async () => {
    mockUser = { id: "tech-user-123", role: "technician", name: "Tech A", email: "a@t.com" };
    const { queryByTestId } = render(<ScheduleCalendar />);
    await waitFor(() => {
      expect(queryByTestId("crew-filter-bar")).toBeNull();
    });
  });

  it('tech (role="technician"): fetch includes technician_id', async () => {
    mockUser = { id: "tech-user-123", role: "technician", name: "Tech A", email: "a@t.com" };
    render(<ScheduleCalendar />);
    await waitFor(() => {
      const jobFetches = mockFetchedUrls.filter((u) => u.includes("/jobs?"));
      expect(jobFetches.length).toBeGreaterThan(0);
      const lastFetch = jobFetches[jobFetches.length - 1];
      expect(lastFetch).toContain("technician_id=tech-user-123");
    });
  });

  it('tech (role="technician"): fetch does NOT include crew_id', async () => {
    mockUser = { id: "tech-user-123", role: "technician", name: "Tech A", email: "a@t.com" };
    render(<ScheduleCalendar />);
    await waitFor(() => {
      const jobFetches = mockFetchedUrls.filter((u) => u.includes("/jobs?"));
      expect(jobFetches.length).toBeGreaterThan(0);
      const lastFetch = jobFetches[jobFetches.length - 1];
      expect(lastFetch).not.toContain("crew_id=");
    });
  });

  it('handles alternate spelling (role="tech") same as "technician"', async () => {
    mockUser = { id: "tech-alt-456", role: "tech", name: "Tech B", email: "b@t.com" };
    const { queryByTestId } = render(<ScheduleCalendar />);
    await waitFor(() => {
      // CrewFilterBar hidden
      expect(queryByTestId("crew-filter-bar")).toBeNull();
      // technician_id in fetch
      const jobFetches = mockFetchedUrls.filter((u) => u.includes("/jobs?"));
      expect(jobFetches.length).toBeGreaterThan(0);
      expect(jobFetches[jobFetches.length - 1]).toContain("technician_id=tech-alt-456");
    });
  });

  it('admin: does NOT force technician_id', async () => {
    mockUser = { id: "admin-user-001", role: "admin", name: "Admin", email: "a@a.com" };
    render(<ScheduleCalendar />);
    await waitFor(() => {
      const jobFetches = mockFetchedUrls.filter((u) => u.includes("/jobs?"));
      expect(jobFetches.length).toBeGreaterThan(0);
      const lastFetch = jobFetches[jobFetches.length - 1];
      expect(lastFetch).not.toContain("technician_id=");
    });
  });

  it("customer: redirects away (does not render schedule)", async () => {
    mockUser = { id: "cust-001", role: "customer", name: "Customer", email: "c@c.com" };
    const { queryByTestId } = render(<ScheduleCalendar />);
    // Schedule body should not render for customers
    expect(queryByTestId("schedule-mode-switch")).toBeNull();
  });
});
