/**
 * TD-96-mobile · lead detail action buttons (app/leads/[id].tsx).
 * Gates mirror the backend: send = admin/super_admin/manager,
 * create-quote + linked panel = admin/super_admin.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPush = jest.fn();
let mockRole = "admin";
let mockParams: Record<string, string> = { id: "L1" };

jest.mock("@/src/api", () => {
  class ApiError extends Error { status = 0; detail: any = null; }
  return { api: { get: (u: string) => mockGet(u), post: jest.fn(), patch: jest.fn() }, ApiError };
});
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: mockRole } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => mockParams,
  useFocusEffect: (cb: any) => { const R = require("react"); R.useEffect(() => { cb(); }, []); },
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("@/src/components/customer", () => {
  const { Text } = require("react-native");
  return { PhoneLink: ({ phone, testID }: any) => <Text testID={testID}>{phone}</Text>, AddressLink: () => null };
});
// quote/new.tsx shell (D3 hydration case only) — unused by leads/[id].tsx.
jest.mock("react-native-keyboard-controller", () => ({ KeyboardAwareScrollView: ({ children }: any) => children }));
jest.mock("@/src/components/widgets", () => ({ Header: () => null }));
jest.mock("@/src/components/ui", () => ({ PrimaryButton: () => null }));
jest.mock("@/app/customer/new", () => ({ Field: () => null }));
jest.mock("@/src/components/quotes/QuoteRecipientPicker", () => {
  const { Text } = require("react-native");
  return { __esModule: true, default: ({ value }: any) => <Text testID="mock-recipient">{value ? `${value.type}:${value.name || value.id}` : "none"}</Text> };
});

import LeadDetailScreen from "@/app/leads/[id]";
import QuoteForm from "@/app/quote/new";

const BASE = { id: "L1", name: "Lena Lead", status: "new", phone: "+15550001111", email: "lena@x.com", timeline: [], quotes_count: 0 };
let mockLead: any = BASE;
let mockQuotes: any = { items: [], total: 0, limit: 10 };

beforeEach(() => {
  mockRole = "admin"; mockLead = { ...BASE }; mockQuotes = { items: [], total: 0, limit: 10 }; mockParams = { id: "L1" };
  mockPush.mockClear();
  mockGet.mockReset().mockImplementation(async (u: string) => {
    if (u.startsWith("/leads/L1/quotes")) return typeof mockQuotes === "function" ? mockQuotes() : mockQuotes;
    if (u === "/leads/L1") return mockLead;
    if (u === "/income-categories") return { categories: [] };
    throw new Error(`unexpected GET ${u}`);
  });
});

const mount = async (role = "admin") => {
  mockRole = role;
  const q = render(<LeadDetailScreen />);
  await waitFor(() => q.getByTestId(role.includes("tech") ? "lead-detail-role-gate" : "lead-name"));
  return q;
};
const isDisabled = (q: any, id: string) => q.getByTestId(id).props.accessibilityState?.disabled;

it("A1 · manager → SMS + Email render; Create Quote + linked panel hidden", async () => {
  const q = await mount("manager");
  expect(q.getByTestId("lead-detail-send-sms")).toBeTruthy();
  expect(q.getByTestId("lead-detail-send-email")).toBeTruthy();
  expect(q.queryByTestId("lead-create-quote")).toBeNull();
  expect(q.queryByTestId("lead-linked-quotes-panel")).toBeNull();
});

it("A5 · no phone → SMS disabled (press opens nothing); Email enabled → opens email sheet", async () => {
  mockLead = { ...BASE, phone: "" };
  const q = await mount();
  expect(isDisabled(q, "lead-detail-send-sms")).toBe(true);
  fireEvent.press(q.getByTestId("lead-detail-send-sms"));
  expect(q.queryByTestId("lead-compose-modal")).toBeNull();
  expect(isDisabled(q, "lead-detail-send-email")).toBe(false);
  await act(async () => { fireEvent.press(q.getByTestId("lead-detail-send-email")); });
  expect(q.getByTestId("lead-compose-subject")).toBeTruthy();
  fireEvent.press(q.getByTestId("lead-compose-cancel"));
  expect(q.queryByTestId("lead-compose-modal")).toBeNull();
});

it("A6 · no email → Email disabled; SMS enabled → opens SMS sheet (no subject)", async () => {
  mockLead = { ...BASE, email: null };
  const q = await mount();
  expect(isDisabled(q, "lead-detail-send-email")).toBe(true);
  await act(async () => { fireEvent.press(q.getByTestId("lead-detail-send-sms")); });
  expect(q.getByTestId("lead-compose-modal")).toBeTruthy();
  expect(q.queryByTestId("lead-compose-subject")).toBeNull();
});

it("A7 · closed_won lead → outreach still renders (not canAct-gated, web parity)", async () => {
  mockLead = { ...BASE, status: "closed_won" };
  const q = await mount();
  expect(q.queryByTestId("lead-actions")).toBeNull();
  expect(q.getByTestId("lead-detail-send-sms")).toBeTruthy();
  expect(q.getByTestId("lead-detail-send-email")).toBeTruthy();
});

it.each(["pool_tech", "landscape_tech"])("A9 · %s → role gate; none of the TD-96 testids render; no lead fetch", async (role) => {
  const q = await mount(role);
  for (const id of ["lead-detail-send-sms", "lead-detail-send-email", "lead-create-quote", "lead-linked-quotes-panel"]) {
    expect(q.queryByTestId(id)).toBeNull();
  }
  expect(mockGet).not.toHaveBeenCalled();
});

// ── b2 · Create Quote + count badge + linked-quotes panel (admin / super_admin) ──
const Q = (id: string, extra: any = {}) => ({ id, title: `Quote ${id}`, status: "draft", total: 120, doc_type: "quote", reparented: false, ...extra });

it.each(["admin", "super_admin"])("A2/A3 · %s → all 4 primitives; count badge = quotes_count; panel count = total", async (role) => {
  mockLead = { ...BASE, quotes_count: 2 };
  mockQuotes = { items: [Q("q1"), Q("q2", { doc_type: "invoice", status: "sent" })], total: 2, limit: 10 };
  const q = await mount(role);
  expect(q.getByTestId("lead-detail-send-sms")).toBeTruthy();
  expect(q.getByTestId("lead-detail-send-email")).toBeTruthy();
  expect(q.getByTestId("lead-create-quote-count").props.children.props.children).toBe("2");
  await waitFor(() => q.getByTestId("lead-linked-quotes-panel"));
  expect(q.getByTestId("lead-linked-quotes-count").props.children).toBe("2");
  expect(q.getByTestId("lead-linked-quote-row-q1")).toBeTruthy();
  expect(q.getByTestId("lead-linked-quote-row-q2")).toBeTruthy();
  expect(mockGet).toHaveBeenCalledWith("/leads/L1/quotes?limit=10");
});

it("A1b · manager → linked-quotes endpoint never called (would 403-free but admin-only UI)", async () => {
  mockLead = { ...BASE, quotes_count: 2 };
  await mount("manager");
  expect(mockGet.mock.calls.map((c) => c[0])).toEqual(["/leads/L1"]);
});

it("A4 · quotes_count 0 → Create Quote w/o badge; panel ALWAYS fetched (TD-96-g2 workaround) but hidden when empty", async () => {
  const q = await mount();
  expect(q.getByTestId("lead-create-quote")).toBeTruthy();
  expect(q.queryByTestId("lead-create-quote-count")).toBeNull();
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/leads/L1/quotes?limit=10"));
  expect(q.queryByTestId("lead-linked-quotes-panel")).toBeNull();
});

it("A4b · post-conversion: quotes_count 0 but reparented quotes exist → panel still renders with marker (A12)", async () => {
  mockLead = { ...BASE, status: "closed_won", quotes_count: 0, converted_customer_id: "C9" };
  mockQuotes = { items: [Q("r1", { reparented: true })], total: 1, limit: 10 };
  const q = await mount();
  await waitFor(() => q.getByTestId("lead-linked-quotes-panel"));
  expect(q.getByText("Linked Quote")).toBeTruthy();
  expect(q.getByTestId("lead-linked-quote-meta-r1").props.children).toMatch(/ · reparented$/);
  expect(q.getByTestId("lead-create-quote")).toBeTruthy();
});

it("A8 · Create Quote → /quote/new?recipient_type=lead&recipient_id=<id>; row tap → /quote/<qid>", async () => {
  mockQuotes = { items: [Q("q1")], total: 1, limit: 10 };
  const q = await mount();
  fireEvent.press(q.getByTestId("lead-create-quote"));
  expect(mockPush).toHaveBeenCalledWith("/quote/new?recipient_type=lead&recipient_id=L1");
  await waitFor(() => q.getByTestId("lead-linked-quote-row-q1"));
  fireEvent.press(q.getByTestId("lead-linked-quote-row-q1"));
  expect(mockPush).toHaveBeenLastCalledWith("/quote/q1");
});

it("A10 · linked-quotes fetch rejects → panel absent, screen intact (fail-open)", async () => {
  mockLead = { ...BASE, quotes_count: 3 };
  mockQuotes = () => Promise.reject(new Error("boom"));
  const q = await mount();
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/leads/L1/quotes?limit=10"));
  expect(q.queryByTestId("lead-linked-quotes-panel")).toBeNull();
  expect(q.getByTestId("lead-create-quote-count")).toBeTruthy();
});

it("A11 · total 12 / items 10 → 'View all 12 →' deep-links Quotes with lead + view:'all' (TD-96-g1-mobile)", async () => {
  mockQuotes = { items: Array.from({ length: 10 }, (_, i) => Q(`q${i}`)), total: 12, limit: 10 };
  const q = await mount();
  await waitFor(() => q.getByTestId("lead-linked-quotes-view-all"));
  expect(q.queryByTestId("lead-linked-quotes-more")).toBeNull();
  expect(q.getByText("View all 12 →")).toBeTruthy();
  fireEvent.press(q.getByTestId("lead-linked-quotes-view-all"));
  expect(mockPush).toHaveBeenCalledWith({ pathname: "/(app)/quotes", params: { lead: "L1", view: "all" } });
});

it("D3 · quote/new with recipient_type=lead hydrates the lead name via GET /leads/{id}", async () => {
  mockParams = { recipient_type: "lead", recipient_id: "L1" };
  const q = render(<QuoteForm />);
  expect(q.getByTestId("mock-recipient").props.children).toBe("lead:L1");
  await waitFor(() => expect(q.getByTestId("mock-recipient").props.children).toBe("lead:Lena Lead"));
  expect(mockGet).toHaveBeenCalledWith("/leads/L1");
});
