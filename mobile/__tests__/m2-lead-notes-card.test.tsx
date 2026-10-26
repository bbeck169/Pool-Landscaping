/**
 * M2 commit 2 · Lead notes card — append-only (POST /leads/{id}/note), customer-profile-style.
 */
import React from "react";
import { render, waitFor, fireEvent, act, within } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPut = jest.fn();
const mockPatch = jest.fn();
jest.mock("@/src/api", () => ({ api: {
  get: (...a: any[]) => mockGet(...a), post: (...a: any[]) => mockPost(...a),
  put: (...a: any[]) => mockPut(...a), patch: (...a: any[]) => mockPatch(...a) } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: "admin" } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: jest.fn() }) }));
jest.mock("expo-router", () => ({
  useLocalSearchParams: () => ({ id: "L1" }),
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useFocusEffect: (cb: any) => { const R = require("react"); R.useEffect(cb, [cb]); },
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("@/src/components/customer", () => ({ PhoneLink: () => null, AddressLink: () => null }));
jest.mock("@/src/components/leads/LeadLinkedQuotesPanel", () => () => null);
jest.mock("@/src/components/leads/LeadCommunicationTimeline", () => () => null);
jest.mock("@/src/components/leads/LeadComposeSheet", () => () => null);
jest.mock("@/src/components/leads/LeadRequestedServiceCard", () => () => null);
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));

import LeadDetailScreen from "@/app/leads/[id]";

const TL = [
  { kind: "created", ts: "2026-10-01T10:00:00Z" },
  { kind: "note_added", ts: "2026-10-02T10:00:00Z", payload: { text: "first" } },
  { kind: "status_change", ts: "2026-10-03T10:00:00Z", payload: { to: "contacted" } },
  { kind: "note_added", ts: "2026-10-04T10:00:00Z", payload: { text: "second" } },
];
const LEAD = { id: "L1", name: "N", status: "new", timeline: TL };
beforeEach(() => { [mockGet, mockPost, mockPut, mockPatch].forEach((m) => m.mockReset()); });

it("N1 · notes list = note_added entries only, newest first, count in title", async () => {
  mockGet.mockResolvedValue(LEAD);
  const q = render(<LeadDetailScreen />);
  await waitFor(() => expect(q.getByTestId("lead-notes-card")).toBeTruthy());
  expect(q.getByTestId("lead-notes-title").props.children.join("")).toBe("Notes (2)");
  expect(within(q.getByTestId("lead-note-row-0")).getByText(/second/)).toBeTruthy();
  expect(within(q.getByTestId("lead-note-row-1")).getByText(/first/)).toBeTruthy();
});

it("N2 · add note stays append-only: POST /leads/{id}/note {text}; never PUT/PATCH; list refreshes from response", async () => {
  mockGet.mockResolvedValue(LEAD);
  mockPost.mockResolvedValue({ ...LEAD, timeline: [...TL, { kind: "note_added", ts: "2026-10-05T10:00:00Z", payload: { text: "third" } }] });
  const q = render(<LeadDetailScreen />);
  await waitFor(() => expect(q.getByTestId("lead-note-input")).toBeTruthy());
  fireEvent.changeText(q.getByTestId("lead-note-input"), "  third  ");
  await act(async () => { fireEvent.press(q.getByTestId("lead-note-submit")); });
  expect(mockPost).toHaveBeenCalledWith("/leads/L1/note", { text: "third" });
  expect(mockPut).not.toHaveBeenCalled();
  expect(mockPatch).not.toHaveBeenCalled();
  await waitFor(() => expect(within(q.getByTestId("lead-note-row-0")).getByText(/third/)).toBeTruthy());
  expect(q.getByTestId("lead-note-input").props.value).toBe("");
});

it("N3 · empty input → submit disabled; no notes → empty state", async () => {
  mockGet.mockResolvedValue({ ...LEAD, timeline: [] });
  const q = render(<LeadDetailScreen />);
  await waitFor(() => expect(q.getByTestId("lead-notes-empty")).toBeTruthy());
  expect(q.getByTestId("lead-note-submit").props.accessibilityState?.disabled).toBe(true);
});

it("N4 · web-written lead.notes shown read-only; absent → hidden", async () => {
  mockGet.mockResolvedValue({ ...LEAD, notes: "Gate code 1234" });
  const q = render(<LeadDetailScreen />);
  await waitFor(() => expect(within(q.getByTestId("lead-notes-field")).getByText(/Gate code 1234/)).toBeTruthy());
  mockGet.mockResolvedValue(LEAD);
  const q2 = render(<LeadDetailScreen />);
  await waitFor(() => expect(q2.getByTestId("lead-notes-card")).toBeTruthy());
  expect(q2.queryByTestId("lead-notes-field")).toBeNull();
});
