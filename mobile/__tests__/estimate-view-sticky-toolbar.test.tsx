/**
 * TD-estimate-toolbar-sticky-footer-mobile-parity (web 032c28f0a).
 * Customer surface (as_customer && actionable && !locked): the Approve /
 * Decline / Changes toolbar is pinned in a sticky footer (flex sibling below
 * the ScrollView) with the bottom safe-area inset. Admin keeps the inline
 * toolbar; locked / draft render no sticky footer. testIDs unchanged.
 */
import React from "react";
import { render, waitFor, within, fireEvent } from "@testing-library/react-native";
import { StyleSheet } from "react-native";

jest.mock("@/src/theme", () => ({
  colors: {
    brand: "#2563EB", muted: "#9CA3AF", onSurface: "#111827",
    error: "#EF4444", surface: "#FFFFFF", border: "#E5E7EB",
    surfaceSecondary: "#F9FAFB", warning: "#F59E0B", success: "#16A34A",
  },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 11, sm: 13, base: 15, md: 15, lg: 18, xl: 22, "2xl": 28 },
  money: (v: number) => `$${(v || 0).toFixed(2)}`,
  inputColors: { bg: "#FFFFFF", text: "#000080", placeholder: "rgba(0,0,128,0.55)" },
}));
jest.mock("@expo/vector-icons", () => {
  const { Text } = require("react-native");
  return { Ionicons: (p: any) => <Text>{p.name}</Text> };
});
jest.mock("expo-router", () => ({
  useLocalSearchParams: () => ({ id: "est-1" }),
  useRouter: () => ({ back: jest.fn(), push: jest.fn(), replace: jest.fn() }),
  useFocusEffect: (cb: any) => cb(),
  useSegments: () => [],
  Redirect: () => null,
  Link: ({ children }: any) => children,
}));
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 34, left: 0, right: 0 }),
  SafeAreaView: ({ children }: any) => children,
}));
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { id: "c1", role: "customer", name: "Cust" }, isLoggedIn: true }),
}));
jest.mock("@/src/components/files", () => ({ InvoiceAttachments: () => null }));
jest.mock("@/src/api/estimatesFull", () => ({
  getEstimateFull: jest.fn(),
  acceptEstimate: jest.fn(),
  declineEstimate: jest.fn(),
  requestEstimateChanges: jest.fn(),
  fetchMagicLinkToken: jest.fn(),
  declineLineItem: jest.fn(),
  undeclineLineItem: jest.fn(),
  approveViaToken: jest.fn(),
  declineViaToken: jest.fn(),
}));

import EstimateViewScreen from "@/app/estimate-view/[id]";
import { getEstimateFull, fetchMagicLinkToken } from "@/src/api/estimatesFull";

const mockGetFull = getEstimateFull as jest.MockedFunction<typeof getEstimateFull>;
const mockFetchToken = fetchMagicLinkToken as jest.MockedFunction<typeof fetchMagicLinkToken>;

const BASE = {
  company: { name: "Test Co", address: "123 Main St", phone: "555-0100" },
  bill_to: { name: "Customer X", address: "456 Oak Ave" },
  property_address: "789 Pine Rd",
  header: { customer_number: "C001", estimate_number: "EST001", estimate_date: "2026-09-09" },
  title: "Test Quote",
  status: "sent",
  decision: null,
  accepted_at: null,
  declined_at: null,
  as_customer: true,
  line_items: [
    { description: "Pool Cleaning", qty_hr: 1, visits: 1, total: 100, customer_status: "pending" },
  ],
  totals: {
    subtotal: 100, taxes: 0, amount_paid: 0, total_estimated_cost: 100,
    has_declined_lines: false, original_total: 100, adjusted_total: 100,
  },
  notes: "",
};

const GROUPED = {
  ...BASE,
  customer_view: { groups: [{ group_key: "g1", category_id: "pool", label: "Pool Service", subtotal: 100, declined: false }] },
};

async function renderWith(data: any, token: string | null = "magic-tok") {
  mockGetFull.mockResolvedValue(data);
  mockFetchToken.mockResolvedValue(token as any);
  const r = render(<EstimateViewScreen />);
  await waitFor(() => r.getByTestId("estimate-header-card"));
  return r;
}

const STICKY = "estimate-toolbar-sticky-footer";
const CTAS = ["estimate-toolbar-customer-approve", "estimate-toolbar-customer-decline", "estimate-changes-btn"];

describe("Estimate view — sticky customer toolbar (mobile parity)", () => {
  beforeEach(() => jest.clearAllMocks());

  it.each([["sent"], ["viewed"]])("customer + %s → sticky footer holds all 3 CTAs, once each", async (status) => {
    const { getByTestId, getAllByTestId } = await renderWith({ ...BASE, status });
    const sticky = getByTestId(STICKY);
    for (const id of CTAS) {
      expect(within(sticky).getByTestId(id)).toBeTruthy();
      expect(getAllByTestId(id)).toHaveLength(1); // not duplicated inline
    }
  });

  it("sticky footer is outside the ScrollView and pads for the bottom safe-area inset", async () => {
    const { getByTestId, UNSAFE_getByType } = await renderWith(BASE);
    const scroll = UNSAFE_getByType(require("react-native").ScrollView);
    expect(within(scroll).queryByTestId(STICKY)).toBeNull();
    const style = StyleSheet.flatten(getByTestId(STICKY).props.style);
    expect(style.paddingBottom).toBe(34);
    expect(style.borderTopWidth).toBe(1);
  });

  it("handlers unchanged — Decline in the sticky footer opens the decline dialog", async () => {
    const { getByTestId, queryByTestId } = await renderWith(BASE);
    expect(queryByTestId("estimate-decline-modal")).toBeNull(); // hidden Modal isn't in the tree
    fireEvent.press(within(getByTestId(STICKY)).getByTestId("estimate-toolbar-customer-decline"));
    await waitFor(() => expect(getByTestId("estimate-decline-modal")).toBeTruthy());
  });

  it("admin / non-customer → no sticky footer, inline toolbar kept", async () => {
    const { queryByTestId, getByTestId, UNSAFE_getByType } = await renderWith({ ...BASE, as_customer: false });
    expect(queryByTestId(STICKY)).toBeNull();
    const scroll = UNSAFE_getByType(require("react-native").ScrollView);
    expect(within(scroll).getByTestId("estimate-toolbar-customer-approve")).toBeTruthy();
  });

  it.each([
    ["accepted (locked)", { ...BASE, status: "accepted", decision: "accepted", accepted_at: "2026-09-09" }],
    ["declined (locked)", { ...BASE, status: "declined", decision: "declined", declined_at: "2026-09-09" }],
    ["sent + decision accepted (locked)", { ...BASE, decision: "accepted", accepted_at: "2026-09-09" }],
    ["draft (not actionable)", { ...BASE, status: "draft" }],
  ])("no sticky footer for %s", async (_l, data) => {
    const { queryByTestId } = await renderWith(data);
    expect(queryByTestId(STICKY)).toBeNull();
    expect(queryByTestId("estimate-toolbar-customer-approve")).toBeNull();
  });
});
