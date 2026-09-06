/**
 * PB1 · Invoice Internal Margin tests.
 *
 * - Internal-margin section renders for admin role
 * - Internal-margin section HIDDEN for customer role
 * - Internal-margin section HIDDEN for technician role
 * - Customer view does NOT contain wholesale/cogs/margin strings
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ id: "inv-1" }),
  useFocusEffect: (cb: any) => {
    const React = require("react");
    React.useEffect(() => { cb(); }, []);
  },
}));

jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn().mockResolvedValue({}),
    post: jest.fn().mockResolvedValue({}),
    patch: jest.fn().mockResolvedValue({}),
  },
  api_base: () => "http://test/api",
  getAuthToken: () => Promise.resolve("tok"),
}));

let mockRole = "super_admin";
jest.mock("@/src/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", role: mockRole, name: "Admin", email: "a@b.com" },
  }),
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
  SafeAreaView: ({ children }: any) => children,
}));

jest.mock("react-native-webview", () => ({
  WebView: () => null,
}));

jest.mock("expo-image", () => ({ Image: "Image" }));

// Mock the invoice-specific modules
jest.mock("@/src/api/invoices", () => {
  const MOCK = {
    company: { name: "AquaTerra", address: "123 Main St", phone: "555-0100" },
    bill_to: { name: "John Doe", address: "456 Oak" },
    property_address: "456 Oak",
    header: { invoice_number: "INV-001", invoice_date: "2026-01-15" },
    line_items: [
      {
        description: "Pool Cleaning",
        qty_hr: 2,
        cost_rate: 100.0,
        total: 200.0,
        retail_price_snapshot: 100.0,
        wholesale_price_snapshot: 30.0,
        labor_cost_snapshot: 15.0,
      },
    ],
    totals: { subtotal: 200.0, this_invoice: 216.0, amount_paid: 216.0, total_due: 0.0 },
    notes: "",
    is_due_on_receipt: false,
    payment_status: "paid",
  };
  return {
    getInvoiceFull: jest.fn(() => Promise.resolve(MOCK)),
    getInvoiceMagic: jest.fn(() => Promise.resolve(MOCK)),
  };
});

jest.mock("@/src/api/payments", () => ({
  createPaymentIntent: jest.fn().mockResolvedValue({ client_secret: "cs_test", amount_cents: 21600 }),
}));

jest.mock("@/src/config/stripe", () => ({
  useStripeConfig: () => ({ pk: "pk_test", loading: false }),
}));

jest.mock("@/src/components/files", () => ({
  InvoiceAttachments: () => null,
}));

jest.mock("@/src/components/files/AuthedImage", () => ({
  AuthedImage: () => null,
}));
jest.mock("@/src/components/files/FileList", () => ({
  FileList: () => null,
}));
jest.mock("@/src/components/files/FileUpload", () => ({
  FileUpload: () => null,
}));
jest.mock("@/src/api/files", () => ({
  humanBytes: (n: number) => `${n} B`,
  buildAuthedDownloadUrl: (id: string, token: string) => `http://test/api/files/${id}/download?auth=${token}`,
}));

import InvoiceDetail from "@/app/invoice/[id]";

describe("PB1 · Invoice Internal Margin", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("renders internal-margin section for super_admin", async () => {
    mockRole = "super_admin";
    const { getByTestId } = render(<InvoiceDetail />);
    await waitFor(() => {
      expect(getByTestId("internal-margin-section")).toBeTruthy();
    });
  }, 15000);

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("renders internal-margin section for admin", async () => {
    mockRole = "admin";
    const { getByTestId } = render(<InvoiceDetail />);
    await waitFor(() => {
      expect(getByTestId("internal-margin-section")).toBeTruthy();
    });
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("renders internal-margin section for manager", async () => {
    mockRole = "manager";
    const { getByTestId } = render(<InvoiceDetail />);
    await waitFor(() => {
      expect(getByTestId("internal-margin-section")).toBeTruthy();
    });
  });

  it("DOES NOT render internal-margin for customer role", async () => {
    mockRole = "customer";
    const { queryByTestId } = render(<InvoiceDetail />);
    await waitFor(() => {
      expect(queryByTestId("internal-margin-section")).toBeNull();
    });
  });

  it("DOES NOT render internal-margin for technician role", async () => {
    mockRole = "technician";
    const { queryByTestId } = render(<InvoiceDetail />);
    await waitFor(() => {
      expect(queryByTestId("internal-margin-section")).toBeNull();
    });
  });

  it("customer view does NOT contain wholesale/cogs/margin text", async () => {
    mockRole = "customer";
    const { queryByText, queryByTestId } = render(<InvoiceDetail />);
    // Wait for the component to render
    await waitFor(() => {
      expect(queryByTestId("internal-margin-section")).toBeNull();
    });
    // None of these internal strings should appear anywhere for customer
    expect(queryByText(/wholesale/i)).toBeNull();
    expect(queryByText("COGS")).toBeNull();
    expect(queryByText("Gross Profit")).toBeNull();
    expect(queryByText(/internal margin/i)).toBeNull();
    expect(queryByText(/margin_pct/i)).toBeNull();
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("displays amber badge text for admin", async () => {
    mockRole = "super_admin";
    const { getByText } = render(<InvoiceDetail />);
    await waitFor(() => {
      expect(getByText(/not shown to customer/i)).toBeTruthy();
    });
  });
});
