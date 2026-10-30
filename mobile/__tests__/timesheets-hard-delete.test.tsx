/**
 * Ticket 2 FE · admin Timesheets per-row hard delete
 * (BE f16ffc940 · DELETE /attendance/timesheets/{id}?reason=...).
 */
import React from "react";
import { Alert } from "react-native";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

let mockRole = "admin";
const mockGet = jest.fn();
const mockDel = jest.fn();
const mockToast = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (...a: any[]) => mockGet(...a), del: (...a: any[]) => mockDel(...a) } }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: mockRole } }) }));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));
jest.mock("@/src/utils/exportCsv", () => ({ exportCsv: jest.fn(), toCsvRow: () => "" }));
jest.mock("@/src/components/widgets", () => {
  const { View } = jest.requireActual("react-native");
  return { Header: ({ right }: any) => <View>{right}</View>, IconButton: () => null };
});
jest.mock("expo-router", () => {
  const React = jest.requireActual("react");
  return { useFocusEffect: (cb: any) => React.useEffect(cb, [cb]) };
});

import Timesheets from "@/app/timesheets";

const ROWS = [
  { id: "r1", date: "2026-10-20", technician_name: "Mike", hours: 8, clock_in_at: null, clock_out_at: null },
  { id: "r2", date: "2026-10-21", technician_name: "Mike", hours: 6.5, clock_in_at: null, clock_out_at: null },
];

// Non-empty: the screen only fetches /technicians while `techs` is empty.
const TECHS = [{ id: "t1", name: "Mike" }];

beforeEach(() => {
  mockRole = "admin";
  mockGet.mockReset(); mockDel.mockReset(); mockToast.mockReset();
  mockGet.mockImplementation(async (p: string) => (p.startsWith("/attendance/report") ? { rows: ROWS.map((r) => ({ ...r })), total_hours: 14.5 } : TECHS));
  jest.spyOn(Alert, "alert").mockImplementation(() => {});
});
afterEach(() => jest.restoreAllMocks());

async function mount() {
  const q = render(<Timesheets />);
  await waitFor(() => q.getByTestId("timesheets-list"));
  return q;
}
async function openReason(q: any, id = "r1") {
  fireEvent.press(q.getByTestId(`timesheet-delete-${id}`));
  const buttons = (Alert.alert as jest.Mock).mock.calls[0][2];
  await act(async () => { buttons.find((b: any) => b.text === "Delete").onPress(); });
  return q.getByTestId("timesheet-delete-reason-modal");
}

describe("Timesheets · per-row hard delete", () => {
  it("1 · non-admin roles → no delete buttons", async () => {
    for (const role of ["technician", "manager", "owner"]) {
      mockRole = role;
      const q = await mount();
      expect(q.queryByTestId("timesheet-delete-r1")).toBeNull();
      expect(q.queryByTestId("timesheet-delete-r2")).toBeNull();
      q.unmount();
    }
  });

  it("2 · admin + super_admin → delete button on every row", async () => {
    for (const role of ["admin", "super_admin"]) {
      mockRole = role;
      const q = await mount();
      expect(q.getByTestId("timesheet-delete-r1")).toBeTruthy();
      expect(q.getByTestId("timesheet-delete-r2")).toBeTruthy();
      q.unmount();
    }
  });

  it("3 · tap → Alert.alert with title, message, Cancel + destructive Delete", async () => {
    const q = await mount();
    fireEvent.press(q.getByTestId("timesheet-delete-r1"));
    const [title, msg, buttons] = (Alert.alert as jest.Mock).mock.calls[0];
    expect(title).toBe("Delete timecard?");
    expect(msg).toBe("This cannot be undone. The row will be removed permanently.");
    expect(buttons.map((b: any) => [b.text, b.style])).toEqual([["Cancel", "cancel"], ["Delete", "destructive"]]);
    expect(q.queryByTestId("timesheet-delete-reason-modal")).toBeNull();
    expect(mockDel).not.toHaveBeenCalled();
  });

  it("4 · confirm → reason prompt; submit disabled until trimmed reason ≥ 3 chars", async () => {
    const q = await mount();
    await openReason(q);
    const submit = () => q.getByTestId("timesheet-delete-reason-submit");
    expect(submit().props.accessibilityState.disabled).toBe(true);
    fireEvent.changeText(q.getByTestId("timesheet-delete-reason-input"), "  ab  ");
    expect(submit().props.accessibilityState.disabled).toBe(true);
    fireEvent.press(submit());
    expect(mockDel).not.toHaveBeenCalled();
    fireEvent.changeText(q.getByTestId("timesheet-delete-reason-input"), "dup");
    expect(submit().props.accessibilityState.disabled).toBe(false);
  });

  it("5 · BE 400 reason_required → error shown, prompt stays open, row kept", async () => {
    mockDel.mockRejectedValueOnce(Object.assign(new Error("400"), { status: 400, detail: { code: "reason_required", msg: "A reason of at least 3 characters is required." } }));
    const q = await mount();
    await openReason(q);
    fireEvent.changeText(q.getByTestId("timesheet-delete-reason-input"), "abc");
    await act(async () => { fireEvent.press(q.getByTestId("timesheet-delete-reason-submit")); });
    await waitFor(() => q.getByTestId("timesheet-delete-reason-error"));
    expect(q.getByTestId("timesheet-delete-reason-error").props.children).toBe("A reason of at least 3 characters is required.");
    expect(q.getByTestId("timesheet-delete-reason-modal")).toBeTruthy();
    expect(q.getByTestId("timesheet-r1")).toBeTruthy();
  });

  it("6 · success → DELETE with encoded reason, row removed, toast, refetch", async () => {
    mockDel.mockResolvedValueOnce({ ok: true });
    const q = await mount();
    const reportCalls = () => mockGet.mock.calls.filter(([p]) => p.startsWith("/attendance/report")).length;
    const before = reportCalls();
    await openReason(q);
    fireEvent.changeText(q.getByTestId("timesheet-delete-reason-input"), "duplicate entry & typo");
    mockGet.mockImplementation(async (p: string) => (p.startsWith("/attendance/report") ? { rows: [{ ...ROWS[1] }], total_hours: 6.5 } : TECHS));
    await act(async () => { fireEvent.press(q.getByTestId("timesheet-delete-reason-submit")); });
    expect(mockDel).toHaveBeenCalledWith("/attendance/timesheets/r1?reason=duplicate%20entry%20%26%20typo");
    await waitFor(() => expect(q.queryByTestId("timesheet-r1")).toBeNull());
    expect(q.getByTestId("timesheet-r2")).toBeTruthy();
    expect(q.queryByTestId("timesheet-delete-reason-modal")).toBeNull();
    expect(mockToast).toHaveBeenCalledWith("Timecard deleted", "success");
    await waitFor(() => expect(reportCalls()).toBeGreaterThan(before));
  });

  it("7 · BE 403 → error toast, row remains", async () => {
    mockDel.mockRejectedValueOnce(Object.assign(new Error("Forbidden"), { status: 403, detail: "Admin only" }));
    const q = await mount();
    await openReason(q);
    fireEvent.changeText(q.getByTestId("timesheet-delete-reason-input"), "cleanup");
    await act(async () => { fireEvent.press(q.getByTestId("timesheet-delete-reason-submit")); });
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith("Admin only", "error"));
    expect(q.getByTestId("timesheet-r1")).toBeTruthy();
    expect(mockToast).not.toHaveBeenCalledWith("Timecard deleted", "success");
  });

  it("Cancel on the reason prompt closes it without calling the BE", async () => {
    const q = await mount();
    await openReason(q);
    fireEvent.press(q.getByTestId("timesheet-delete-reason-cancel"));
    expect(q.queryByTestId("timesheet-delete-reason-modal")).toBeNull();
    expect(mockDel).not.toHaveBeenCalled();
  });
});
