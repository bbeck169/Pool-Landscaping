/**
 * TD-96-mobile-timeline b2 · wiring on app/leads/[id].tsx.
 * Mount below Timeline (web placement); compose onSent → timeline refetch (web parity);
 * strict D3b: status changes do NOT refetch the communication timeline.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPatch = jest.fn();

jest.mock("@/src/api", () => {
  class ApiError extends Error { status = 0; detail: any = null; }
  return { api: { get: (u: string) => mockGet(u), post: (u: string, b: any) => mockPost(u, b), patch: (u: string, b: any) => mockPatch(u, b) }, ApiError };
});
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: "manager" } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({ id: "L1" }),
  useFocusEffect: (cb: any) => { const R = require("react"); R.useEffect(() => { cb(); }, []); },
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("@/src/components/customer", () => ({ PhoneLink: () => null, AddressLink: () => null }));

import LeadDetailScreen from "@/app/leads/[id]";

const LEAD = { id: "L1", name: "Lena Lead", status: "new", phone: "+15550001111", email: "lena@x.com", timeline: [], quotes_count: 0 };
const COMMS = "/leads/L1/communications?limit=50";
const commCalls = () => mockGet.mock.calls.filter((c) => c[0] === COMMS).length;

beforeEach(() => {
  mockGet.mockReset().mockImplementation(async (u: string) => {
    if (u === "/leads/L1") return LEAD;
    if (u === COMMS) return { items: [{ id: "c1", type: "sms", direction: "outbound", status: "sent", body: "Hello", created_at: "2026-09-15T04:53:03+00:00" }], next_cursor: null, has_more: false };
    throw new Error(`unexpected GET ${u}`);
  });
  mockPost.mockReset().mockResolvedValue({ id: "c2", status: "sent" });
  mockPatch.mockReset().mockImplementation(async (_u: string, b: any) => ({ ...LEAD, ...b }));
});

const mount = async () => {
  const q = render(<LeadDetailScreen />);
  await waitFor(() => q.getByTestId("lead-comm-item-sms"));
  return q;
};

it("W1 · card mounts after the lead loads and fetches the lead communications", async () => {
  const q = await mount();
  expect(q.getByTestId("lead-communication-timeline")).toBeTruthy();
  expect(commCalls()).toBe(1);
});

it("W2 · compose SMS sent → onSent refetches the communication timeline", async () => {
  const q = await mount();
  await act(async () => { fireEvent.press(q.getByTestId("lead-detail-send-sms")); });
  fireEvent.changeText(q.getByTestId("lead-compose-body"), "Hi Lena");
  await act(async () => { fireEvent.press(q.getByTestId("lead-compose-send")); });
  expect(mockPost).toHaveBeenCalledWith("/leads/L1/send-sms", expect.objectContaining({ body: "Hi Lena" }));
  await waitFor(() => expect(commCalls()).toBe(2));
  expect(q.queryByTestId("lead-compose-modal")).toBeNull();
});

it("W3 · status change does NOT refetch the communication timeline (strict web parity, D3b)", async () => {
  const q = await mount();
  await act(async () => { fireEvent.press(q.getByTestId("lead-status-contacted")); });
  expect(mockPatch).toHaveBeenCalledWith("/leads/L1", { status: "contacted" });
  await act(async () => {});
  expect(commCalls()).toBe(1);
});
