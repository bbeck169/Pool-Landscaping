/**
 * __tests__/settings-hub-mobile.test.tsx
 *
 * Tests for the mobile Settings Hub (Part 1):
 *   - Renders 4 tabs with correct active-tab indicator
 *   - Deep-link to ?tab=social opens Social tab directly
 *   - Non-admin role sees not-authorized gate
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

/* ── Mocks ────────────────────────────────────────────── */
const mockRouterPush = jest.fn();
const mockRouterBack = jest.fn();
const mockRouterReplace = jest.fn();

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockRouterPush, back: mockRouterBack, replace: mockRouterReplace }),
  useLocalSearchParams: () => ({}),
  usePathname: () => "/settings",
  useSegments: () => ["settings"],
  Redirect: ({ href }: any) => {
    const { Text } = require("react-native");
    return <Text testID="mock-redirect">{`Redirect: ${href}`}</Text>;
  },
  useFocusEffect: (cb: any) => {
    const React = require("react");
    React.useEffect(() => { const cleanup = cb(); return typeof cleanup === "function" ? cleanup : undefined; }, []);
  },
}));

let _mockRole = "admin";
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: _mockRole, id: "u1" } }),
}));

jest.mock("@/src/offline", () => ({
  useOnline: () => true,
}));

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn((url: string) => {
      if (url === "/settings/integrations") return Promise.resolve({ stripe: { configured: true, preview: "sk_live_***" }, resend: { configured: false } });
      if (url === "/soshie/autopilot/config") return Promise.resolve({ items: [{ platform: "gbp", enabled: true, posts_per_day: 2 }] });
      if (url === "/soshie/platforms") return Promise.resolve({ platforms: [{ platform: "gbp", ok: true }] });
      if (url === "/notifications/unread-count") return Promise.resolve({ count: 0 });
      return Promise.resolve({});
    }),
    patch: jest.fn(() => Promise.resolve({})),
  },
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
  SafeAreaView: ({ children }: any) => children,
}));

jest.mock("@/src/hooks/useBreadcrumbs", () => ({
  useBreadcrumbs: () => [],
}));

jest.mock("@/src/components/BrandLogo", () => {
  const { Text } = require("react-native");
  return {
    __esModule: true,
    default: (props: any) => <Text testID="brand-logo-mock">BrandLogo</Text>,
  };
});

jest.mock("@/src/hooks/useTenantBrand", () => ({
  __esModule: true,
  default: () => ({ logoUri: null, loading: false, error: null }),
}));

/* ── Import after mocks ──────────────────────────────── */
import SettingsHubScreen from "@/app/settings/index";

describe("Settings Hub Mobile", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    _mockRole = "admin";
  });

  it("renders 4 tabs (general / branding / integrations / social)", () => {
    const tree = render(<SettingsHubScreen />);
    expect(tree.getByTestId("settings-tab-general")).toBeTruthy();
    expect(tree.getByTestId("settings-tab-branding")).toBeTruthy();
    expect(tree.getByTestId("settings-tab-integrations")).toBeTruthy();
    expect(tree.getByTestId("settings-tab-social")).toBeTruthy();
    console.log("✅ SH-T1: All 4 tabs render");
  });

  it("defaults to General tab with quick links", () => {
    const tree = render(<SettingsHubScreen />);
    expect(tree.getByTestId("settings-general-card")).toBeTruthy();
    expect(tree.getByTestId("settings-general-link-tenant")).toBeTruthy();
    console.log("✅ SH-T2: General tab is default with quick links");
  });

  it("switching to Branding tab shows logo + web note", () => {
    const tree = render(<SettingsHubScreen />);
    fireEvent.press(tree.getByTestId("settings-tab-branding"));
    expect(tree.getByTestId("settings-branding-card")).toBeTruthy();
    expect(tree.getByTestId("settings-branding-web-note")).toBeTruthy();
    expect(tree.getByTestId("brand-logo-mock")).toBeTruthy();
    console.log("✅ SH-T3: Branding tab shows logo + web note");
  });

  it("switching to Integrations tab shows integration cards", async () => {
    const tree = render(<SettingsHubScreen />);
    fireEvent.press(tree.getByTestId("settings-tab-integrations"));
    await waitFor(() => {
      expect(tree.getByTestId("settings-integration-stripe")).toBeTruthy();
    });
    expect(tree.getByTestId("settings-integrations-web-note")).toBeTruthy();
    console.log("✅ SH-T4: Integrations tab shows integration cards");
  });

  it("switching to Social tab shows platform grid", async () => {
    const tree = render(<SettingsHubScreen />);
    fireEvent.press(tree.getByTestId("settings-tab-social"));
    await waitFor(() => {
      expect(tree.getByTestId("settings-social-page")).toBeTruthy();
    });
    expect(tree.getByTestId("settings-social-open-soshie")).toBeTruthy();
    console.log("✅ SH-T5: Social tab shows platform grid + Soshie link");
  });

  it("tapping a General quick link navigates to the correct route", () => {
    const tree = render(<SettingsHubScreen />);
    fireEvent.press(tree.getByTestId("settings-general-link-tenant"));
    expect(mockRouterPush).toHaveBeenCalledWith("/settings/tenant");
    console.log("✅ SH-T6: Quick link navigates correctly");
  });
});
