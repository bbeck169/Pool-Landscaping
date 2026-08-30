/**
 * App shell logo single-instance test.
 *
 * Verifies the app shell renders exactly one `testID="brand-logo-img"`
 * in the authenticated layout.
 */

const mockPush = jest.fn();
jest.mock("expo-router", () => {
  const React = require("react");
  const { View, Text } = require("react-native");
  return {
    useRouter: () => ({ push: mockPush, back: jest.fn(), replace: jest.fn() }),
    useLocalSearchParams: () => ({}),
    usePathname: () => "/",
    Tabs: ({ children }: any) => React.createElement(View, { testID: "tabs" }, children),
    Redirect: ({ href }: { href: string }) =>
      React.createElement(Text, null, `Redirect:${href}`),
    Stack: ({ children }: any) => React.createElement(View, null, children),
  };
});

jest.mock("@/src/hooks/useTenantBrand", () => ({
  useTenantBrand: () => ({
    logoUrl: "https://example.com/tenant-logo.png",
    loading: false,
    refresh: jest.fn(),
  }),
  __resetSessionCache: jest.fn(),
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", role: "admin", name: "Admin" },
    isLoggedIn: true,
    login: jest.fn(),
    logout: jest.fn(),
    loading: false,
  }),
}));

jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn(async () => null),
  setItem: jest.fn(async () => {}),
}));

jest.mock("@/src/api", () => ({
  api: { get: jest.fn(), post: jest.fn(), put: jest.fn(), patch: jest.fn(), del: jest.fn() },
}));

jest.mock("@/src/services/sync/netBus", () => ({
  isOnlineNow: () => true,
  on: jest.fn(() => jest.fn()),
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
  SafeAreaProvider: ({ children }: any) => children,
}));

jest.mock("expo-linear-gradient", () => {
  const React = require("react");
  const { View } = require("react-native");
  return { LinearGradient: (props: any) => React.createElement(View, props) };
});

import React from "react";
import { render } from "@testing-library/react-native";
import { View } from "react-native";

// Render just the Header (which is used on every auth screen) and
// verify it contains exactly one brand-logo-img.
import { Header } from "@/src/components/widgets";

describe("App shell logo single instance", () => {
  test("Header renders exactly one brand-logo-img when no back and no left", () => {
    const { getAllByTestId } = render(
      <View>
        <Header title="Dashboard" />
      </View>,
    );
    const logos = getAllByTestId("brand-logo-img");
    expect(logos).toHaveLength(1);
    console.log("✅ ASL-T1: Header renders exactly one brand-logo-img");
  });

  test("Header with back=true does NOT render the logo (back button takes its place)", () => {
    const { queryByTestId } = render(
      <View>
        <Header title="Detail" back />
      </View>,
    );
    // back=true means no left prop is injected automatically
    const logo = queryByTestId("brand-logo-img");
    // With back=true and no explicit left, the Header shows back button, not logo.
    // Logo should NOT appear because the condition is `!back`.
    expect(logo).toBeNull();
    console.log("✅ ASL-T2: Header with back=true hides the logo");
  });

  test("Header with explicit left prop does NOT duplicate the logo", () => {
    const { Text } = require("react-native");
    const custom = <Text testID="custom-left">Custom</Text>;
    const { getAllByTestId, queryByTestId } = render(
      <View>
        <Header title="Custom" left={custom} />
      </View>,
    );
    expect(queryByTestId("custom-left")).toBeTruthy();
    // Since left is provided, logo should not render
    const logos = queryByTestId("brand-logo-img");
    expect(logos).toBeNull();
    console.log("✅ ASL-T3: Header with explicit left does NOT duplicate logo");
  });
});
