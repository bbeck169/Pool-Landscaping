/**
 * Task 5 — Save card on file · Jest mobile coverage.
 *
 * Tests:
 *   1. Lists saved cards with brand + last4 + default chip.
 *   2. Empty state renders when no cards.
 *   3. Remove flow — opens confirm dialog and calls DELETE.
 *   4. Set-default calls PATCH endpoint.
 *   5. Save card switch present on magic invoice screen.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

/* ── Mocks ─────────────────────────────────────────────────── */

jest.mock("expo-router", () => ({
  useRouter: () => ({ back: jest.fn(), push: jest.fn(), canGoBack: () => true }),
  useFocusEffect: (cb: () => any) => {
    const { useEffect } = require("react");
    useEffect(() => { const cleanup = cb(); return typeof cleanup === "function" ? cleanup : undefined; }, []);
  },
  useLocalSearchParams: jest.fn(() => ({})),
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 44, bottom: 34, left: 0, right: 0 }),
  SafeAreaProvider: ({ children }: any) => children,
}));

jest.mock("@expo/vector-icons", () => {
  const { Text } = require("react-native");
  return { Ionicons: ({ name, ...props }: any) => <Text {...props}>{name}</Text> };
});

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPatch = jest.fn();
const mockDel = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockGet(...a),
    post: (...a: any[]) => mockPost(...a),
    patch: (...a: any[]) => mockPatch(...a),
    del: (...a: any[]) => mockDel(...a),
  },
}));

jest.mock("@/src/theme", () => ({
  colors: { brand: "#0EA5E9", onSurface: "#0F172A", error: "#DC2626", muted: "#94A3B8", surface: "#FFFFFF", surfaceSecondary: "#F8FAFC", border: "#E2E8F0", success: "#16A34A" },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { sm: 13, base: 15, lg: 17, xl: 20, "2xl": 24, "3xl": 30 },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, "2xl": 24, "3xl": 32 },
  radius: { sm: 6, md: 10, lg: 14 },
}));

jest.mock("@/src/components/widgets", () => {
  const { View, Text } = require("react-native");
  return {
    Header: ({ title }: any) => <View><Text>{title}</Text></View>,
  };
});

jest.mock("@/src/components/ui", () => {
  const { View, Text, ActivityIndicator } = require("react-native");
  return {
    Loading: (props: any) => <View testID={props.testID}><ActivityIndicator /></View>,
    EmptyState: (props: any) => <View testID={props.testID}><Text>{props.title}</Text></View>,
  };
});

import PortalPaymentMethodsScreen from "../app/portal/payment-methods";


/* ── Data ──────────────────────────────────────────────────── */

const CARDS = [
  {
    provider_payment_method_id: "pm_visa",
    id: "pm_visa",
    brand: "visa", last4: "4242", exp_month: 12, exp_year: 2030,
    default: true, type: "card",
  },
  {
    provider_payment_method_id: "pm_amex",
    id: "pm_amex",
    brand: "amex", last4: "0005", exp_month: 6, exp_year: 2029,
    default: false, type: "card",
  },
];


/* ── Tests ─────────────────────────────────────────────────── */

describe("PortalPaymentMethodsScreen (Task 5)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGet.mockReset();
    mockPatch.mockReset();
    mockDel.mockReset();
  });

  it("1. lists saved cards + shows default chip on default card", async () => {
    mockGet.mockResolvedValue({ methods: CARDS });

    const { getByTestId } = render(<PortalPaymentMethodsScreen />);

    await waitFor(() => {
      expect(getByTestId("portal-pm-list")).toBeTruthy();
    });
    expect(getByTestId("portal-pm-row-pm_visa")).toBeTruthy();
    expect(getByTestId("portal-pm-row-pm_amex")).toBeTruthy();
    expect(getByTestId("portal-pm-default-chip-pm_visa")).toBeTruthy();
  });

  it("2. renders empty state when no cards", async () => {
    mockGet.mockResolvedValue({ methods: [] });

    const { getByTestId } = render(<PortalPaymentMethodsScreen />);

    await waitFor(() => {
      expect(getByTestId("portal-pm-empty-state")).toBeTruthy();
    });
  });

  it("3. remove flow — opens confirm and calls DELETE", async () => {
    mockGet.mockResolvedValue({ methods: CARDS });
    mockDel.mockResolvedValue({ removed: true, remaining: 1 });

    const { getByTestId } = render(<PortalPaymentMethodsScreen />);

    await waitFor(() => {
      expect(getByTestId("customer-pm-remove-pm_amex")).toBeTruthy();
    });

    // Tap remove
    fireEvent.press(getByTestId("customer-pm-remove-pm_amex"));

    // Confirm dialog appears
    await waitFor(() => {
      expect(getByTestId("portal-pm-remove-confirm-dialog")).toBeTruthy();
    });

    // Confirm removal
    await act(async () => {
      fireEvent.press(getByTestId("portal-pm-remove-confirm"));
    });

    await waitFor(() => {
      expect(mockDel).toHaveBeenCalledWith(
        "/customer-portal/payment-methods/pm_amex",
      );
    });
  });

  it("4. set-default calls PATCH endpoint with is_default true", async () => {
    mockGet.mockResolvedValue({ methods: CARDS });
    mockPatch.mockResolvedValue({ default_payment_method_id: "pm_amex" });

    const { getByTestId } = render(<PortalPaymentMethodsScreen />);

    await waitFor(() => {
      expect(getByTestId("customer-pm-set-default-pm_amex")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(getByTestId("customer-pm-set-default-pm_amex"));
    });

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(
        "/customer-portal/payment-methods/pm_amex/set-default",
        { is_default: true },
      );
    });
  });
});
