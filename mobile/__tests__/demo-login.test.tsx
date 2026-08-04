/**
 * Tests for FIX 3: Demo Login Section — preview-only demo accounts
 *
 * process.env.EXPO_PUBLIC_ENV is read at RENDER time in Jest,
 * so we can simply toggle it between tests without resetModules.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

// ── Mocks ────────────────────────────────────────────────────────────
const mockLogin = jest.fn().mockResolvedValue(undefined);
const mockReplace = jest.fn();
const mockPush = jest.fn();

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ login: mockLogin, user: null, token: null }),
}));
jest.mock("@/src/api", () => ({ api: { get: jest.fn(), post: jest.fn() } }));
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

const ORIGINAL_ENV = process.env.EXPO_PUBLIC_ENV;

afterEach(() => {
  jest.clearAllMocks();
  process.env.EXPO_PUBLIC_ENV = ORIGINAL_ENV;
});

describe("Login — Demo Accounts Section", () => {
  it("renders 4 demo login buttons when EXPO_PUBLIC_ENV=preview", () => {
    process.env.EXPO_PUBLIC_ENV = "preview";
    const { getByTestId } = render(<Login />);

    expect(getByTestId("demo-login-section")).toBeTruthy();
    expect(getByTestId("demo-login-super-admin-btn")).toBeTruthy();
    expect(getByTestId("demo-login-admin-btn")).toBeTruthy();
    expect(getByTestId("demo-login-customer-btn")).toBeTruthy();
    // The demo tech account was renamed from "Pool Tech" →
    // "Landscape Tech" (email swapped from mike@ → landscaper@) in
    // an earlier session; testID follows the label kebab-case.
    expect(getByTestId("demo-login-landscape-tech-btn")).toBeTruthy();
  });

  it("hides demo login buttons when EXPO_PUBLIC_ENV=production", () => {
    process.env.EXPO_PUBLIC_ENV = "production";
    const { queryByTestId } = render(<Login />);

    expect(queryByTestId("demo-login-section")).toBeNull();
  });

  it("hides demo login buttons when EXPO_PUBLIC_ENV is unset", () => {
    delete process.env.EXPO_PUBLIC_ENV;
    const { queryByTestId } = render(<Login />);

    expect(queryByTestId("demo-login-section")).toBeNull();
  });

  it("calls login with correct Super Admin credentials on tap", async () => {
    process.env.EXPO_PUBLIC_ENV = "preview";
    const { getByTestId } = render(<Login />);

    fireEvent.press(getByTestId("demo-login-super-admin-btn"));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith(
        "super@aquaterra.com",
        "password123",
      );
    });
  });

  it("calls login with Customer credentials on tap", async () => {
    process.env.EXPO_PUBLIC_ENV = "preview";
    const { getByTestId } = render(<Login />);

    fireEvent.press(getByTestId("demo-login-customer-btn"));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith(
        "customer@aquaterra.com",
        "password123",
      );
    });
  });
});
