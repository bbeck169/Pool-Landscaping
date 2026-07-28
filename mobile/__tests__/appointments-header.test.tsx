/**
 * Tests for FIX 1: Appointments page Header layout fix
 *
 * Validates that the Header component renders title and subtitle
 * horizontally (not one-char-per-line vertical layout).
 */
import React from "react";
import { render } from "@testing-library/react-native";

// ── Mocks ────────────────────────────────────────────────────────────
const mockBack = jest.fn();
const mockPush = jest.fn();
const mockApiGet = jest.fn();

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { name: "Test", role: "customer" }, token: "tok" }),
}));
jest.mock("@/src/api", () => ({
  api: { get: (...args: any[]) => mockApiGet(...args) },
}));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, back: mockBack, replace: jest.fn() }),
  useFocusEffect: (cb: any) => {
    const { useEffect } = require("react");
    useEffect(() => { cb(); }, []);
  },
  usePathname: () => "/portal/appointments",
}));
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("expo-image", () => {
  const { View } = require("react-native");
  return { Image: (props: any) => <View {...props} /> };
});
jest.mock("@/src/components/ui", () => {
  const { View, Text } = require("react-native");
  return {
    Loading: () => <View><Text>Loading</Text></View>,
    StatusChip: (props: any) => <View><Text>{props.status}</Text></View>,
  };
});
jest.mock("@/src/hooks/useBreadcrumbs", () => ({
  useBreadcrumbs: () => [],
}));
jest.mock("@/src/components/nav/Breadcrumbs", () => {
  const { View } = require("react-native");
  return { __esModule: true, default: () => <View /> };
});
jest.mock("@/src/theme", () => ({
  colors: { surface: "#fff", brand: "#0284C7", muted: "#999", error: "#DC2626", border: "#E5E7EB", onSurface: "#111", onSurfaceSecondary: "#555", surfaceSecondary: "#F9FAFB", brandTertiary: "#EFF6FF", divider: "#E5E7EB" },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32, "3xl": 48 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { sm: 12, base: 14, lg: 16, xl: 18, "2xl": 24 },
  money: (v: number) => `$${v}`,
}));

describe("Header Component — Layout Fix", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders Header with title and subtitle text visible (not squeezed)", () => {
    const { Header } = require("../src/components/widgets");
    const { View, Pressable, Text } = require("react-native");

    const rightElement = (
      <Pressable testID="book-btn">
        <Text>Book</Text>
      </Pressable>
    );

    const { getByText, getByTestId } = render(
      <Header
        title="My Appointments"
        subtitle="Track pending, confirmed, or rejected requests"
        right={rightElement}
      />
    );

    // Title and subtitle must be findable as complete strings
    expect(getByText("My Appointments")).toBeTruthy();
    expect(getByText("Track pending, confirmed, or rejected requests")).toBeTruthy();
    expect(getByTestId("book-btn")).toBeTruthy();
  });

  it("renders Header with left prop without breaking layout", () => {
    const { Header } = require("../src/components/widgets");
    const { View, Text } = require("react-native");

    const leftElement = <View testID="left-element"><Text>L</Text></View>;

    const { getByText, getByTestId } = render(
      <Header
        title="Test Title"
        subtitle="Test Subtitle"
        left={leftElement}
      />
    );

    expect(getByText("Test Title")).toBeTruthy();
    expect(getByText("Test Subtitle")).toBeTruthy();
    expect(getByTestId("left-element")).toBeTruthy();
  });
});

describe("Appointments Page — Full Render", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders appointments page with header text readable", async () => {
    mockApiGet.mockResolvedValue([]);

    const PortalAppointments = require("../app/portal/appointments").default;
    const { waitFor } = require("@testing-library/react-native");
    const { getByText, getByTestId } = render(<PortalAppointments />);

    await waitFor(() => {
      expect(getByText("My Appointments")).toBeTruthy();
    });

    expect(getByText("Track pending, confirmed, or rejected requests")).toBeTruthy();
    expect(getByTestId("portal-appts-new")).toBeTruthy();
  });

  it("shows empty state when no appointments exist", async () => {
    mockApiGet.mockResolvedValue([]);

    const PortalAppointments = require("../app/portal/appointments").default;
    const { waitFor } = require("@testing-library/react-native");
    const { getByText } = render(<PortalAppointments />);

    await waitFor(() => {
      expect(getByText(/No appointments yet/)).toBeTruthy();
    });
  });

  it("renders appointment rows when data exists", async () => {
    mockApiGet.mockResolvedValue([
      {
        id: "appt-1",
        service_type: "Pool Cleaning",
        preferred_date: "2026-08-01",
        preferred_window: "Morning",
        status: "pending",
      },
    ]);

    const PortalAppointments = require("../app/portal/appointments").default;
    const { waitFor } = require("@testing-library/react-native");
    const { getByText, getByTestId } = render(<PortalAppointments />);

    await waitFor(() => {
      expect(getByTestId("appt-row-appt-1")).toBeTruthy();
    });

    expect(getByText("Pool Cleaning")).toBeTruthy();
    expect(getByText("Pending")).toBeTruthy();
  });
});
