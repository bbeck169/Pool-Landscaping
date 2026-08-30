/**
 * __tests__/settings-sprocket-visibility.test.tsx
 *
 * Tests for the settings gear icon in the mobile Header (Part 2):
 *   - Sprocket renders for owner/super_admin/admin
 *   - Sprocket hidden for tech + customer
 *   - Tap navigates to /settings
 */
import React from "react";
import { render, fireEvent } from "@testing-library/react-native";

/* ── Mocks ────────────────────────────────────────────── */
const mockRouterPush = jest.fn();
const mockRouterBack = jest.fn();

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockRouterPush, back: mockRouterBack }),
  usePathname: () => "/",
  useSegments: () => [],
  useFocusEffect: (cb: any) => {
    const React = require("react");
    React.useEffect(() => { const cleanup = cb(); return typeof cleanup === "function" ? cleanup : undefined; }, []);
  },
}));

let _mockRole = "admin";
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: _mockRole, id: "u1" } }),
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

jest.mock("@/src/hooks/useBreadcrumbs", () => ({
  useBreadcrumbs: () => [],
}));

jest.mock("@/src/hooks/useTenantBrand", () => ({
  __esModule: true,
  default: () => ({ logoUri: null, loading: false, error: null }),
}));

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(() => Promise.resolve({ count: 0 })),
  },
}));

import { Header } from "@/src/components/widgets";

describe("Settings Sprocket Visibility", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders sprocket for admin role", () => {
    _mockRole = "admin";
    const tree = render(<Header title="Dashboard" />);
    expect(tree.getByTestId("header-settings-sprocket")).toBeTruthy();
    console.log("✅ SP-T1: Sprocket visible for admin");
  });

  it("renders sprocket for super_admin role", () => {
    _mockRole = "super_admin";
    const tree = render(<Header title="Dashboard" />);
    expect(tree.getByTestId("header-settings-sprocket")).toBeTruthy();
    console.log("✅ SP-T2: Sprocket visible for super_admin");
  });

  it("hides sprocket for technician role", () => {
    _mockRole = "technician";
    const tree = render(<Header title="Schedule" />);
    expect(tree.queryByTestId("header-settings-sprocket")).toBeNull();
    console.log("✅ SP-T3: Sprocket hidden for technician");
  });

  it("hides sprocket for customer role", () => {
    _mockRole = "customer";
    const tree = render(<Header title="Home" />);
    expect(tree.queryByTestId("header-settings-sprocket")).toBeNull();
    console.log("✅ SP-T4: Sprocket hidden for customer");
  });

  it("tap navigates to /settings", () => {
    _mockRole = "admin";
    const tree = render(<Header title="Dashboard" />);
    fireEvent.press(tree.getByTestId("header-settings-sprocket"));
    expect(mockRouterPush).toHaveBeenCalledWith("/settings");
    console.log("✅ SP-T5: Tap navigates to /settings");
  });
});
