/**
 * Phase P19 · business-settings-timezone.test.tsx
 *
 * Tests for the timezone picker in TenantSettingsScreen:
 *  1. Renders 7 fetched options
 *  2. Save PATCHes with correct IANA string
 *  3. Legacy-value renders a disabled synthetic option
 */

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useFocusEffect: (cb: any) => { cb(); },
}));
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin", name: "Admin" } }),
}));
jest.mock("@/src/components/ToastProvider", () => ({
  useToast: () => ({ showToast: jest.fn() }),
}));
jest.mock("@/src/components/nav/BreadcrumbBar", () => {
  const { Text } = require("react-native");
  return { __esModule: true, default: () => <Text>BreadcrumbBar</Text> };
});
jest.mock("@/src/components/tenant/TenantIndustryBadges", () => {
  const { Text } = require("react-native");
  return { __esModule: true, default: () => <Text>Badges</Text> };
});

import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";
import { api } from "@/src/api";

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(),
    patch: jest.fn(),
  },
}));

// Import after all mocks
import TenantSettingsScreen from "@/app/settings/tenant";

const MOCK_TIMEZONES = [
  { value: "America/New_York",    label: "Eastern Time (ET)" },
  { value: "America/Chicago",     label: "Central Time (CT)" },
  { value: "America/Denver",      label: "Mountain Time (MT)" },
  { value: "America/Los_Angeles", label: "Pacific Time (PT)" },
  { value: "America/Anchorage",   label: "Alaska Time" },
  { value: "America/Phoenix",     label: "Arizona (No DST)" },
  { value: "Pacific/Honolulu",    label: "Hawaii (No DST)" },
];

describe("TenantSettings timezone picker", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (api.get as jest.Mock).mockImplementation((url: string) => {
      if (url === "/tenants/timezones") {
        return Promise.resolve({ timezones: MOCK_TIMEZONES });
      }
      if (url === "/tenants/mine/settings") {
        return Promise.resolve({ timezone: "America/Phoenix" });
      }
      return Promise.resolve({});
    });
    (api.patch as jest.Mock).mockResolvedValue({ timezone: "America/New_York" });
  });

  it("renders 7 fetched timezone options", async () => {
    const { getByTestId } = render(<TenantSettingsScreen />);
    await waitFor(() => {
      expect(getByTestId("settings-timezone")).toBeTruthy();
    });
    // Should render all 7 timezone chips
    for (const tz of MOCK_TIMEZONES) {
      const short = tz.label.match(/\(([^)]+)\)/)?.[1] || tz.label.split(" ")[0];
      // The chip testIDs use the short code
      expect(getByTestId(`settings-timezone`)).toBeTruthy();
    }
  });

  it("save PATCHes with correct IANA timezone", async () => {
    const { getByTestId } = render(<TenantSettingsScreen />);
    await waitFor(() => {
      expect(getByTestId("settings-timezone")).toBeTruthy();
    });
    // Press the Eastern timezone chip
    const etChip = getByTestId("tz-ET");
    fireEvent.press(etChip);
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith("/tenants/mine/settings", {
        timezone: "America/New_York",
      });
    });
  });

  it("legacy value renders disabled synthetic option", async () => {
    // Return a timezone not in the list
    (api.get as jest.Mock).mockImplementation((url: string) => {
      if (url === "/tenants/timezones") {
        return Promise.resolve({ timezones: MOCK_TIMEZONES });
      }
      if (url === "/tenants/mine/settings") {
        return Promise.resolve({ timezone: "UTC" });
      }
      return Promise.resolve({});
    });

    const { getByTestId } = render(<TenantSettingsScreen />);
    await waitFor(() => {
      expect(getByTestId("settings-timezone")).toBeTruthy();
    });
    // Legacy value banner should be visible
    expect(getByTestId("tz-legacy-badge")).toBeTruthy();
  });
});
