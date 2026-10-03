/**
 * QuoteDeclineReopen.test.tsx — Phase 3 Quote lifecycle mobile parity tests.
 *
 * Covers:
 * 1. Utility helpers: canUserDeclineOrReopenQuote, shouldShowDeclineButton,
 *    shouldShowReopenButton, shouldHideConvertWhenDeclined
 * 2. List screen: 4 filter testIDs, Decline on open rows, Reopen on declined rows,
 *    role-gating, converted rows show neither.
 * 3. Detail screen: Decline/Reopen visibility, Convert hidden when declined,
 *    Alert.alert confirm dialog gating.
 */
import {
  canUserDeclineOrReopenQuote,
  shouldShowDeclineButton,
  shouldShowReopenButton,
  shouldHideConvertWhenDeclined,
} from "@/src/utils/quoteLifecycle";

// ═══════════════════════════════════════════════════════════════════
// 1. Utility helpers
// ═══════════════════════════════════════════════════════════════════
describe("canUserDeclineOrReopenQuote", () => {
  it("allows admin/super_admin/owner/manager", () => {
    for (const role of ["admin", "super_admin", "owner", "manager"]) {
      expect(canUserDeclineOrReopenQuote(role)).toBe(true);
    }
  });

  it("is case-insensitive", () => {
    for (const role of ["Admin", "SUPER_ADMIN", "Owner", "MANAGER"]) {
      expect(canUserDeclineOrReopenQuote(role)).toBe(true);
    }
  });

  it("blocks technician/customer/dispatcher/null/undefined", () => {
    for (const role of ["technician", "customer", "dispatcher", null, undefined, ""]) {
      expect(canUserDeclineOrReopenQuote(role)).toBe(false);
    }
  });
});

describe("shouldShowDeclineButton", () => {
  const base = { isInvoice: false, canDecline: true, convertedInvoiceId: null };

  it("visible on draft/sent/accepted statuses", () => {
    for (const s of ["draft", "sent", "accepted"]) {
      expect(shouldShowDeclineButton({ ...base, docStatus: s })).toBe(true);
    }
  });

  it("hidden when already declined", () => {
    expect(shouldShowDeclineButton({ ...base, docStatus: "declined" })).toBe(false);
  });

  it("hidden on invoices", () => {
    expect(shouldShowDeclineButton({ ...base, isInvoice: true, docStatus: "draft" })).toBe(false);
  });

  it("hidden when converted", () => {
    expect(shouldShowDeclineButton({ ...base, docStatus: "sent", convertedInvoiceId: "inv-1" })).toBe(false);
  });

  it("hidden when canDecline is false (role gate)", () => {
    expect(shouldShowDeclineButton({ ...base, canDecline: false, docStatus: "draft" })).toBe(false);
  });
});

describe("shouldShowReopenButton", () => {
  const base = { isInvoice: false, canReopen: true };

  it("visible when status is declined", () => {
    expect(shouldShowReopenButton({ ...base, docStatus: "declined" })).toBe(true);
  });

  it("hidden when status is NOT declined", () => {
    for (const s of ["draft", "sent", "accepted", "expired"]) {
      expect(shouldShowReopenButton({ ...base, docStatus: s })).toBe(false);
    }
  });

  it("hidden on invoices", () => {
    expect(shouldShowReopenButton({ ...base, isInvoice: true, docStatus: "declined" })).toBe(false);
  });

  it("hidden when canReopen is false (role gate)", () => {
    expect(shouldShowReopenButton({ ...base, canReopen: false, docStatus: "declined" })).toBe(false);
  });
});

describe("shouldHideConvertWhenDeclined", () => {
  it("returns true when status is declined", () => {
    expect(shouldHideConvertWhenDeclined("declined")).toBe(true);
    expect(shouldHideConvertWhenDeclined("Declined")).toBe(true);
    expect(shouldHideConvertWhenDeclined("DECLINED")).toBe(true);
  });

  it("returns false for non-declined statuses", () => {
    for (const s of ["draft", "sent", "accepted", "expired", ""]) {
      expect(shouldHideConvertWhenDeclined(s)).toBe(false);
    }
  });
});

// ═══════════════════════════════════════════════════════════════════
// 2. Quotes List filter + row buttons (unit-level rendering tests)
// ═══════════════════════════════════════════════════════════════════
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";
import { Alert } from "react-native";

// ── Mocks ─────────────────────────────────────────────────────────
const mockPush = jest.fn();
const mockBack = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn(), back: mockBack }),
  useFocusEffect: (cb: any) => { cb(); },
  useLocalSearchParams: () => ({ id: "q-test-1" }),
}));

let mockUser = { role: "admin" };
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockUser }),
}));

const mockApiGet = jest.fn();
const mockApiPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockApiGet(...args),
    post: (...args: any[]) => mockApiPost(...args),
  },
  ApiError: class extends Error {
    status: number;
    detail: any;
    constructor(msg: string, status: number, detail: any) {
      super(msg);
      this.status = status;
      this.detail = detail;
    }
  },
}));

const mockShowToast = jest.fn();
jest.mock("@/src/components/ToastProvider", () => ({
  useToast: () => ({ showToast: mockShowToast }),
}));

jest.mock("@/src/services/readCache", () => ({
  writeCache: jest.fn().mockResolvedValue(undefined),
  readCache: jest.fn().mockResolvedValue(null),
}));

jest.mock("@/src/theme", () => ({
  colors: {
    brand: "#1B1F5C", surface: "#fff", border: "#ddd",
    success: "#16A34A", warning: "#F59E0B", error: "#EF4444",
    onSurface: "#111", onSurfaceSecondary: "#666", muted: "#999",
    surfaceSecondary: "#f5f5f5", brandTertiary: "#E8E8FF",
    surfaceTertiary: "#eee", divider: "#eee",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "3xl": 48 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 18, xl: 22 },
  money: (v: number) => `$${(v || 0).toFixed(2)}`,
}));

jest.mock("@/src/components/ui", () => {
  const { View, Text, ActivityIndicator } = require("react-native");
  return {
    Loading: ({ testID }: any) => <View testID={testID}><ActivityIndicator /></View>,
    EmptyState: ({ testID, title }: any) => <View testID={testID}><Text>{title}</Text></View>,
    StatusChip: ({ status, testID }: any) => <View testID={testID}><Text>{status}</Text></View>,
    PrimaryButton: ({ testID, children, onPress }: any) => (
      <View testID={testID}>{children}</View>
    ),
    Sheet: ({ visible, children, testID }: any) =>
      visible ? <View testID={testID}>{children}</View> : null,
  };
});

jest.mock("@/src/components/widgets", () => {
  const { View, Text, Pressable, ScrollView } = require("react-native");
  return {
    Header: ({ title }: any) => <View testID="header"><Text>{title}</Text></View>,
    FilterRow: ({ options, value, onChange, testID }: any) => (
      <View testID={testID}>
        {options.map((o: any) => (
          <Pressable
            key={o.key}
            testID={`${testID}-${o.key}`}
            onPress={() => onChange(o.key)}
          >
            <Text>{o.label}</Text>
          </Pressable>
        ))}
      </View>
    ),
    IconButton: ({ testID, onPress }: any) => (
      <Pressable testID={testID} onPress={onPress} />
    ),
    NotificationBell: () => <View />,
  };
});

jest.mock("@/src/utils/formatCustomerName", () => ({
  formatCustomerName: (q: any) => q.customer_name || "Customer",
}));

// ── List screen tests ─────────────────────────────────────────────
describe("Quotes list screen — Phase 3 filter + row actions", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUser = { role: "admin" };
    mockApiGet.mockResolvedValue([
      { id: "q1", doc_type: "quote", title: "Open quote", status: "draft", total: 500, customer_name: "Alice" },
      { id: "q2", doc_type: "quote", title: "Declined quote", status: "declined", total: 300, customer_name: "Bob" },
      { id: "q3", doc_type: "quote", title: "Converted quote", status: "sent", total: 700, customer_name: "Charlie", converted_invoice_id: "inv-99" },
    ]);
  });

  it("renders 4 lifecycle filter options with correct testIDs (admin)", async () => {
    const Quotes = require("@/app/(app)/quotes").default;
    const { getByTestId } = render(<Quotes />);

    await waitFor(() => {
      expect(getByTestId("quotes-list-filter")).toBeTruthy();
      expect(getByTestId("quotes-list-filter-open")).toBeTruthy();
      expect(getByTestId("quotes-list-filter-converted")).toBeTruthy();
      expect(getByTestId("quotes-list-filter-declined")).toBeTruthy();
      expect(getByTestId("quotes-list-filter-all")).toBeTruthy();
    });
  });

  it("default mount fetches with ?view=open", async () => {
    const Quotes = require("@/app/(app)/quotes").default;
    render(<Quotes />);

    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith("/quotes?view=open");
    });
  });

  it("tapping Converted re-fetches with ?view=converted", async () => {
    const Quotes = require("@/app/(app)/quotes").default;
    const { getByTestId } = render(<Quotes />);

    await waitFor(() => getByTestId("quotes-list-filter-converted"));
    fireEvent.press(getByTestId("quotes-list-filter-converted"));

    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith("/quotes?view=converted");
    });
  });

  it("shows Decline button on open-view rows when role allows", async () => {
    const Quotes = require("@/app/(app)/quotes").default;
    const { getByTestId, queryByTestId } = render(<Quotes />);

    await waitFor(() => {
      // q1 is draft → Decline visible
      expect(getByTestId("quote-row-decline-q1")).toBeTruthy();
      // q2 is declined → Decline NOT visible
      expect(queryByTestId("quote-row-decline-q2")).toBeNull();
      // q3 is converted → Decline NOT visible
      expect(queryByTestId("quote-row-decline-q3")).toBeNull();
    });
  });

  it("shows Reopen button on declined rows when role allows", async () => {
    const Quotes = require("@/app/(app)/quotes").default;
    const { getByTestId, queryByTestId } = render(<Quotes />);

    await waitFor(() => {
      // q2 is declined → Reopen visible
      expect(getByTestId("quote-row-reopen-q2")).toBeTruthy();
      // q1 is draft → Reopen NOT visible
      expect(queryByTestId("quote-row-reopen-q1")).toBeNull();
      // q3 is converted → Reopen NOT visible
      expect(queryByTestId("quote-row-reopen-q3")).toBeNull();
    });
  });

  it("hides Decline/Reopen for technician role", async () => {
    mockUser = { role: "technician" };
    const Quotes = require("@/app/(app)/quotes").default;
    const { queryByTestId } = render(<Quotes />);

    await waitFor(() => {
      expect(queryByTestId("quote-row-decline-q1")).toBeNull();
      expect(queryByTestId("quote-row-reopen-q2")).toBeNull();
    });
  });

  it("Decline button triggers Alert.alert", async () => {
    const alertSpy = jest.spyOn(Alert, "alert");
    const Quotes = require("@/app/(app)/quotes").default;
    const { getByTestId } = render(<Quotes />);

    await waitFor(() => getByTestId("quote-row-decline-q1"));
    fireEvent.press(getByTestId("quote-row-decline-q1"));

    expect(alertSpy).toHaveBeenCalledWith(
      "Decline Quote",
      "Decline this quote? You can reopen it later.",
      expect.arrayContaining([
        expect.objectContaining({ text: "Cancel", style: "cancel" }),
        expect.objectContaining({ text: "Decline", style: "destructive" }),
      ]),
    );
    alertSpy.mockRestore();
  });

  it("Reopen button triggers Alert.alert", async () => {
    const alertSpy = jest.spyOn(Alert, "alert");
    const Quotes = require("@/app/(app)/quotes").default;
    const { getByTestId } = render(<Quotes />);

    await waitFor(() => getByTestId("quote-row-reopen-q2"));
    fireEvent.press(getByTestId("quote-row-reopen-q2"));

    expect(alertSpy).toHaveBeenCalledWith(
      "Reopen Quote",
      "Reopen this quote?",
      expect.arrayContaining([
        expect.objectContaining({ text: "Cancel", style: "cancel" }),
        expect.objectContaining({ text: "Reopen" }),
      ]),
    );
    alertSpy.mockRestore();
  });
});

// ═══════════════════════════════════════════════════════════════════
// 3. Detail screen — Convert hidden when declined (regression)
// ═══════════════════════════════════════════════════════════════════
describe("Detail screen lifecycle visibility (unit logic)", () => {
  it("Convert-to-Invoice is hidden when status=declined (Phase 3 regression)", () => {
    // This test validates the shouldHideConvertWhenDeclined guard used
    // in the detail screen JSX: {!isInvoice && q.id && !shouldHideConvertWhenDeclined(q.status)}
    expect(shouldHideConvertWhenDeclined("declined")).toBe(true);
    // So the ConvertToInvoiceButton would NOT render
  });

  it("Decline visible on draft quote for admin", () => {
    expect(
      shouldShowDeclineButton({
        isInvoice: false,
        docStatus: "draft",
        convertedInvoiceId: null,
        canDecline: canUserDeclineOrReopenQuote("admin"),
      }),
    ).toBe(true);
  });

  it("Decline hidden on converted quote", () => {
    expect(
      shouldShowDeclineButton({
        isInvoice: false,
        docStatus: "sent",
        convertedInvoiceId: "inv-123",
        canDecline: canUserDeclineOrReopenQuote("admin"),
      }),
    ).toBe(false);
  });

  it("Decline hidden when status=declined", () => {
    expect(
      shouldShowDeclineButton({
        isInvoice: false,
        docStatus: "declined",
        convertedInvoiceId: null,
        canDecline: canUserDeclineOrReopenQuote("admin"),
      }),
    ).toBe(false);
  });

  it("Reopen visible only when status=declined for admin", () => {
    expect(
      shouldShowReopenButton({
        isInvoice: false,
        docStatus: "declined",
        canReopen: canUserDeclineOrReopenQuote("admin"),
      }),
    ).toBe(true);
  });

  it("Reopen hidden for draft status", () => {
    expect(
      shouldShowReopenButton({
        isInvoice: false,
        docStatus: "draft",
        canReopen: canUserDeclineOrReopenQuote("admin"),
      }),
    ).toBe(false);
  });
});
