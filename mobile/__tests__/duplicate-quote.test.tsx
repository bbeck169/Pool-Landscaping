/**
 * duplicate-quote.test.tsx — Duplicate Quote feature tests.
 *
 * Uses the same mock pattern as PriceBookAdmin.test.tsx (which passes).
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";
import { Alert } from "react-native";

// ── Mocks ─────────────────────────────────────────────────────
jest.mock("expo-router", () => ({
  useLocalSearchParams: () => ({ id: "q-123" }),
  useRouter: () => ({ push: mockPush, back: jest.fn(), replace: jest.fn() }),
  useFocusEffect: (cb: any) => {
    const RN = require("react");
    RN.useEffect(() => { cb(); }, []);
  },
  Link: ({ children }: any) => children,
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("expo-web-browser", () => ({ openBrowserAsync: jest.fn() }));
jest.mock("expo-linking", () => ({ openURL: jest.fn() }));
jest.mock("@/src/hooks/useBusinessSettings", () => ({
  useBusinessSettings: () => ({ branding: { brand_primary_hex: "#0B4A6F", company_display_name: "Test Co" }, loading: false }),
}));
jest.mock("@/src/config/stripe", () => ({
  useStripeConfig: () => ({ stripeConfigured: false }),
}));
jest.mock("@/src/utils/formatCustomerName", () => ({
  formatCustomerName: (q: any) => q?.customer_name || "Source Customer",
}));
jest.mock("@/src/utils/exportInvoicePdf", () => ({ exportInvoicePdf: jest.fn() }));
jest.mock("@/src/lib/stripeConfig", () => ({ StripeUnconfiguredNotice: () => null }));
jest.mock("@/src/services/readCache", () => ({
  readCache: jest.fn().mockResolvedValue(null),
  writeCache: jest.fn().mockResolvedValue(undefined),
}));

// Use same pass-through pattern as PriceBookAdmin
const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPush = jest.fn();

jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockGet(...a),
    post: (...a: any[]) => mockPost(...a),
    put: jest.fn().mockResolvedValue({}),
    patch: jest.fn().mockResolvedValue({}),
    del: jest.fn().mockResolvedValue({}),
  },
  api_base: () => "http://test/api",
}));

let mockRole = "admin";
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: mockRole } }),
}));

const alertSpy = jest.spyOn(Alert, "alert").mockImplementation(() => {});

import QuoteDetail from "@/app/quote/[id]";

const QUOTE_DATA = {
  id: "q-123", title: "Test Quote", doc_type: "quote", status: "draft",
  customer_id: "cust-1", customer_name: "Source Customer",
  line_items: [{ description: "Item A", quantity: 1, unit_price: 100, total: 100 }],
  subtotal: 100, tax: 0, tax_rate: 0, total: 100,
  tenant_name: "Test Co", payment_status: "unpaid",
};

const CUSTOMERS = [
  { id: "cust-1", name: "Source Customer" },
  { id: "cust-2", name: "Another Customer" },
];

const PROPS_1 = [{ id: "p1", address: { line1: "123 Main", city: "Austin", state: "TX" }, active: true }];
const PROPS_2 = [
  { id: "p2", address: { line1: "456 Oak", city: "Dallas", state: "TX" }, active: true },
  { id: "p3", address: { line1: "789 Elm", city: "Houston", state: "TX" }, active: true },
];

beforeEach(() => {
  jest.clearAllMocks();
  mockRole = "admin";
  mockGet.mockImplementation((url: string) => {
    if (url === "/quotes/q-123") return Promise.resolve(QUOTE_DATA);
    if (url === "/card") return Promise.resolve({ company: { name: "Test Co" } });
    if (url === "/customers") return Promise.resolve(CUSTOMERS);
    if (url.includes("/customers/cust-1/properties")) return Promise.resolve(PROPS_1);
    if (url.includes("/customers/cust-2/properties")) return Promise.resolve(PROPS_2);
    return Promise.resolve(null);
  });
  mockPost.mockResolvedValue({ quote_id: "new-q", quote_number: "abc123" });
});

describe("Duplicate Quote", () => {
  it("shows duplicate button for admin", async () => {
    const { getByTestId } = render(<QuoteDetail />);
    await waitFor(() => expect(getByTestId("duplicate-quote-btn")).toBeTruthy());
  }, 10000);

  it("hides duplicate button for technician", async () => {
    mockRole = "technician";
    const { queryByTestId } = render(<QuoteDetail />);
    // Wait briefly then check (technician still loads data but has no button)
    await waitFor(() => expect(queryByTestId("quote-detail-loading")).toBeNull(), { timeout: 5000 });
    expect(queryByTestId("duplicate-quote-btn")).toBeNull();
  }, 10000);

  it("opens modal with source customer pre-selected", async () => {
    const { getByTestId, getByText } = render(<QuoteDetail />);
    await waitFor(() => expect(getByTestId("duplicate-quote-btn")).toBeTruthy(), { timeout: 5000 });

    fireEvent.press(getByTestId("duplicate-quote-btn"));

    await waitFor(() => expect(getByTestId("duplicate-quote-sheet")).toBeTruthy(), { timeout: 5000 });
    expect(getByText("Source Customer")).toBeTruthy();

    // Property auto-picked
    await waitFor(() => expect(getByTestId("duplicate-pick-property-p1")).toBeTruthy(), { timeout: 5000 });
  }, 15000);

  it("refreshes properties on customer change", async () => {
    const { getByTestId, queryByTestId } = render(<QuoteDetail />);
    await waitFor(() => expect(getByTestId("duplicate-quote-btn")).toBeTruthy(), { timeout: 5000 });

    fireEvent.press(getByTestId("duplicate-quote-btn"));
    await waitFor(() => expect(getByTestId("duplicate-quote-sheet")).toBeTruthy(), { timeout: 5000 });

    // Open customer picker
    fireEvent.press(getByTestId("duplicate-customer-selector"));
    await waitFor(() => expect(getByTestId("duplicate-customer-picker")).toBeTruthy(), { timeout: 5000 });

    // Select cust-2
    fireEvent.press(getByTestId("duplicate-pick-customer-cust-2"));

    // Should show cust-2 properties
    await waitFor(() => {
      expect(getByTestId("duplicate-pick-property-p2")).toBeTruthy();
      expect(getByTestId("duplicate-pick-property-p3")).toBeTruthy();
      expect(queryByTestId("duplicate-pick-property-p1")).toBeNull();
    }, { timeout: 5000 });
  }, 15000);

  it("on success, fires alert with quote number", async () => {
    const { getByTestId } = render(<QuoteDetail />);
    await waitFor(() => expect(getByTestId("duplicate-quote-btn")).toBeTruthy(), { timeout: 5000 });

    fireEvent.press(getByTestId("duplicate-quote-btn"));
    await waitFor(() => expect(getByTestId("duplicate-quote-sheet")).toBeTruthy(), { timeout: 5000 });
    await waitFor(() => expect(getByTestId("duplicate-pick-property-p1")).toBeTruthy(), { timeout: 5000 });

    fireEvent.press(getByTestId("duplicate-quote-submit"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith("/quotes/q-123/duplicate", { customer_id: "cust-1", property_id: "p1" });
      expect(alertSpy).toHaveBeenCalledWith("Quote duplicated", expect.stringContaining("abc123"), expect.any(Array));
    }, { timeout: 5000 });
  }, 15000);

  it("on error, shows error and keeps modal open", async () => {
    mockPost.mockRejectedValueOnce(new Error("Customer not found"));

    const { getByTestId } = render(<QuoteDetail />);
    await waitFor(() => expect(getByTestId("duplicate-quote-btn")).toBeTruthy(), { timeout: 5000 });

    fireEvent.press(getByTestId("duplicate-quote-btn"));
    await waitFor(() => expect(getByTestId("duplicate-quote-sheet")).toBeTruthy(), { timeout: 5000 });
    await waitFor(() => expect(getByTestId("duplicate-pick-property-p1")).toBeTruthy(), { timeout: 5000 });

    fireEvent.press(getByTestId("duplicate-quote-submit"));

    await waitFor(() => {
      expect(getByTestId("duplicate-quote-error")).toBeTruthy();
      expect(getByTestId("duplicate-quote-sheet")).toBeTruthy();
    }, { timeout: 5000 });
  }, 15000);
});
