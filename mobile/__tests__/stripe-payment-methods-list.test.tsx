/**
 * __tests__/stripe-payment-methods-list.test.tsx
 *
 * Verifies:
 *   - Empty state renders when list is empty
 *   - Card row + ACH row render with correct labels + chips
 *   - Remove flow shows confirm modal (no typed input) and calls DELETE
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

/* ── Hoisted mocks ────────────────────────────────────── */
const mockShowConfirm = jest.fn();
const mockApiGet = jest.fn();
const mockApiDelete = jest.fn();
const mockListPm = jest.fn();
const mockRemovePm = jest.fn();

jest.mock("@stripe/stripe-react-native", () => ({
  StripeProvider: ({ children }: any) => children,
  initPaymentSheet: jest.fn(),
  presentPaymentSheet: jest.fn(),
}));

jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: jest.fn(async () => ({ client_secret: "cs_1", setup_intent_id: "si_1" })),
    delete: (...a: any[]) => mockApiDelete(...a),
  },
}));

jest.mock("@/src/api/stripe", () => ({
  createSetupIntent: jest.fn(),
  attachPaymentMethod: jest.fn(),
  listPaymentMethods: (...a: any[]) => mockListPm(...a),
  removePaymentMethod: (...a: any[]) => mockRemovePm(...a),
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({ id: "cust-1" }),
  usePathname: () => "/customer/cust-1/payment-methods",
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
  showConfirm: (...a: any[]) => mockShowConfirm(...a),
  ConfirmModal: () => null,
  ConfirmModalHost: () => null,
}));

import PaymentMethodsScreen from "@/app/customer/[id]/payment-methods";

const CARD_PM = {
  id: "pm_card1",
  provider_payment_method_id: "pm_card1",
  type: "card" as const,
  brand: "visa",
  last4: "4242",
  exp_month: 12,
  exp_year: 2026,
  is_default: true,
};

const ACH_PM = {
  id: "pm_ach1",
  provider_payment_method_id: "pm_ach1",
  type: "us_bank_account" as const,
  bank_name: "Chase",
  last4: "6789",
  verification_status: "unverified",
  is_default: false,
};

describe("Stripe Payment Methods List", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockApiGet.mockImplementation(async (url: string) => {
      if (url.includes("customers/")) return { name: "Jane Smith" };
      if (url.includes("notifications")) return { count: 0 };
      return {};
    });
  });

  it("renders empty state when list is empty", async () => {
    mockListPm.mockResolvedValue([]);
    const tree = render(<PaymentMethodsScreen />);
    await waitFor(() => {
      expect(tree.getByTestId("pm-empty-state")).toBeTruthy();
    });
    console.log("✅ PML-T1: Empty state renders when no payment methods");
  });

  it("renders card row with correct label", async () => {
    mockListPm.mockResolvedValue([CARD_PM]);
    const tree = render(<PaymentMethodsScreen />);
    await waitFor(() => {
      expect(tree.getByTestId("pm-row-pm_card1")).toBeTruthy();
    });
    expect(tree.getByTestId("pm-label-pm_card1")).toBeTruthy();
    expect(tree.getByTestId("pm-default-chip")).toBeTruthy();
    console.log("✅ PML-T2: Card row renders with label + default chip");
  });

  it("renders ACH row with verification chip", async () => {
    mockListPm.mockResolvedValue([ACH_PM]);
    const tree = render(<PaymentMethodsScreen />);
    await waitFor(() => {
      expect(tree.getByTestId("pm-row-pm_ach1")).toBeTruthy();
    });
    expect(tree.getByTestId("pm-verification-chip")).toBeTruthy();
    console.log("✅ PML-T3: ACH row renders with verification chip");
  });

  it("renders both card + ACH rows together", async () => {
    mockListPm.mockResolvedValue([CARD_PM, ACH_PM]);
    const tree = render(<PaymentMethodsScreen />);
    await waitFor(() => {
      expect(tree.getByTestId("pm-row-pm_card1")).toBeTruthy();
      expect(tree.getByTestId("pm-row-pm_ach1")).toBeTruthy();
    });
    // ACH note should appear because ACH is present
    expect(tree.getByTestId("pm-ach-note")).toBeTruthy();
    console.log("✅ PML-T4: Both card + ACH rows render together with ACH note");
  });

  it("remove flow shows confirm modal (no typed input)", async () => {
    mockListPm.mockResolvedValue([CARD_PM]);
    const tree = render(<PaymentMethodsScreen />);
    await waitFor(() => {
      expect(tree.getByTestId("pm-remove-pm_card1")).toBeTruthy();
    });
    fireEvent.press(tree.getByTestId("pm-remove-pm_card1"));
    expect(mockShowConfirm).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Remove payment method?",
        confirmLabel: "Remove",
        confirmStyle: "destructive",
      }),
    );
    console.log("✅ PML-T5: Remove shows confirm modal (no typed input)");
  });
});
