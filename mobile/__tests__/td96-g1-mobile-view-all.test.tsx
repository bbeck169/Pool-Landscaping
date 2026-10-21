/**
 * TD-96-g1-mobile · Quotes list `?lead=<lid>` filter (web QuotesList
 * 00888d0af parity + D1 view:"all", D2 badge, D4 all roles, cache guard).
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockSetParams = jest.fn();
const mockWriteCache = jest.fn(async () => {});
const mockReadCache = jest.fn(async () => [{ id: "cached", title: "Cached" }]);
let mockParams: any = {};
let mockRole = "admin";

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), setParams: mockSetParams }),
  useFocusEffect: (cb: any) => require("react").useEffect(cb, [cb]),
  useLocalSearchParams: () => mockParams,
}));
jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u), post: jest.fn() } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: mockRole } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("@/src/components/ConfirmModal", () => ({ showConfirm: jest.fn() }));
jest.mock("@/src/services/readCache", () => ({
  writeCache: (...a: any[]) => mockWriteCache(...(a as [])), readCache: (...a: any[]) => mockReadCache(...(a as [])),
}));
jest.mock("@/src/components/widgets", () => ({ Header: () => null, FilterRow: () => null, IconButton: () => null, NotificationBell: () => null }));
jest.mock("@/src/components/ui", () => {
  const { View } = require("react-native");
  return { Loading: () => null, EmptyState: ({ testID }: any) => <View testID={testID} />, StatusChip: () => null };
});

import Quotes from "@/app/(app)/quotes";

const QUOTE = { id: "q1", title: "Pool resurfacing", status: "draft", doc_type: "quote", total: 100, customer_name: "Lena" };
const quoteCalls = () => mockGet.mock.calls.map((c) => c[0]).filter((u: string) => u.startsWith("/quotes"));

beforeEach(() => {
  mockParams = {}; mockRole = "admin";
  [mockSetParams, mockWriteCache, mockReadCache].forEach((m) => m.mockClear());
  mockGet.mockReset().mockImplementation(async (u: string) => {
    if (u.startsWith("/quotes")) return [QUOTE];
    if (u === "/leads/L1abcdef99") return { id: "L1abcdef99", name: "Lena Lead" };
    throw Object.assign(new Error("Not found"), { status: 404 });
  });
});

it("G1 · no param → unchanged fetch (?view=open), no lead_id, no badge, cache written", async () => {
  const q = render(<Quotes />);
  await waitFor(() => expect(quoteCalls()).toContain("/quotes?view=open"));
  expect(quoteCalls().some((u) => u.includes("lead_id"))).toBe(false);
  expect(q.queryByTestId("quotes-filter-lead-bar")).toBeNull();
  expect(mockWriteCache).toHaveBeenCalledWith("quotes:open", [QUOTE]);
});

it("G2 · admin: lead + view:'all' (panel link) → /quotes?view=all&lead_id=<lid>", async () => {
  mockParams = { lead: "L1abcdef99", view: "all" };
  render(<Quotes />);
  await waitFor(() => expect(quoteCalls()).toContain("/quotes?view=all&lead_id=L1abcdef99"));
});

it("G3 · invalid view param is ignored (stays open); lead still applied", async () => {
  mockParams = { lead: "L1abcdef99", view: "bogus" };
  render(<Quotes />);
  await waitFor(() => expect(quoteCalls()).toContain("/quotes?view=open&lead_id=L1abcdef99"));
  expect(quoteCalls().some((u) => u.includes("bogus"))).toBe(false);
});

it("G4 · non-admin (manager) branch gets the filter too (D4)", async () => {
  mockRole = "manager";
  mockParams = { lead: "L1abcdef99" };
  render(<Quotes />);
  await waitFor(() => expect(quoteCalls()).toContain("/quotes?lead_id=L1abcdef99"));
});

it("G5 · badge shows the lead name from GET /leads/{lid}", async () => {
  mockParams = { lead: "L1abcdef99", view: "all" };
  const q = render(<Quotes />);
  await waitFor(() => expect(q.getByTestId("quotes-filter-lead-badge").props.children).toBe("Lena Lead"));
  expect(mockGet).toHaveBeenCalledWith("/leads/L1abcdef99");
});

it("G6 · badge falls back to 'Lead <id[:8]>' when the lead fetch 404s", async () => {
  mockParams = { lead: "ZZ99887766" };
  const q = render(<Quotes />);
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith("/leads/ZZ99887766"));
  expect(q.getByTestId("quotes-filter-lead-badge").props.children).toBe("Lead ZZ998877");
});

it("G7 · Clear removes the lead param via router.setParams", async () => {
  mockParams = { lead: "L1abcdef99", view: "all" };
  const q = render(<Quotes />);
  await waitFor(() => expect(q.getByTestId("quotes-filter-lead-clear")).toBeTruthy());
  fireEvent.press(q.getByTestId("quotes-filter-lead-clear"));
  expect(mockSetParams).toHaveBeenCalledWith({ lead: undefined });
});

it("G8 · filtered fetches never write or read the offline cache; failure shows empty, not stale rows", async () => {
  mockParams = { lead: "L1abcdef99", view: "all" };
  const q = render(<Quotes />);
  await waitFor(() => expect(quoteCalls()).toContain("/quotes?view=all&lead_id=L1abcdef99"));
  expect(mockWriteCache).not.toHaveBeenCalled();
  mockGet.mockImplementation(async (u: string) => { if (u.startsWith("/quotes")) throw new Error("offline"); return {}; });
  mockParams = { lead: "L2offline00", view: "all" };
  q.rerender(<Quotes />);
  await waitFor(() => expect(q.getByTestId("quotes-empty")).toBeTruthy());
  expect(mockReadCache).not.toHaveBeenCalled();
});
