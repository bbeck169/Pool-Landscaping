/**
 * TD-82 b2 · admin Jobs list bulk actions (B-narrow).
 * Web parity: pages/jobs/JobsList.jsx (bulk-update / bulk-delete).
 */
import React from "react";
import { Platform } from "react-native";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPush = jest.fn();
const mockToast = jest.fn();
const mockConfirm = jest.fn();
let mockRole = "admin";

jest.mock("@/src/api", () => ({ api: { get: (u: string) => mockGet(u), post: (u: string, b: any) => mockPost(u, b) } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: mockRole } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));
jest.mock("@/src/components/ConfirmModal", () => ({ showConfirm: (o: any) => mockConfirm(o) }));
jest.mock("@react-native-community/datetimepicker", () => () => null);
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("expo-router", () => {
  const React = jest.requireActual("react");
  const { Text } = jest.requireActual("react-native");
  return {
    useLocalSearchParams: () => ({}),
    useRouter: () => ({ push: mockPush, back: jest.fn(), setParams: jest.fn() }),
    useFocusEffect: (cb: any) => React.useEffect(() => cb(), [cb]),
    Redirect: ({ href }: any) => <Text testID="redirect">{String(href)}</Text>,
  };
});
jest.mock("@/src/components/widgets", () => {
  const { View, Text, Pressable } = jest.requireActual("react-native");
  return {
    Header: (p: any) => <View><Text>{p.title}</Text>{p.right}</View>,
    FilterRow: (p: any) => (
      <View>{p.options.map((o: any) => <Pressable key={o.key} testID={`${p.testID}-${o.key}`} onPress={() => p.onChange(o.key)}><Text>{o.label}</Text></Pressable>)}</View>
    ),
  };
});

import AdminJobsList, { bulkResultMessage } from "@/app/admin/jobs";

const JOBS = [{ id: "j1", title: "Clean A", status: "scheduled" }, { id: "j2", title: "Clean B", status: "pending" }, { id: "j3", title: "Clean C", status: "active" }];
const origOS = Platform.OS;

beforeEach(() => {
  mockRole = "admin";
  [mockPush, mockToast, mockConfirm].forEach((m) => m.mockReset());
  mockGet.mockReset().mockResolvedValue(JOBS);
  mockPost.mockReset();
});
afterEach(() => { (Platform as any).OS = origOS; });

const mount = async () => {
  const q = render(<AdminJobsList />);
  await waitFor(() => q.getByTestId("job-row-j1"));
  return q;
};
const pickTwo = async (q: any) => {
  fireEvent(q.getByTestId("job-row-j1"), "longPress");
  fireEvent.press(q.getByTestId("job-row-j2"));
  await waitFor(() => expect(q.getByTestId("bulk-action-bar-count").props.children).toEqual([2, " selected"]));
};

it("L1 · entry via long-press (selects row) and via header Select; tap toggles in select mode, opens job otherwise; Cancel exits", async () => {
  const q = await mount();
  fireEvent.press(q.getByTestId("job-row-j3"));
  expect(mockPush).toHaveBeenCalledWith("/job/j3");
  fireEvent(q.getByTestId("job-row-j1"), "longPress");
  expect(q.getByTestId("job-row-check-j1")).toBeTruthy();
  fireEvent.press(q.getByTestId("job-row-j2"));
  expect(q.getByTestId("bulk-action-bar-count").props.children).toEqual([2, " selected"]);
  expect(mockPush).toHaveBeenCalledTimes(1);
  fireEvent.press(q.getByTestId("jobs-select-cancel"));
  expect(q.queryByTestId("bulk-action-bar")).toBeNull();
  fireEvent.press(q.getByTestId("jobs-select-toggle"));
  expect(q.getByTestId("job-row-check-j1")).toBeTruthy();
  expect(q.queryByTestId("bulk-action-bar")).toBeNull(); // nothing selected yet
});

it("L2 · select-all = all loaded rows; filter change clears selection", async () => {
  const q = await mount();
  fireEvent.press(q.getByTestId("jobs-select-toggle"));
  fireEvent.press(q.getByTestId("jobs-select-all"));
  expect(q.getByTestId("bulk-action-bar-count").props.children).toEqual([3, " selected"]);
  expect(q.getByText("3 of 3 selected")).toBeTruthy();
  await act(async () => { fireEvent.press(q.getByTestId("jobs-filter-status-pending")); });
  await waitFor(() => q.getByTestId("job-row-j1"));
  expect(q.queryByTestId("bulk-action-bar")).toBeNull();
});

it("L3 · Change status: silent → POST /jobs/bulk-update {ids, patch:{status}}; toast; exits select mode; reloads", async () => {
  mockPost.mockResolvedValue({ ok: true, updated_count: 2, updated: ["j1", "j2"], failed: [] });
  const q = await mount();
  await pickTwo(q);
  fireEvent.press(q.getByTestId("bulk-action-status"));
  await act(async () => { fireEvent.press(q.getByTestId("bulk-status-option-completed")); });
  expect(mockConfirm).not.toHaveBeenCalled();
  expect(mockPost).toHaveBeenCalledWith("/jobs/bulk-update", { ids: ["j1", "j2"], patch: { status: "completed" } });
  expect(mockToast).toHaveBeenCalledWith("2 jobs → completed", "success");
  expect(q.queryByTestId("bulk-action-bar")).toBeNull();
  expect(q.queryByTestId("job-row-check-j1")).toBeNull();
  expect(mockGet).toHaveBeenCalledTimes(2);
});

it("L4 · partial failure → 'X updated · Y locked — reasons' (info)", async () => {
  mockPost.mockResolvedValue({ ok: true, updated_count: 1, failed: [{ id: "j2", reason: "Active timer running", status_code: 409 }] });
  const q = await mount();
  await pickTwo(q);
  fireEvent.press(q.getByTestId("bulk-action-status"));
  await act(async () => { fireEvent.press(q.getByTestId("bulk-status-option-canceled")); });
  expect(mockToast).toHaveBeenCalledWith("1 job → canceled · 1 locked — Active timer running", "info");
  expect(bulkResultMessage("x", [{ reason: "a" }, { reason: "b" }, { reason: "c" }, { reason: "d" }]).text).toBe("x · 4 locked — a · b · c");
});

it("L5 · Reschedule: sheet Apply → POST bulk-update {scheduled_date}; friendly-date toast", async () => {
  (Platform as any).OS = "web";
  mockPost.mockResolvedValue({ ok: true, updated_count: 2, failed: [] });
  const q = await mount();
  await pickTwo(q);
  fireEvent.press(q.getByTestId("bulk-action-reschedule"));
  fireEvent.changeText(q.getByTestId("bulk-reschedule-datepicker"), "2026-11-04");
  expect(q.getByTestId("bulk-reschedule-summary").props.children).toBe("Move 2 jobs to Wed, Nov 4, 2026");
  await act(async () => { fireEvent.press(q.getByTestId("bulk-reschedule-apply")); });
  expect(mockPost).toHaveBeenCalledWith("/jobs/bulk-update", { ids: ["j1", "j2"], patch: { scheduled_date: "2026-11-04" } });
  expect(mockToast).toHaveBeenCalledWith("Rescheduled 2 jobs to Wed, Nov 4, 2026", "success");
});

it("L6 · Delete: destructive confirm w/ web locked copy; cancel = no call; confirm → bulk-delete, deleted rows removed, locked row stays", async () => {
  mockPost.mockResolvedValue({ ok: true, deleted_count: 1, deleted: ["j1"], failed: [{ id: "j2", reason: "Completed with invoice" }] });
  const q = await mount();
  await pickTwo(q);
  fireEvent.press(q.getByTestId("bulk-action-delete"));
  const opts = mockConfirm.mock.calls[0][0];
  expect(opts).toMatchObject({
    title: "Delete 2 jobs?", confirmLabel: "Delete 2", confirmStyle: "destructive",
    message: "Locked jobs (active timers or completed with an invoice) will be skipped.",
  });
  expect(mockPost).not.toHaveBeenCalled(); // not confirmed yet (= cancel path)
  await act(async () => { await opts.onConfirm(); });
  expect(mockPost).toHaveBeenCalledWith("/jobs/bulk-delete", { ids: ["j1", "j2"] });
  expect(q.queryByTestId("job-row-j1")).toBeNull();
  expect(q.getByTestId("job-row-j2")).toBeTruthy();
  expect(mockToast).toHaveBeenCalledWith("1 job deleted · 1 locked — Completed with invoice", "info");
});

it("L7 · request error → error toast; selection kept for retry", async () => {
  mockPost.mockRejectedValue(new Error("Network down"));
  const q = await mount();
  await pickTwo(q);
  fireEvent.press(q.getByTestId("bulk-action-status"));
  await act(async () => { fireEvent.press(q.getByTestId("bulk-status-option-active")); });
  expect(mockToast).toHaveBeenCalledWith("Network down", "error");
  expect(q.getByTestId("bulk-action-bar-count").props.children).toEqual([2, " selected"]);
});

it("L8 · manager / tech → redirect (screen stays admin/super_admin only)", async () => {
  for (const role of ["manager", "pool_tech"]) {
    mockRole = role;
    const q = render(<AdminJobsList />);
    expect(q.getByTestId("redirect").props.children).toBe("/(app)");
    expect(q.queryByTestId("jobs-select-toggle")).toBeNull();
    q.unmount();
  }
});
