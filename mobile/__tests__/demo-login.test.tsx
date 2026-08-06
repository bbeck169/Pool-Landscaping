/**
 * Tests for FIX 3 + Feb 2026 Demo-Login P0 hotfix — preview-only
 * demo accounts on the mobile login screen.
 *
 * The gate is now RUNTIME (fetched from ``/api/config/public``)
 * instead of the previous build-time ``process.env.EXPO_PUBLIC_ENV``,
 * so tests mock ``api.get`` to return the desired ``app_env`` value.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

// ── Mocks ────────────────────────────────────────────────────────────
const mockLogin = jest.fn().mockResolvedValue(undefined);
const mockReplace = jest.fn();
const mockPush = jest.fn();
const mockApiGet = jest.fn();
const mockApiPost = jest.fn();

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ login: mockLogin, user: null, token: null }),
}));
jest.mock("@/src/api", () => ({
  api: { get: (...args: any[]) => mockApiGet(...args), post: (...args: any[]) => mockApiPost(...args) },
}));
jest.mock("expo-router", () => ({
  useRouter: () => ({ replace: mockReplace, push: mockPush, back: jest.fn() }),
  useFocusEffect: jest.fn(),
}));
jest.mock("expo-image", () => {
  const { View } = require("react-native");
  return { Image: (props: any) => <View {...props} /> };
});
jest.mock("expo-linear-gradient", () => {
  const { View } = require("react-native");
  return { LinearGradient: (props: any) => <View {...props} /> };
});
jest.mock("react-native-keyboard-controller", () => {
  const { ScrollView } = require("react-native");
  return { KeyboardAwareScrollView: (props: any) => <ScrollView {...props} /> };
});
jest.mock("@/src/components/ui", () => {
  const { Pressable, Text } = require("react-native");
  return {
    PrimaryButton: (props: any) => (
      <Pressable testID={props.testID} onPress={props.onPress}>
        <Text>{props.title}</Text>
      </Pressable>
    ),
    Loading: () => null,
  };
});
jest.mock("@/src/components/BrandLogo", () => {
  const { View } = require("react-native");
  return (props: any) => <View testID={props.testID} />;
});
jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff", brand: "#0284C7", muted: "#999", error: "#DC2626",
    border: "#E5E7EB", onSurface: "#111", onSurfaceSecondary: "#555",
    surfaceSecondary: "#F9FAFB", brandTertiary: "#EFF6FF",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32, "3xl": 48 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { sm: 12, base: 14, lg: 16, xl: 18, "2xl": 24 },
  IMAGES: { loginHero: "https://example.com/hero.jpg" },
  money: (v: number) => `$${v}`,
}));

import Login from "../app/login";

afterEach(() => {
  jest.clearAllMocks();
});

// Helper: mock the /config/public response with the given app_env.
function mockAppEnv(value: string | null | undefined, opts?: { reject?: boolean }) {
  mockApiGet.mockImplementation((path: string) => {
    if (path === "/config/public") {
      if (opts?.reject) return Promise.reject(new Error("boom"));
      return Promise.resolve({ show_demo_logins: true, app_env: value });
    }
    return Promise.resolve(undefined);
  });
}

describe("Login — Demo Accounts Section (runtime app_env gate)", () => {
  it("renders 4 demo login buttons when app_env=preview", async () => {
    mockAppEnv("preview");
    const { getByTestId, findByTestId } = render(<Login />);

    // Wait for the effect's fetch to settle and the section to mount.
    await findByTestId("demo-login-section");
    expect(getByTestId("demo-login-super-admin-btn")).toBeTruthy();
    expect(getByTestId("demo-login-admin-btn")).toBeTruthy();
    expect(getByTestId("demo-login-customer-btn")).toBeTruthy();
    // The demo tech account was renamed from "Pool Tech" →
    // "Landscape Tech" (email swapped from mike@ → landscaper@) in
    // an earlier session; testID follows the label kebab-case.
    expect(getByTestId("demo-login-landscape-tech-btn")).toBeTruthy();
  });

  it("renders 4 demo login buttons when app_env=development", async () => {
    mockAppEnv("development");
    const { findByTestId } = render(<Login />);
    await findByTestId("demo-login-section");
  });

  it("hides demo login buttons when app_env=production", async () => {
    mockAppEnv("production");
    const { queryByTestId } = render(<Login />);
    // Give the effect a tick to flush.
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledWith("/config/public"));
    expect(queryByTestId("demo-login-section")).toBeNull();
  });

  it("hides demo login buttons when app_env is missing (fail-closed)", async () => {
    mockAppEnv(undefined);
    const { queryByTestId } = render(<Login />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledWith("/config/public"));
    expect(queryByTestId("demo-login-section")).toBeNull();
  });

  it("hides demo login buttons when the /config/public fetch fails (fail-closed)", async () => {
    mockAppEnv("preview", { reject: true });
    const { queryByTestId } = render(<Login />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledWith("/config/public"));
    expect(queryByTestId("demo-login-section")).toBeNull();
  });

  it("hides demo login buttons on initial render (before fetch resolves)", () => {
    // Never-resolving promise so the initial null state is visible.
    mockApiGet.mockImplementation(() => new Promise(() => {}));
    const { queryByTestId } = render(<Login />);
    expect(queryByTestId("demo-login-section")).toBeNull();
  });

  it("calls login with correct Super Admin credentials on tap", async () => {
    mockAppEnv("preview");
    const { findByTestId } = render(<Login />);
    const btn = await findByTestId("demo-login-super-admin-btn");
    fireEvent.press(btn);

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith(
        "super@aquaterra.com",
        "password123",
      );
    });
  });

  it("calls login with Customer credentials on tap", async () => {
    mockAppEnv("preview");
    const { findByTestId } = render(<Login />);
    const btn = await findByTestId("demo-login-customer-btn");
    fireEvent.press(btn);

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith(
        "customer@aquaterra.com",
        "password123",
      );
    });
  });
});
