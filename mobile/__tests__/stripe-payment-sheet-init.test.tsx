/**
 * __tests__/stripe-payment-sheet-init.test.tsx
 *
 * Verifies:
 *   - Card add flow calls POST setup-intent without payment_method_types
 *   - ACH add flow calls POST setup-intent with ["us_bank_account"]
 *   - Mock initPaymentSheet receives the correct client_secret
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

/* ── Hoisted mocks ────────────────────────────────────── */
const mockInitPaymentSheet = jest.fn(async () => ({ error: null }));
const mockPresentPaymentSheet = jest.fn(async () => ({ error: null }));

jest.mock("@stripe/stripe-react-native", () => ({
  StripeProvider: ({ children }: any) => children,
  initPaymentSheet: (...args: any[]) => mockInitPaymentSheet(...args),
  presentPaymentSheet: (...args: any[]) => mockPresentPaymentSheet(...args),
}));

const mockApiPost = jest.fn();
const mockApiGet = jest.fn();
const mockApiDelete = jest.fn();

jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: (...a: any[]) => mockApiPost(...a),
    delete: (...a: any[]) => mockApiDelete(...a),
  },
}));

jest.mock("@/src/api/stripe", () => ({
  createSetupIntent: (...a: any[]) => mockApiPost("/payments/stripe/setup-intent", ...a),
  attachPaymentMethod: jest.fn(),
  listPaymentMethods: () => mockApiGet("/payments/stripe/payment-methods/cust-1"),
  removePaymentMethod: jest.fn(),
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({ id: "cust-1" }),
  usePathname: () => "/customer/cust-1/payment-methods",
  useSegments: () => ["customer", "cust-1", "payment-methods"],
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

/* ── Component import ──────────────────────────────────── */
import PaymentMethodsScreen from "@/app/customer/[id]/payment-methods";

describe("Stripe PaymentSheet Init", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockApiGet.mockImplementation(async (url: string) => {
      if (url.includes("payment-methods")) return [];
      if (url.includes("customers/")) return { name: "John Doe" };
      if (url.includes("notifications")) return { count: 0 };
      return {};
    });
    mockApiPost.mockResolvedValue({
      client_secret: "seti_1_secret_test123",
      setup_intent_id: "seti_1",
    });
  });

  it("card add flow calls setup-intent without payment_method_types", async () => {
    const tree = render(<PaymentMethodsScreen />);
    await waitFor(() => expect(tree.getByTestId("pm-add-card-btn")).toBeTruthy());

    await act(async () => {
      fireEvent.press(tree.getByTestId("pm-add-card-btn"));
    });

    await waitFor(() => {
      // createSetupIntent passes (customerId) without payment_method_types for card
      expect(mockApiPost).toHaveBeenCalledWith(
        "/payments/stripe/setup-intent",
        "cust-1",
      );
    });
    console.log("✅ SI-T1: Card flow calls setup-intent without payment_method_types");
  });

  it("ACH add flow calls setup-intent with [us_bank_account]", async () => {
    const tree = render(<PaymentMethodsScreen />);
    await waitFor(() => expect(tree.getByTestId("pm-add-ach-btn")).toBeTruthy());

    await act(async () => {
      fireEvent.press(tree.getByTestId("pm-add-ach-btn"));
    });

    await waitFor(() => {
      // createSetupIntent passes (customerId, ["us_bank_account"]) for ACH
      expect(mockApiPost).toHaveBeenCalledWith(
        "/payments/stripe/setup-intent",
        "cust-1",
        ["us_bank_account"],
      );
    });
    console.log("✅ SI-T2: ACH flow calls setup-intent with [us_bank_account]");
  });

  it("initPaymentSheet receives the correct client_secret", async () => {
    const tree = render(<PaymentMethodsScreen />);
    await waitFor(() => expect(tree.getByTestId("pm-add-card-btn")).toBeTruthy());

    await act(async () => {
      fireEvent.press(tree.getByTestId("pm-add-card-btn"));
    });

    await waitFor(() => {
      expect(mockInitPaymentSheet).toHaveBeenCalledWith(
        expect.objectContaining({
          setupIntentClientSecret: "seti_1_secret_test123",
        }),
      );
    });
    console.log("✅ SI-T3: initPaymentSheet receives correct client_secret");
  });
});
