/**
 * Schedule map show/hide toggle — unit tests.
 *
 * Tests:
 *  1. Toggle renders with correct initial state from storage
 *  2. Tap flips visibility
 *  3. Preference persists across mount/unmount
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

/* ── Storage mock ──────────────────────────────────────────────────── */
const storageStore: Record<string, any> = {};
jest.mock("@/src/utils/storage", () => ({
  storage: {
    getItem: jest.fn(async (key: string, fallback?: any) =>
      key in storageStore ? storageStore[key] : fallback,
    ),
    setItem: jest.fn(async (key: string, value: any) => {
      storageStore[key] = value;
    }),
  },
}));

/* ── Minimal mocks for calendar dependencies ──────────────────────── */
// Native module: the import graph reaches src/background/jobGeofence.ts:19
// (via GpsConsentModal), which imports expo-task-manager. Same inline shape as
// k32-tech-scoped-schedule / GpsTracker / phase37c-job-geofence.
jest.mock("expo-task-manager", () => ({ defineTask: jest.fn() }));

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useFocusEffect: (cb: any) => {
    const React = require("react");
    React.useEffect(() => { cb(); }, []);
  },
  Redirect: () => null,
  useLocalSearchParams: () => ({}),
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", role: "admin", name: "Test Admin" },
  }),
}));

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(async () => []),
    post: jest.fn(async () => ({})),
    put: jest.fn(async () => ({})),
  },
}));

jest.mock("@/src/lib/offline/apiCache", () => ({
  cachedGet: jest.fn(async () => []),
  writeThroughJobs: jest.fn(async () => {}),
  readCachedWeekJobs: jest.fn(async () => []),
}));

jest.mock("@/src/components/OfflineBadge", () => {
  const { Text } = require("react-native");
  return () => <Text>OfflineBadge</Text>;
});

jest.mock("@/src/components/SyncBadge", () => {
  const { Text } = require("react-native");
  return () => <Text>SyncBadge</Text>;
});

jest.mock("@/src/components/PendingSyncPill", () => {
  const { Text } = require("react-native");
  return () => <Text>PendingSyncPill</Text>;
});

jest.mock("@/src/hooks/usePendingOps", () => ({
  usePendingEntityIds: () => new Set(),
}));

jest.mock("@/src/hooks/useRouteHydration", () => ({
  useRouteHydration: () => ({ meta: null }),
}));

jest.mock("@/src/hooks/useCachedJobIds", () => ({
  useCachedJobIds: () => new Set(),
}));

jest.mock("@/src/components/schedule/WeekStrip", () => {
  const { View } = require("react-native");
  return () => <View testID="week-strip" />;
});

jest.mock("@/src/components/schedule/OnMyWayButton", () => {
  const { View } = require("react-native");
  return () => <View testID="on-my-way-btn" />;
});

jest.mock("@/src/components/schedule/CouldNotServiceButton", () => {
  const { View } = require("react-native");
  return () => <View testID="cns-btn" />;
});

jest.mock("@/src/components/schedule/NavigateJobButton", () => {
  const { View } = require("react-native");
  return () => <View testID="nav-job-btn" />;
});

jest.mock("@/src/components/schedule/NavigateRouteButton", () => {
  const { View } = require("react-native");
  return () => <View testID="nav-route-btn" />;
});

jest.mock("@/src/components/schedule/CrewFilterBar", () => {
  const { View } = require("react-native");
  return () => <View testID="crew-filter-bar" />;
});

jest.mock("@/src/components/schedule/ScheduleMapLazy", () => {
  const { View } = require("react-native");
  return () => <View testID="schedule-map-lazy" />;
});

jest.mock("@/src/components/schedule/DailyRouteMap", () => {
  const { View } = require("react-native");
  return () => <View testID="daily-route-map" />;
});

jest.mock("@/src/components/MapErrorBoundary", () => ({
  MapErrorBoundary: ({ children }: any) => children,
}));

jest.mock("@/src/components/ScheduleErrorBoundary", () => ({
  ScheduleErrorBoundary: ({ children }: any) => children,
}));

jest.mock("@/src/components/widgets", () => ({
  Header: ({ children }: any) => {
    const { View } = require("react-native");
    return <View testID="header">{children}</View>;
  },
  NotificationBell: () => null,
}));

jest.mock("@/src/components/schedule/JobNotesCallout", () => {
  const { View } = require("react-native");
  return () => <View testID="job-notes-callout" />;
});

jest.mock("@/src/components/schedule/ScheduleJobEditSheet", () => {
  const { View } = require("react-native");
  return () => <View testID="edit-sheet" />;
});

jest.mock("@/src/components/weather/WeatherWidget", () => {
  const { View } = require("react-native");
  return () => <View testID="weather" />;
});

jest.mock("@/src/components/weather/RainFlag", () => {
  const { View } = require("react-native");
  return () => <View testID="rain-flag" />;
});

jest.mock("@/src/components/LandscapingClockWidget", () => {
  const { View } = require("react-native");
  return () => <View testID="clock" />;
});

jest.mock("@/src/components/ConfirmModal", () => ({
  showConfirm: jest.fn(),
}));

jest.mock("@/src/utils/diagnostics", () => ({
  logNav: jest.fn(),
}));

jest.mock("@/src/lib/jobStatus", () => ({
  jobStatusColor: () => ({ bg: "#fff", border: "#ccc" }),
}));

jest.mock("@/src/utils/scheduleStatus", () => ({
  getStatusBorderColor: () => "#ccc",
}));

jest.mock("@/src/utils/formatCustomerName", () => ({
  formatCustomerName: (n: any) => n || "",
}));

jest.mock("react-native-draggable-flatlist", () => {
  const { FlatList } = require("react-native");
  const DFL = (props: any) => <FlatList {...props} />;
  DFL.ScaleDecorator = ({ children }: any) => children;
  return { __esModule: true, default: DFL, ScaleDecorator: DFL.ScaleDecorator };
});

/* ── Import the component under test ──────────────────────────────── */
import ScheduleCalendar from "@/app/(app)/schedule/calendar";

/* ── Mock the schedule sub-components via local path ──────────────── */
jest.mock("./JobTrackerTiles", () => {
  const { View } = require("react-native");
  return () => <View testID="job-tracker-tiles" />;
}, { virtual: true });

/* ── Test suite ────────────────────────────────────────────────────── */
const MAP_VISIBLE_KEY = "schedule.mapVisible";

describe("Schedule map show/hide toggle", () => {
  const { storage } = require("@/src/utils/storage");

  beforeEach(() => {
    // Clear storage mock between tests
    for (const k of Object.keys(storageStore)) delete storageStore[k];
    jest.clearAllMocks();
  });

  it("renders toggle with default visible state", async () => {
    const { getByTestId } = render(<ScheduleCalendar />);
    await waitFor(() => {
      const toggle = getByTestId("schedule-map-toggle");
      expect(toggle).toBeTruthy();
    });
  });

  it("shows 'Hide map' when map is visible (default)", async () => {
    const { getByTestId, getByText } = render(<ScheduleCalendar />);
    await waitFor(() => {
      expect(getByTestId("schedule-map-toggle")).toBeTruthy();
    });
    // Default is visible → "Hide map"
    expect(getByText("Hide map")).toBeTruthy();
  });

  it("tapping toggle hides the map and shows 'Show map'", async () => {
    const { getByTestId, getByText, queryByTestId } = render(<ScheduleCalendar />);
    await waitFor(() => {
      expect(getByTestId("schedule-map-toggle")).toBeTruthy();
    });

    // Tap to hide
    await act(async () => {
      fireEvent.press(getByTestId("schedule-map-toggle"));
    });

    // Should show "Show map"
    expect(getByText("Show map")).toBeTruthy();
    // List|Map toggle should be gone
    expect(queryByTestId("grid-sub-mode-toggle")).toBeNull();
  });

  it("tapping toggle again shows the map", async () => {
    const { getByTestId, getByText } = render(<ScheduleCalendar />);
    await waitFor(() => {
      expect(getByTestId("schedule-map-toggle")).toBeTruthy();
    });

    // Hide
    await act(async () => {
      fireEvent.press(getByTestId("schedule-map-toggle"));
    });
    expect(getByText("Show map")).toBeTruthy();

    // Show again
    await act(async () => {
      fireEvent.press(getByTestId("schedule-map-toggle"));
    });
    expect(getByText("Hide map")).toBeTruthy();
    expect(getByTestId("grid-sub-mode-toggle")).toBeTruthy();
  });

  it("persists preference to storage on toggle", async () => {
    const { getByTestId } = render(<ScheduleCalendar />);
    await waitFor(() => {
      expect(getByTestId("schedule-map-toggle")).toBeTruthy();
    });

    // Tap to hide → should persist false
    await act(async () => {
      fireEvent.press(getByTestId("schedule-map-toggle"));
    });

    expect(storage.setItem).toHaveBeenCalledWith(MAP_VISIBLE_KEY, false);

    // Tap to show → should persist true
    await act(async () => {
      fireEvent.press(getByTestId("schedule-map-toggle"));
    });

    expect(storage.setItem).toHaveBeenCalledWith(MAP_VISIBLE_KEY, true);
  });

  it("reads saved preference on mount (hidden)", async () => {
    // Pre-set the preference to false
    storageStore[MAP_VISIBLE_KEY] = false;

    const { getByText } = render(<ScheduleCalendar />);

    await waitFor(() => {
      expect(getByText("Show map")).toBeTruthy();
    });
  });

  it("reads saved preference on mount (visible)", async () => {
    // Pre-set the preference to true
    storageStore[MAP_VISIBLE_KEY] = true;

    const { getByText } = render(<ScheduleCalendar />);

    await waitFor(() => {
      expect(getByText("Hide map")).toBeTruthy();
    });
  });

  it("has correct accessibility props", async () => {
    const { getByTestId } = render(<ScheduleCalendar />);
    await waitFor(() => {
      expect(getByTestId("schedule-map-toggle")).toBeTruthy();
    });

    const toggle = getByTestId("schedule-map-toggle");
    expect(toggle.props.accessibilityLabel).toBe("Hide map");
    expect(toggle.props.accessibilityRole).toBe("button");

    // Tap to hide
    await act(async () => {
      fireEvent.press(toggle);
    });

    const toggleAfter = getByTestId("schedule-map-toggle");
    expect(toggleAfter.props.accessibilityLabel).toBe("Show map");
  });
});
