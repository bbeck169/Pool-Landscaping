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

jest.mock("@/src/api", () => {
  class ApiError extends Error { status = 0; detail: any = null; }
  return { api: { get: (u: string) => mockGet(u), post: jest.fn(), patch: jest.fn() }, ApiError };
});
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: mockRole } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ id: "L1" }),
  useFocusEffect: (cb: any) => { const R = require("react"); R.useEffect(() => { cb(); }, []); },
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("@/src/components/customer", () => {
  const { Text } = require("react-native");
  return { PhoneLink: ({ phone, testID }: any) => <Text testID={testID}>{phone}</Text>, AddressLink: () => null };
});

import LeadDetailScreen from "@/app/leads/[id]";

const BASE = { id: "L1", name: "Lena Lead", status: "new", phone: "+15550001111", email: "lena@x.com", timeline: [], quotes_count: 0 };
let mockLead: any = BASE;
let mockQuotes: any = { items: [], total: 0, limit: 10 };

beforeEach(() => {
  mockRole = "admin"; mockLead = { ...BASE }; mockQuotes = { items: [], total: 0, limit: 10 };
  mockPush.mockClear();
  mockGet.mockReset().mockImplementation(async (u: string) => {
    if (u.startsWith("/leads/L1/quotes")) return typeof mockQuotes === "function" ? mockQuotes() : mockQuotes;
    if (u === "/leads/L1") return mockLead;
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
