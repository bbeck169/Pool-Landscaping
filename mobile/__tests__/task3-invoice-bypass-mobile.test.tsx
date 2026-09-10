/**
 * Task 3 — Invoice bypass portal (magic link) · Jest mobile coverage.
 *
 * Tests:
 *   1. Invalid/malformed JWT → renders `public-invoice-magic-invalid-token`.
 *   2. Valid JWT decodes → renders `public-invoice-magic-root` with invoice data.
 *   3. Pay Now button opens system browser via Linking.openURL.
 *   4. Save card checkbox toggles and is included in the pay request.
 *   5. API error → renders error state with retry button.
 *   6. Loading state renders spinner.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

/* ── Mocks ─────────────────────────────────────────────────── */

// Mock expo-router
const mockRouter = { back: jest.fn(), canGoBack: jest.fn(() => true), push: jest.fn() };
jest.mock("expo-router", () => ({
  useLocalSearchParams: jest.fn(),
  useRouter: () => mockRouter,
}));

// Mock safe area
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 44, bottom: 34, left: 0, right: 0 }),
  SafeAreaProvider: ({ children }: any) => children,
}));

// Mock vector icons
jest.mock("@expo/vector-icons", () => {
  const { Text } = require("react-native");
  return { Ionicons: ({ name, ...props }: any) => <Text {...props}>{name}</Text> };
});

// Mock API
const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockGet(...args),
    post: (...args: any[]) => mockPost(...args),
    patch: jest.fn(),
    del: jest.fn(),
  },
}));

// Mock theme
jest.mock("@/src/theme", () => ({
  colors: { brand: "#0EA5E9", onSurface: "#0F172A", error: "#DC2626", muted: "#94A3B8", surface: "#FFFFFF", surfaceSecondary: "#F8FAFC", border: "#E2E8F0", success: "#16A34A" },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { sm: 13, base: 15, lg: 17, xl: 20, "2xl": 24, "3xl": 30 },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, "2xl": 24, "3xl": 32 },
  radius: { sm: 6, md: 10, lg: 14 },
}));

// Mock Linking - use spyOn after import
import { Linking } from "react-native";

import { useLocalSearchParams } from "expo-router";
import MagicInvoiceScreen from "../app/i/[token]";

/* ── Helpers ───────────────────────────────────────────────── */

/** Build a fake HS256 JWT with the given payload. */
function makeToken(payload: Record<string, any>): string {
  const b64 = (obj: any) => {
    const json = JSON.stringify(obj);
    return Buffer.from(json, "utf-8")
      .toString("base64")
      .replace(/=/g, "")
      .replace(/\+/g, "-")
      .replace(/\//g, "_");
  };
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64(payload)}.abc`;
}

const INVOICE_DATA = {
  company: { name: "AquaTerra LLC", address: "123 Pool St", phone: "555-1234" },
  bill_to: { name: "Brian Beckman", address: "456 Oak Ave" },
  property_address: "789 Elm Rd",
  header: { invoice_number: "INV-001", invoice_date: "2026-03-15", outstanding_balance: 250 },
  line_items: [
    { description: "Pool Cleaning", cost_rate: 150, qty_hr: 1, total: 150 },
    { description: "Chemical Treatment", cost_rate: 100, qty_hr: 1, total: 100 },
  ],
  totals: { subtotal: 250, this_invoice: 250, amount_paid: 0, total_due: 250 },
  notes: "Please pay within 30 days.",
  is_due_on_receipt: true,
  payment_status: "unpaid",
};


/* ── Tests ─────────────────────────────────────────────────── */

describe("MagicInvoiceScreen (Task 3)", () => {
  let mockOpenURL: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    mockGet.mockReset();
    mockPost.mockReset();
    mockOpenURL = jest.spyOn(Linking, "openURL").mockResolvedValue(undefined as any);
  });

  afterEach(() => {
    mockOpenURL.mockRestore();
  });

  it("1. shows invalid-token banner for malformed JWT", () => {
    (useLocalSearchParams as jest.Mock).mockReturnValue({ token: "not-a-jwt" });

    const { getByTestId } = render(<MagicInvoiceScreen />);
    expect(getByTestId("public-invoice-magic-invalid-token")).toBeTruthy();
  });

  it("2. decodes valid token → renders invoice root with data", async () => {
    const token = makeToken({ sub: "invoice_pay", invoice_id: "inv-777", tenant_id: "t1" });
    (useLocalSearchParams as jest.Mock).mockReturnValue({ token });
    mockGet.mockResolvedValue(INVOICE_DATA);

    const { getByTestId, getByText } = render(<MagicInvoiceScreen />);

    await waitFor(() => {
      expect(getByTestId("public-invoice-magic-root")).toBeTruthy();
    });
    expect(getByTestId("magic-invoice-number")).toBeTruthy();
    expect(getByText("Invoice #INV-001")).toBeTruthy();
    expect(getByTestId("magic-invoice-total-due")).toBeTruthy();
    expect(mockGet).toHaveBeenCalledWith(
      expect.stringContaining("/invoices/inv-777/full-magic?token="),
    );
  });

  it("3. Pay Now calls POST for checkout URL and opens system browser", async () => {
    const token = makeToken({ sub: "invoice_pay", invoice_id: "inv-42", tenant_id: "t1" });
    (useLocalSearchParams as jest.Mock).mockReturnValue({ token });
    mockGet.mockResolvedValue(INVOICE_DATA);
    mockPost.mockResolvedValue({ url: "https://checkout.stripe.com/session/test" });

    const { getByTestId } = render(<MagicInvoiceScreen />);

    await waitFor(() => {
      expect(getByTestId("invoice-pay-now-btn")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(getByTestId("invoice-pay-now-btn"));
    });

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        expect.stringContaining("/invoices/inv-42/request-payment-link-magic?token="),
        { save_card: false },
      );
    });
    expect(mockOpenURL).toHaveBeenCalledWith("https://checkout.stripe.com/session/test");
  });

  it("4. Save card switch toggles and is included in pay request", async () => {
    const token = makeToken({ sub: "invoice_pay", invoice_id: "inv-55", tenant_id: "t1" });
    (useLocalSearchParams as jest.Mock).mockReturnValue({ token });
    mockGet.mockResolvedValue(INVOICE_DATA);
    mockPost.mockResolvedValue({ url: "https://checkout.stripe.com/session/saved" });

    const { getByTestId } = render(<MagicInvoiceScreen />);

    await waitFor(() => {
      expect(getByTestId("magic-invoice-save-card-switch")).toBeTruthy();
    });

    // Toggle save card ON
    fireEvent(getByTestId("magic-invoice-save-card-switch"), "valueChange", true);

    await act(async () => {
      fireEvent.press(getByTestId("invoice-pay-now-btn"));
    });

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        expect.stringContaining("/request-payment-link-magic"),
        { save_card: true },
      );
    });
  });

  it("5. API error → renders error state with retry", async () => {
    const token = makeToken({ sub: "invoice_pay", invoice_id: "inv-err", tenant_id: "t1" });
    (useLocalSearchParams as jest.Mock).mockReturnValue({ token });
    mockGet.mockRejectedValue(new Error("token_invalid_or_expired"));

    const { getByTestId } = render(<MagicInvoiceScreen />);

    await waitFor(() => {
      expect(getByTestId("magic-invoice-error")).toBeTruthy();
    });
    expect(getByTestId("magic-invoice-retry")).toBeTruthy();
  });

  it("6. loading state renders spinner", () => {
    const token = makeToken({ sub: "invoice_pay", invoice_id: "inv-loading", tenant_id: "t1" });
    (useLocalSearchParams as jest.Mock).mockReturnValue({ token });
    mockGet.mockReturnValue(new Promise(() => {})); // Never resolves

    const { getByTestId } = render(<MagicInvoiceScreen />);
    expect(getByTestId("magic-invoice-loading")).toBeTruthy();
  });
});
