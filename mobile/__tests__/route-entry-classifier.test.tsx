/**
 * Route-entry classifier gap — tests that 403 renders "Not authorized"
 * and network errors render "You're offline" on detail screens.
 *
 * Tests:
 *   1. Quote detail 403 → "Not authorized"
 *   2. Quote detail network error → "You're offline"
 *   3. Customer detail 403 → "Not authorized"
 *   4. Customer detail network error → "You're offline"
 *   5. Invoice detail 403 → "Not authorized"
 *   6. Invoice detail network error → "You're offline"
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

/* ------------------------------------------------------------------ */
/*  Shared mocks                                                       */
/* ------------------------------------------------------------------ */

jest.mock("@/src/components/ToastProvider", () => ({
  useToast: () => ({ showToast: jest.fn() }),
  ToastProvider: ({ children }: any) => children,
}));

jest.mock("@/src/api", () => {
  class ApiError extends Error {
    status: number;
    detail: string;
    constructor(status: number, message?: string) {
      super(message || "Error");
      this.status = status;
      this.detail = message || "Error";
    }
  }
  class ApiNetworkError extends Error {
    kind = "network";
    constructor(msg?: string) { super(msg || "Network error"); }
  }
  return {
    api: { get: jest.fn(), post: jest.fn(), put: jest.fn(), patch: jest.fn(), delete: jest.fn() },
    ApiError,
    ApiNetworkError,
    TOKEN_KEY: "token",
  };
});

// We want the REAL mapApiError so we can verify end-to-end classification.
// It imports ApiError from @/src/api which is mocked above, so it will
// work with our mock ApiError class.
jest.mock("@/src/theme", () => ({
  colors: {
    brand: "#0066FF", onSurface: "#111", onSurfaceSecondary: "#555",
    muted: "#999", error: "#d00", success: "#22c55e", warning: "#eab308",
    background: "#fff", surface: "#fff", surfaceSecondary: "#f4f4f5",
    border: "#ccc",
  },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32, "3xl": 48 },
  radius: { sm: 4, md: 8, lg: 16, pill: 999 },
  font: { regular: "System", bold: "System", semibold: "System", medium: "System", mono: "monospace" },
  fontSize: { xs: 10, sm: 12, base: 14, md: 14, lg: 16, xl: 20, xxl: 24 },
  money: (n: number) => `$${(n || 0).toFixed(2)}`,
  IMAGES: {},
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin", email: "admin@test.com" }, token: "tok" }),
}));

jest.mock("@/src/services/readCache", () => ({
  writeCache: jest.fn().mockResolvedValue(undefined),
  readCache: jest.fn().mockResolvedValue(null),
}));

jest.mock("expo-router", () => ({
  useLocalSearchParams: () => ({ id: "test123" }),
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useFocusEffect: (cb: any) => { const React = require("react"); React.useEffect(() => { cb(); }, []); },
  Link: "Link",
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

jest.mock("@expo/vector-icons", () => ({ Ionicons: "Ionicons" }));

jest.mock("@/src/components/ui", () => ({
  Loading: (props: any) => {
    const { View, Text } = require("react-native");
    return require("react").createElement(View, { testID: props.testID },
      require("react").createElement(Text, null, "Loading..."));
  },
  StatusChip: () => null,
  PrimaryButton: () => null,
  Sheet: () => null,
}));

jest.mock("@/src/components/widgets", () => ({
  Header: ({ children }: any) => {
    const { View } = require("react-native");
    return require("react").createElement(View, null, children);
  },
  IconButton: () => null,
  JobCard: () => null,
}));

/* Stub out heavy sub-components used by quote/customer/invoice detail */
jest.mock("@/src/config/stripe", () => ({
  useStripeConfig: () => ({ stripeConfigured: false, pk: null }),
}));
jest.mock("@/src/hooks/useBusinessSettings", () => ({
  useBusinessSettings: () => ({ branding: null }),
}));
jest.mock("@/src/utils/formatCustomerName", () => ({
  formatCustomerName: () => "Test Customer",
}));
jest.mock("@/src/utils/exportInvoicePdf", () => ({
  exportInvoicePdf: jest.fn(),
}));
jest.mock("@/src/lib/stripeConfig", () => ({
  StripeUnconfiguredNotice: () => null,
}));
jest.mock("expo-web-browser", () => ({
  openBrowserAsync: jest.fn(),
  dismissBrowser: jest.fn(),
}));
jest.mock("expo-linking", () => ({
  createURL: () => "test://",
}));
jest.mock("@/src/components/quotes/SendToCustomerSheet", () => ({
  __esModule: true, default: () => null,
}));

/* Customer-specific mocks */
jest.mock("@/src/components/customers/CustomerEquipmentLibrary", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/MultiContact", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerMultiContactEditor", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/AutomationsMuteSection", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerTasks", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/ServiceNotes", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/SendCreateSheet", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/SendServiceRecordsLinkModal", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerTagsSection", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/PaymentMethodTiles", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CommunicationTimeline", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/comms/DemoAccountToggle", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/MuteControlSheet", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/CustomerDeleteModal", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/subscriptions/SubscriptionsSection", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customers/PortalAccessPanel", () => ({ __esModule: true, default: () => null }));

/* Invoice-specific mocks */
jest.mock("@/src/api/invoices", () => ({
  getInvoiceFull: jest.fn(),
}));
jest.mock("@/src/api/payments", () => ({
  createPaymentIntent: jest.fn(),
}));
jest.mock("@/src/components/files", () => ({
  InvoiceAttachments: () => null,
}));
jest.mock("@/src/components/invoices/InvoiceViewHistory", () => ({ __esModule: true, default: () => null }));
jest.mock("react-native-webview", () => ({
  WebView: "WebView",
}));

/* ------------------------------------------------------------------ */
/*  Import mocks + components                                          */
/* ------------------------------------------------------------------ */

import { api, ApiError, ApiNetworkError } from "@/src/api";
const mockGet = api.get as jest.Mock;

import { getInvoiceFull } from "@/src/api/invoices";
const mockGetInvoiceFull = getInvoiceFull as jest.Mock;

import QuoteDetail from "@/app/quote/[id]";
import CustomerDetail from "@/app/customer/[id]";
import InvoiceDetail from "@/app/invoice/[id]";

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe("Route-entry classifier — Quote Detail", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGet.mockReset();
  });

  it("403 renders 'Not authorized' (not 'You're offline')", async () => {
    mockGet.mockRejectedValue(new (ApiError as any)(403, "Forbidden"));
    const { getByTestId } = render(<QuoteDetail />);
    await waitFor(() => getByTestId("quote-detail-error"));
    const title = getByTestId("quote-detail-error-title");
    expect(title.props.children).toBe("Not authorized");
  });

  it("network error renders 'You're offline'", async () => {
    mockGet.mockRejectedValue(new (ApiNetworkError as any)("No network"));
    const { getByTestId } = render(<QuoteDetail />);
    await waitFor(() => getByTestId("quote-detail-error"));
    const title = getByTestId("quote-detail-error-title");
    expect(title.props.children).toBe("You're offline");
  });
});

describe("Route-entry classifier — Customer Detail", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGet.mockReset();
  });

  it("403 renders 'Not authorized'", async () => {
    mockGet.mockRejectedValue(new (ApiError as any)(403, "Forbidden"));
    const { getByTestId } = render(<CustomerDetail />);
    await waitFor(() => getByTestId("customer-detail-error"));
    const title = getByTestId("customer-detail-error-title");
    expect(title.props.children).toBe("Not authorized");
  });

  it("network error renders 'You're offline'", async () => {
    mockGet.mockRejectedValue(new (ApiNetworkError as any)("No network"));
    const { getByTestId } = render(<CustomerDetail />);
    await waitFor(() => getByTestId("customer-detail-error"));
    const title = getByTestId("customer-detail-error-title");
    expect(title.props.children).toBe("You're offline");
  });
});

describe("Route-entry classifier — Invoice Detail", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetInvoiceFull.mockReset();
  });

  it("403 renders 'Not authorized'", async () => {
    mockGetInvoiceFull.mockRejectedValue(new (ApiError as any)(403, "Forbidden"));
    const { getByTestId } = render(<InvoiceDetail />);
    await waitFor(() => getByTestId("invoice-detail-error"));
    const title = getByTestId("invoice-detail-error-title");
    expect(title.props.children).toBe("Not authorized");
  });

  it("network error renders 'You're offline'", async () => {
    mockGetInvoiceFull.mockRejectedValue(new (ApiNetworkError as any)("No network"));
    const { getByTestId } = render(<InvoiceDetail />);
    await waitFor(() => getByTestId("invoice-detail-error"));
    const title = getByTestId("invoice-detail-error-title");
    expect(title.props.children).toBe("You're offline");
  });
});
