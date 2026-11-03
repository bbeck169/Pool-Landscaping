/**
 * TD-estimate-public-instructional-copy-mobile-parity (web a5d4c58f9).
 * Locks the exact helper wording + gating: shown only on the customer surface
 * (as_customer) while the estimate is actionable (sent / viewed) and not locked
 * (accepted / declined). Hidden for admin / non-customer payloads, drafts and
 * finalized estimates. Mobile has no printable / flipbook branch.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

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
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
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

const COPY =
  "You can customize your estimate by clicking Decline on any line item before approving the final estimate.";
const NUDGE = "estimate-line-items-instructional-copy";

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

describe("Estimate view — Decline instructional copy (mobile parity)", () => {
  beforeEach(() => jest.clearAllMocks());

  it("locks the exact wording, rendered once, above the itemized lines", async () => {
    const { getByTestId, getAllByTestId } = await renderWith(BASE);
    await waitFor(() => getByTestId(NUDGE));
    expect(getAllByTestId(NUDGE)).toHaveLength(1);
    expect(getByTestId(NUDGE).props.children).toBe(COPY);
    // Sits inside the line-items card (directly above the first line).
    const card = getByTestId("estimate-line-items");
    expect(() => require("@testing-library/react-native").within(card).getByTestId(NUDGE)).not.toThrow();
  });

  it("renders for status=viewed", async () => {
    const { getByTestId } = await renderWith({ ...BASE, status: "viewed" });
    await waitFor(() => getByTestId(NUDGE));
  });

  it("renders in the grouped (customer_view) branch", async () => {
    const { getByTestId } = await renderWith(GROUPED);
    await waitFor(() => getByTestId(NUDGE));
    const card = getByTestId("estimate-grouped-lines");
    expect(require("@testing-library/react-native").within(card).getByTestId(NUDGE).props.children).toBe(COPY);
  });

  it.each([
    ["admin / non-customer payload", { ...BASE, as_customer: false }],
    ["draft (not actionable)", { ...BASE, status: "draft" }],
    ["accepted (locked)", { ...BASE, status: "accepted", decision: "accepted", accepted_at: "2026-09-09" }],
    ["declined (locked)", { ...BASE, status: "declined", decision: "declined", declined_at: "2026-09-09" }],
    ["sent but decision accepted (locked)", { ...BASE, decision: "accepted", accepted_at: "2026-09-09" }],
    ["grouped + locked", { ...GROUPED, decision: "declined", declined_at: "2026-09-09" }],
  ])("hidden for %s", async (_label, data) => {
    const { queryByTestId, queryByText } = await renderWith(data);
    await waitFor(() => expect(mockFetchToken).toHaveBeenCalled());
    expect(queryByTestId(NUDGE)).toBeNull();
    expect(queryByText(COPY)).toBeNull();
  });

  it("hidden on the itemized branch when no per-line Decline buttons exist (no magic token)", async () => {
    const { queryByTestId } = await renderWith(BASE, null);
    await waitFor(() => expect(mockFetchToken).toHaveBeenCalled());
    expect(queryByTestId("estimate-line-item-decline-0")).toBeNull();
    expect(queryByTestId(NUDGE)).toBeNull();
  });
});
