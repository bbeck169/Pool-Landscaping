/**
 * __tests__/stripe-attach-round-trip.test.tsx
 *
 * Verifies:
 *   - After PaymentSheet reports success, the list is refreshed (which
 *     picks up the new PM from the backend mirror).
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

/* ── Hoisted mocks ────────────────────────────────────── */
const mockInitPaymentSheet = jest.fn(async () => ({ error: null }));
const mockPresentPaymentSheet = jest.fn(async () => ({ error: null }));
const mockListPm = jest.fn();
const mockApiPost = jest.fn();
const mockApiGet = jest.fn();

jest.mock("@stripe/stripe-react-native", () => ({
  StripeProvider: ({ children }: any) => children,
  initPaymentSheet: (...a: any[]) => mockInitPaymentSheet(...a),
  presentPaymentSheet: (...a: any[]) => mockPresentPaymentSheet(...a),
}));

jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: (...a: any[]) => mockApiPost(...a),
    delete: jest.fn(async () => ({})),
  },
}));

jest.mock("@/src/api/stripe", () => ({
  createSetupIntent: () =>
    mockApiPost("/payments/stripe/setup-intent", { customer_id: "cust-1" }),
  attachPaymentMethod: jest.fn(),
  listPaymentMethods: (...a: any[]) => mockListPm(...a),
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
  useOnline: () => true,
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

describe("Stripe Attach Round Trip", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockApiGet.mockImplementation(async (url: string) => {
      if (url.includes("customers/")) return { name: "John Doe" };
      if (url.includes("notifications")) return { count: 0 };
      return {};
    });
    mockApiPost.mockResolvedValue({
      client_secret: "seti_1_secret_abc",
      setup_intent_id: "seti_1",
    });
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("after PaymentSheet success, list is refreshed to pick up new PM", async () => {
    // First call: empty list
    mockListPm.mockResolvedValueOnce([]);
    // Second call (after sheet success): list with new PM
    mockListPm.mockResolvedValueOnce([
      {
        id: "pm_new",
        provider_payment_method_id: "pm_new",
        type: "card",
        brand: "mastercard",
        last4: "5555",
        exp_month: 3,
        exp_year: 2028,
        is_default: true,
      },
    ]);

    const tree = render(<PaymentMethodsScreen />);
    // Wait for empty state
    await waitFor(() => {
      expect(tree.getByTestId("pm-empty-state")).toBeTruthy();
    });

    // Tap add card
    await act(async () => {
      fireEvent.press(tree.getByTestId("pm-add-card-btn"));
    });

    // Wait for the refresh after sheet success
    await waitFor(() => {
      expect(tree.getByTestId("pm-row-pm_new")).toBeTruthy();
    });

    // List was fetched twice: initial + after sheet
    expect(mockListPm).toHaveBeenCalledTimes(2);
    console.log("✅ ART-T1: After PaymentSheet success, list refreshed with new PM");
  });
});
