/**
 * TD-96-mobile-bulk-toast · leads list bulk status change.
 * Regression: `showToast` was referenced but never wired (since 4a8d04429),
 * so a SUCCESSFUL POST /leads/bulk-status threw a ReferenceError → the catch
 * showed "Error · showToast is not defined", select mode stayed on and the
 * list never reloaded.
 */
import React from "react";
import { Alert } from "react-native";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockToast = jest.fn();

jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u), post: (u: string, b: any) => mockPost(u, b) } }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn() }),
  useFocusEffect: (cb: any) => require("react").useEffect(cb, [cb]),
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("@/src/components/widgets", () => ({ Header: () => null, FilterRow: () => null, IconButton: () => null }));
jest.mock("@/src/components/ui", () => ({ Loading: () => null, EmptyState: () => null, StatusChip: () => null, PrimaryButton: () => null, Sheet: () => null }));
jest.mock("@/src/components/ui/AppTextInput", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/common/AddressAutocomplete", () => ({ __esModule: true, default: () => null }));
jest.mock("@/src/components/customer", () => ({ PhoneLink: () => null }));

import Leads from "@/app/leads/index";

const LEADS = [{ id: "L1", name: "Ana", status: "new" }, { id: "L2", name: "Ben", status: "new" }];
const listCalls = () => mockGet.mock.calls.filter((c) => String(c[0]).startsWith("/leads")).length;

beforeEach(() => {
  [mockToast].forEach((m) => m.mockReset());
  mockGet.mockReset().mockResolvedValue({ rows: LEADS, total: 2 });
  mockPost.mockReset().mockResolvedValue({ updated: 2 });
  jest.spyOn(Alert, "alert").mockImplementation(() => {});
});
afterEach(() => jest.restoreAllMocks());

async function selectBoth(q: ReturnType<typeof render>) {
  await waitFor(() => expect(q.getByTestId("lead-L1")).toBeTruthy());
  fireEvent(q.getByTestId("lead-L1"), "longPress");
  fireEvent.press(q.getByTestId("lead-L2"));
  await waitFor(() => expect(q.getByTestId("bulk-status-contacted")).toBeTruthy());
}

it("B1 · success → toast, NO error alert, select mode exits, list reloads", async () => {
  const q = render(<Leads />);
  await selectBoth(q);
  const before = listCalls();
  await act(async () => { fireEvent.press(q.getByTestId("bulk-status-contacted")); });
  expect(mockPost).toHaveBeenCalledWith("/leads/bulk-status", { ids: ["L1", "L2"], status: "contacted" });
  expect(mockToast).toHaveBeenCalledWith("2 leads set to contacted.");
  expect(Alert.alert).not.toHaveBeenCalled();
  await waitFor(() => expect(q.queryByTestId("bulk-status-contacted")).toBeNull());
  expect(listCalls()).toBeGreaterThan(before);
});

it("B2 · failure → existing error alert path, no toast", async () => {
  mockPost.mockRejectedValueOnce(new Error("Update failed upstream"));
  const q = render(<Leads />);
  await selectBoth(q);
  await act(async () => { fireEvent.press(q.getByTestId("bulk-status-closed_lost")); });
  expect(Alert.alert).toHaveBeenCalledWith("Error", "Update failed upstream");
  expect(mockToast).not.toHaveBeenCalled();
});
