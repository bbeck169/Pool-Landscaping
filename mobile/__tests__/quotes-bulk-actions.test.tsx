/**
 * Phase 4b mobile parity — Quotes bulk select + Accept / Decline / Delete.
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

let mockRole = "admin";
const mockGet = jest.fn();
const mockPost = jest.fn();
const mockToast = jest.fn();
const mockConfirm = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn() }),
  useFocusEffect: (cb: any) => require("react").useEffect(cb, [cb]),
  useLocalSearchParams: () => ({}), // TD-96-g1-mobile: quotes.tsx reads ?lead / ?view
}));
jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockGet(...a), post: (...a: any[]) => mockPost(...a) } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: mockRole } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));
jest.mock("@/src/components/ConfirmModal", () => ({ showConfirm: (o: any) => mockConfirm(o) }));
jest.mock("@/src/services/readCache", () => ({ writeCache: async () => {}, readCache: async () => null }));
jest.mock("@/src/components/widgets", () => ({ Header: () => null, FilterRow: () => null, IconButton: () => null, NotificationBell: () => null }));
jest.mock("@/src/components/ui", () => ({ Loading: () => null, EmptyState: () => null, StatusChip: () => null }));

import Quotes from "@/app/(app)/quotes";
import { bulkOutcomeMessage } from "@/src/components/quotes/QuotesBulkToolbar";

const ROWS = [
  { id: "q1", title: "Pool resurface", status: "sent", doc_type: "quote", total: 100 },
  { id: "q2", title: "Pump swap", status: "draft", doc_type: "quote", total: 50 },
];

beforeEach(() => {
  jest.clearAllMocks();
  mockRole = "admin";
  mockGet.mockResolvedValue(ROWS);
});

async function selectBoth() {
  const r = render(<Quotes />);
  fireEvent.press(await r.findByTestId("quote-row-select-q1"));
  fireEvent.press(r.getByTestId("quote-row-select-q2"));
  return r;
}

it("toolbar appears on selection with count; Accept posts ids + toasts counts; skipped stays selected", async () => {
  mockPost.mockResolvedValue({ succeeded: ["q1"], skipped: [{ id: "q2", reason: "status" }] });
  const r = render(<Quotes />);
  expect(await r.findByTestId("quote-row-select-q1")).toBeTruthy();
  expect(r.queryByTestId("quotes-bulk-toolbar")).toBeNull();
  fireEvent.press(r.getByTestId("quote-row-select-q1"));
  fireEvent.press(r.getByTestId("quote-row-select-q2"));
  expect(r.getByTestId("quotes-bulk-count").props.children).toEqual(["2 quotes", " selected"]);
  fireEvent.press(r.getByTestId("quotes-bulk-accept"));
  await waitFor(() => expect(mockToast).toHaveBeenCalledWith("1 accepted, 1 skipped (ineligible)", "success"));
  expect(mockPost).toHaveBeenCalledWith("/quotes/bulk-accept", { quote_ids: ["q1", "q2"] });
  expect(r.getByTestId("quotes-bulk-count").props.children).toEqual(["1 quote", " selected"]);
});

it("Decline hits bulk-decline; Delete confirms first then hits bulk-delete", async () => {
  mockPost.mockResolvedValue({ succeeded: ["q1", "q2"], skipped: [] });
  const r = await selectBoth();
  fireEvent.press(r.getByTestId("quotes-bulk-decline"));
  await waitFor(() => expect(mockToast).toHaveBeenCalledWith("2 declined", "success"));
  expect(mockPost).toHaveBeenLastCalledWith("/quotes/bulk-decline", { quote_ids: ["q1", "q2"] });

  fireEvent.press(r.getByTestId("quote-row-select-q1"));
  fireEvent.press(r.getByTestId("quotes-bulk-delete"));
  expect(mockConfirm).toHaveBeenCalledWith(expect.objectContaining({ title: "Delete 1 quote?", confirmStyle: "destructive" }));
  expect(mockConfirm.mock.calls[0][0].message).toMatch(/cannot be undone/);
  expect(mockPost).toHaveBeenCalledTimes(1); // not yet
  await mockConfirm.mock.calls[0][0].onConfirm();
  expect(mockPost).toHaveBeenLastCalledWith("/quotes/bulk-delete", { quote_ids: ["q1"] });
});

it("clear selection hides the toolbar", async () => {
  const r = await selectBoth();
  fireEvent.press(r.getByTestId("quotes-bulk-clear"));
  expect(r.queryByTestId("quotes-bulk-toolbar")).toBeNull();
});

it("tech role: no checkboxes, no toolbar", async () => {
  mockRole = "technician";
  const r = render(<Quotes />);
  expect(await r.findByTestId("quote-card-q1")).toBeTruthy();
  expect(r.queryByTestId("quote-row-select-q1")).toBeNull();
  expect(r.queryByTestId("quotes-bulk-toolbar")).toBeNull();
});

it("outcome copy matches web", () => {
  expect(bulkOutcomeMessage("deleted", [], [])).toEqual({ message: "No deleted action taken.", tone: "info" });
  expect(bulkOutcomeMessage("accepted", [], [{}, {}])).toEqual({ message: "0 accepted, 2 skipped (ineligible)", tone: "info" });
  expect(bulkOutcomeMessage("accepted", ["a", "b", "c"], [{}, {}]).message).toBe("3 accepted, 2 skipped (ineligible)");
});
