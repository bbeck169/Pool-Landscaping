/**
 * BrandLogo component tests.
 *
 * 1. Renders bundled default when useTenantBrand returns null.
 * 2. Renders tenant URL when useTenantBrand returns a URL.
 * 3. onError falls back to bundled default.
 * 4. Tapping logo navigates to home route.
 */

const mockPush = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
}));

let mockLogoUrl: string | null = null;
jest.mock("@/src/hooks/useTenantBrand", () => ({
  useTenantBrand: () => ({
    logoUrl: mockLogoUrl,
    loading: false,
    refresh: jest.fn(),
  }),
}));

jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn(async () => null),
  setItem: jest.fn(async () => {}),
}));

import React from "react";
import { render, fireEvent } from "@testing-library/react-native";
import BrandLogo from "@/src/components/BrandLogo";

describe("BrandLogo component", () => {
  beforeEach(() => {
    mockLogoUrl = null;
    mockPush.mockClear();
  });

  test("1 · renders bundled default when logoUrl is null", () => {
    mockLogoUrl = null;
    const { getByTestId } = render(<BrandLogo />);
    const img = getByTestId("brand-logo-img");
    expect(img).toBeTruthy();
    // Source should be the require() number (bundled asset), not a URI object.
    expect(img.props.source).not.toHaveProperty("uri");
    console.log("✅ BL-T1: Renders bundled default when logoUrl is null");
  });

  test("2 · renders tenant URL when logoUrl is set", () => {
    mockLogoUrl = "https://example.com/tenant-logo.png";
    const { getByTestId } = render(<BrandLogo />);
    const img = getByTestId("brand-logo-img");
    expect(img.props.source).toEqual({ uri: "https://example.com/tenant-logo.png" });
    console.log("✅ BL-T2: Renders tenant URL when logoUrl is set");
  });

  test("3 · onError falls back to bundled default", () => {
    mockLogoUrl = "https://example.com/broken.png";
    const { getByTestId } = render(<BrandLogo />);
    const img = getByTestId("brand-logo-img");
    // Initially it should be the tenant URL
    expect(img.props.source).toEqual({ uri: "https://example.com/broken.png" });
    // Simulate error
    fireEvent(img, "error");
    // After re-render, should fall back to bundled
    const img2 = getByTestId("brand-logo-img");
    expect(img2.props.source).not.toHaveProperty("uri");
    console.log("✅ BL-T3: onError falls back to bundled default");
  });

  test("4 · tapping logo navigates to home route", () => {
    mockLogoUrl = null;
    const { getByTestId } = render(<BrandLogo />);
    const pressable = getByTestId("brand-logo-pressable");
    fireEvent.press(pressable);
    expect(mockPush).toHaveBeenCalledWith("/(app)");
    console.log("✅ BL-T4: Tapping logo navigates to /(app)");
  });

  test("4b · onPress=null renders non-interactive (no Pressable)", () => {
    mockLogoUrl = null;
    const { getByTestId, queryByTestId } = render(<BrandLogo onPress={null} />);
    expect(getByTestId("brand-logo-img")).toBeTruthy();
    expect(queryByTestId("brand-logo-pressable")).toBeNull();
    console.log("✅ BL-T4b: onPress=null renders non-interactive");
  });
});
