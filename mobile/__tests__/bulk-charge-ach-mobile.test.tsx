/**
 * Phase K38 · Feb-2026 — Bulk Charge ACH on File (mobile parity).
 *
 * Covers:
 *  1. Confirmation Alert copy is the verbatim K38 3–5 business day
 *     warning (test-fixture anchor — must NOT be paraphrased).
 *  2. Tapping "Submit ACH" posts to /invoices/bulk-charge-ach-on-file
 *     with dry_run=false and an idempotency key.
 *  3. Failure surface: post rejection triggers an "ACH bulk charge
 *     failed" Alert.
 */
import React from "react";
import { Alert } from "react-native";
import { render, waitFor, act } from "@testing-library/react-native";

jest.setTimeout(15000);

// ── mocks ────────────────────────────────────────────────────────────
const mockApiGet = jest.fn();
const mockApiPost = jest.fn();
const mockAlert = jest.spyOn(Alert, "alert");

jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: (...a: any[]) => mockApiPost(...a),
  },
}));

jest.mock("@/src/services/readCache", () => ({
  writeCache: jest.fn().mockResolvedValue(undefined),
  readCache: jest.fn().mockResolvedValue(null),
}));

jest.mock("expo-router", () => {
  const ReactLib = require("react");
  return {
    useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
    useFocusEffect: (cb: any) => {
      ReactLib.useEffect(() => { cb(); }, []);
    },
  };
});

jest.mock("@expo/vector-icons", () => {
  const { Text } = require("react-native");
  return {
    Ionicons: ({ name }: any) => <Text testID={`icon-${name}`}>{name}</Text>,
  };
});

jest.mock("@/src/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f5f5f5",
    border: "#ddd", brand: "#0af", brandTertiary: "#e0f7ff",
    onSurface: "#333", onSurfaceSecondary: "#666",
    muted: "#888", success: "#0f0", divider: "#eee",
    warning: "#f90", error: "#f00",
  },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 20, "2xl": 24 },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, "3xl": 32 },
  radius: { sm: 4, md: 8, lg: 12, xl: 16, pill: 999 },
  money: (n: any) => `$${(n || 0).toFixed(2)}`,
  statusMeta: {},
}));

jest.mock("@/src/components/ui", () => {
  const { View, Text, Pressable } = require("react-native");
  return {
    Loading: (p: any) => <View testID={p.testID || "loading"} />,
    EmptyState: (p: any) => <View testID={p.testID || "empty"} />,
    StatusChip: () => <View />,
    Sheet: ({ children }: any) => <View>{children}</View>,
    PrimaryButton: ({ title, onPress }: any) => (
      <Pressable onPress={onPress}><Text>{title}</Text></Pressable>
    ),
  };
});

jest.mock("@/src/components/widgets", () => {
  const { View } = require("react-native");
  return {
    Header: () => <View />,
    FilterRow: () => <View />,
  };
});

// ── BulkSelect scaffold — expose a controllable selection via the
// action bar so the test can trigger the K38 ACH handler directly.
const mockBulkState: { selected: Set<string>; count: number } = {
  selected: new Set<string>(["inv-1", "inv-2"]),
  count: 2,
};
let mockBulkActions: any[] = [];
jest.mock("@/src/components/bulk-select/BulkSelectToolkit", () => {
  const { View } = require("react-native");
  return {
    useBulkSelect: () => ({
      selected: mockBulkState.selected,
      count: mockBulkState.count,
      toggleOne: jest.fn(),
      clear: () => { mockBulkState.selected.clear(); mockBulkState.count = 0; },
    }),
    BulkCheckbox: () => <View />,
    BulkActionBar: ({ actions }: any) => {
      mockBulkActions = actions || [];
      return <View testID="bulk-action-bar-mock" />;
    },
  };
});

jest.mock("@/src/utils/formatCustomerName", () => ({
  formatCustomerName: () => "Test Customer",
}));

const Invoices = require("../app/invoices").default;

beforeEach(() => {
  mockApiGet.mockReset();
  mockApiPost.mockReset();
  mockAlert.mockReset();
  mockBulkState.selected = new Set<string>(["inv-1", "inv-2"]);
  mockBulkState.count = 2;
  mockBulkActions = [];
  // Overview payload — happy-path with two invoices.
  mockApiGet.mockResolvedValue({
    summary: null,
    invoices: [
      { id: "inv-1", title: "Pool cleaning", total: 100, balance: 100,
        amount_paid: 0, has_payment_method: true, pm_label: "Chase ••4242",
        customer_id: "c1", customer_name: "T C", pending: true },
      { id: "inv-2", title: "Chem drop", total: 50, balance: 50,
        amount_paid: 0, has_payment_method: true, pm_label: "Chase ••4242",
        customer_id: "c2", customer_name: "T D", pending: true },
    ],
  });
});

const VERBATIM_ACH_WARNING =
  "ACH payments take 3\u20135 business days to settle. " +
  "Charges may still fail after submission (NSF, closed account, or incorrect routing). " +
  "Failed charges will revert the invoice to Unpaid.";

describe("Mobile · Bulk Charge ACH on File (K38)", () => {
  it("Alert copy is the verbatim K38 3-5 business day warning", async () => {
    render(<Invoices />);
    await waitFor(() => expect(mockBulkActions.length).toBeGreaterThanOrEqual(1));
    const achAction = mockBulkActions.find((a) => a.key === "bulk-charge-ach-invoices");
    expect(achAction).toBeTruthy();
    expect(achAction.label).toMatch(/ACH/);
    act(() => { achAction.onPress(); });
    // The confirmation Alert is the second arg to Alert.alert.
    expect(mockAlert).toHaveBeenCalled();
    const call = mockAlert.mock.calls[mockAlert.mock.calls.length - 1];
    const title = call[0];
    const message = call[1];
    expect(title).toMatch(/Charge ACH for 2 invoices\?/);
    expect(message).toBe(VERBATIM_ACH_WARNING);
  });

  it("Submit ACH posts to /invoices/bulk-charge-ach-on-file with dry_run=false", async () => {
    mockApiPost.mockResolvedValue({
      run_id: "run-ach-1",
      dry_run: false,
      summary: { initiated: 2, skipped: 0, failed: 0 },
      results: [],
    });
    render(<Invoices />);
    await waitFor(() => expect(mockBulkActions.length).toBeGreaterThanOrEqual(1));
    const achAction = mockBulkActions.find((a) => a.key === "bulk-charge-ach-invoices");
    act(() => { achAction.onPress(); });
    // Grab the confirmation Alert buttons + tap "Submit ACH".
    const call = mockAlert.mock.calls[mockAlert.mock.calls.length - 1];
    const buttons = call[2] as any[];
    const submitBtn = buttons.find((b) => /submit ach/i.test(b.text || ""));
    expect(submitBtn).toBeTruthy();
    await act(async () => { await submitBtn.onPress(); });
    expect(mockApiPost).toHaveBeenCalledTimes(1);
    const [url, body] = mockApiPost.mock.calls[0];
    expect(url).toBe("/invoices/bulk-charge-ach-on-file");
    expect(body.dry_run).toBe(false);
    expect(Array.isArray(body.invoice_ids)).toBe(true);
    expect(body.invoice_ids).toEqual(expect.arrayContaining(["inv-1", "inv-2"]));
    expect(typeof body.idempotency_key).toBe("string");
    expect(body.idempotency_key.length).toBeGreaterThan(4);
    // Success Alert.
    const lastAlert = mockAlert.mock.calls[mockAlert.mock.calls.length - 1];
    expect(lastAlert[0]).toMatch(/ACH submissions sent/i);
    expect(lastAlert[1]).toMatch(/2 initiated/);
  });

  it("surfaces a failure Alert when the endpoint rejects", async () => {
    mockApiPost.mockRejectedValue(new Error("stripe not configured"));
    render(<Invoices />);
    await waitFor(() => expect(mockBulkActions.length).toBeGreaterThanOrEqual(1));
    const achAction = mockBulkActions.find((a) => a.key === "bulk-charge-ach-invoices");
    act(() => { achAction.onPress(); });
    const call = mockAlert.mock.calls[mockAlert.mock.calls.length - 1];
    const submitBtn = (call[2] as any[]).find((b) => /submit ach/i.test(b.text || ""));
    await act(async () => { await submitBtn.onPress(); });
    const lastAlert = mockAlert.mock.calls[mockAlert.mock.calls.length - 1];
    expect(lastAlert[0]).toMatch(/ACH bulk charge failed/i);
    expect(lastAlert[1]).toMatch(/stripe not configured/);
  });
});
