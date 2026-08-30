/**
 * __tests__/stripe-offline-banner.test.tsx
 *
 * Verifies:
 *   - When offline, add/remove buttons are disabled + offline banner present
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

/* ── Hoisted mocks ────────────────────────────────────── */
let mockOnline = false;

jest.mock("@stripe/stripe-react-native", () => ({
  StripeProvider: ({ children }: any) => children,
  initPaymentSheet: jest.fn(),
  presentPaymentSheet: jest.fn(),
}));

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(async (url: string) => {
      if (url.includes("customers/")) return { name: "Test" };
      if (url.includes("notifications")) return { count: 0 };
      return {};
    }),
    post: jest.fn(async () => ({})),
    delete: jest.fn(async () => ({})),
  },
}));

jest.mock("@/src/api/stripe", () => ({
  createSetupIntent: jest.fn(),
  attachPaymentMethod: jest.fn(),
  listPaymentMethods: jest.fn(async () => [
    {
      id: "pm_1",
      provider_payment_method_id: "pm_1",
      type: "card",
      brand: "visa",
      last4: "4242",
      is_default: true,
    },
  ]),
  removePaymentMethod: jest.fn(),
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({ id: "cust-1" }),
  usePathname: () => "/",
  useSegments: () => [],
  useFocusEffect: (cb: any) => {
    const React = require("react");
    React.useEffect(() => { const cleanup = cb(); return typeof cleanup === "function" ? cleanup : undefined; }, []);
  },
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u1" } }),
}));

jest.mock("@/src/offline", () => ({
  useOnline: () => mockOnline,
}));

jest.mock("@/src/config/stripe", () => ({
  useStripeConfig: () => ({ pk: "pk_test_123", mode: "test", loading: false }),
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
  useTenantBrand: () => ({ logoUrl: null, loading: false, error: null }),
}));

jest.mock("@/src/components/ConfirmModal", () => ({
  showConfirm: jest.fn(),
  ConfirmModal: () => null,
  ConfirmModalHost: () => null,
}));

import PaymentMethodsScreen from "@/app/customer/[id]/payment-methods";

describe("Stripe Offline Banner", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockOnline = false;
  });

  it("shows offline banner and disabled buttons when offline", async () => {
    const tree = render(<PaymentMethodsScreen />);
    await waitFor(() => {
      expect(tree.getByTestId("pm-offline-banner")).toBeTruthy();
    });
    // Add buttons should be disabled
    const cardBtn = tree.getByTestId("pm-add-card-btn");
    const achBtn = tree.getByTestId("pm-add-ach-btn");
    expect(cardBtn.props.accessibilityState?.disabled).toBe(true);
    expect(achBtn.props.accessibilityState?.disabled).toBe(true);
    // Remove button should also be disabled
    const removeBtn = tree.getByTestId("pm-remove-pm_1");
    expect(removeBtn.props.accessibilityState?.disabled).toBe(true);
    console.log("✅ OB-T1: Offline banner shows, add/remove buttons disabled");
  });
});
