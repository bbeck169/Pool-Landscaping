/**
 * M3b commit 2 · Mark as Open on MISSED cards (web Ticket X parity).
 * Behaviour via a stateful harness + the real ToastProvider (Undo is pressable);
 * calendar.tsx wiring pinned by source lock (no screen render harness — baseline).
 */
import React from "react";
import fs from "fs";
import path from "path";
import { Text } from "react-native";
import { render, fireEvent, act, waitFor } from "@testing-library/react-native";

const mockPost = jest.fn();
const mockPut = jest.fn();
const mockGet = jest.fn();
jest.mock("@/src/api", () => ({ api: {
  post: (...a: any[]) => mockPost(...a), put: (...a: any[]) => mockPut(...a), get: (...a: any[]) => mockGet(...a) } }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));

import { ToastProvider } from "@/src/components/ToastProvider";
import MarkOpenButton, { formatMarkOpenError, isMissedJob } from "@/src/components/schedule/MarkOpenButton";

const MISSED = { id: "j1", status: "missed", missed_at: "2026-10-25T18:00:00Z", customer_name: "Acme Pools", service_type: "Weekly Pool" };
function Harness({ initial }: { initial: any }) {
  const [job, setJob] = React.useState(initial);
  return (
    <ToastProvider>
      <Text testID="status">{job.status}</Text>
      <Text testID="reopened">{job.reopened_from_missed_at || ""}</Text>
      <MarkOpenButton job={job} onPatch={(p) => setJob((j: any) => ({ ...j, ...p }))} />
    </ToastProvider>
  );
}
const deferred = () => { let resolve: any, reject: any; const p = new Promise((a, b) => { resolve = a; reject = b; }); return { p, resolve, reject }; };
const status = (q: any) => q.getByTestId("status").props.children;
const toast = (q: any) => q.queryByTestId("toast-text")?.props.children;
const SRC = fs.readFileSync(path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf8");

beforeEach(() => { jest.useFakeTimers(); [mockPost, mockPut, mockGet].forEach((m) => m.mockReset()); });
afterEach(() => { jest.clearAllTimers(); jest.useRealTimers(); }); // toast auto-dismiss timers

it("X1 · visible ONLY on missed cards (case-insensitive)", () => {
  for (const s of ["scheduled", "completed", "could_not_service", "", undefined]) {
    const q = render(<Harness initial={{ ...MISSED, status: s }} />);
    expect(q.queryByTestId("mark-open-btn-j1")).toBeNull();
    q.unmount();
  }
  expect(isMissedJob({ status: "MISSED" })).toBe(true);
  expect(render(<Harness initial={MISSED} />).getByTestId("mark-open-btn-j1")).toBeTruthy();
});

it("X2 · optimistic flip before the network returns; POST /jobs/{id}/mark-open {}; reconcile with server row; success toast with Undo", async () => {
  const d = deferred();
  mockPost.mockReturnValueOnce(d.p);
  const q = render(<Harness initial={MISSED} />);
  fireEvent.press(q.getByTestId("mark-open-btn-j1"));
  expect(status(q)).toBe("scheduled"); // optimistic
  expect(mockPost).toHaveBeenCalledWith("/jobs/j1/mark-open", {});
  await act(async () => { d.resolve({ id: "j1", status: "scheduled", missed_at: null, reopened_from_missed_at: "2026-10-26T08:00:00Z" }); });
  expect(q.getByTestId("reopened").props.children).toBe("2026-10-26T08:00:00Z");
  expect(toast(q)).toBe("Marked as Open · Acme Pools");
  expect(q.getByTestId("toast-action")).toBeTruthy();
});

it("X3 · Undo → card back to missed + PUT /jobs/{id} {status:'missed', missed_at:<original>} + 'Mark-open undone'", async () => {
  mockPost.mockResolvedValueOnce({ id: "j1", status: "scheduled", missed_at: null });
  mockPut.mockResolvedValueOnce({ id: "j1", status: "missed" });
  const q = render(<Harness initial={MISSED} />);
  await act(async () => { fireEvent.press(q.getByTestId("mark-open-btn-j1")); });
  await act(async () => { fireEvent.press(q.getByTestId("toast-action")); });
  expect(status(q)).toBe("missed");
  expect(mockPut).toHaveBeenCalledWith("/jobs/j1", { status: "missed", missed_at: "2026-10-25T18:00:00Z" });
  await waitFor(() => expect(toast(q)).toBe("Mark-open undone"));
  expect(q.getByTestId("mark-open-btn-j1")).toBeTruthy(); // button back on the missed card
});

it("X4 · 409 invalid_status_transition → rollback to missed + error toast with the server detail", async () => {
  mockPost.mockRejectedValueOnce(Object.assign(new Error("Conflict"), { status: 409, detail: { error: "invalid_status_transition", detail: "Job is no longer missed" } }));
  const q = render(<Harness initial={MISSED} />);
  await act(async () => { fireEvent.press(q.getByTestId("mark-open-btn-j1")); });
  expect(status(q)).toBe("missed");
  expect(toast(q)).toBe("Job is no longer missed");
  expect(q.queryByTestId("toast-action")).toBeNull();
});

it("X5 · 403 string detail / network error → rollback + readable message", async () => {
  mockPost.mockRejectedValueOnce(Object.assign(new Error("Forbidden"), { status: 403, detail: "Not allowed" }));
  const q = render(<Harness initial={MISSED} />);
  await act(async () => { fireEvent.press(q.getByTestId("mark-open-btn-j1")); });
  expect(status(q)).toBe("missed");
  expect(toast(q)).toBe("Not allowed");
  mockPost.mockRejectedValueOnce(new Error("Network request failed"));
  await act(async () => { fireEvent.press(q.getByTestId("mark-open-btn-j1")); });
  expect(status(q)).toBe("missed");
  expect(toast(q)).toBe("Network request failed");
});

it("X6 · Undo failure → 'Undo failed: …' + GET /jobs/{id} reconciles to the server-of-record row", async () => {
  mockPost.mockResolvedValueOnce({ id: "j1", status: "scheduled", missed_at: null });
  mockPut.mockRejectedValueOnce(Object.assign(new Error("Forbidden"), { status: 403, detail: "Admins only" }));
  mockGet.mockResolvedValueOnce({ id: "j1", status: "scheduled" });
  const q = render(<Harness initial={MISSED} />);
  await act(async () => { fireEvent.press(q.getByTestId("mark-open-btn-j1")); });
  await act(async () => { fireEvent.press(q.getByTestId("toast-action")); });
  await waitFor(() => expect(toast(q)).toBe("Undo failed: Admins only"));
  expect(mockGet).toHaveBeenCalledWith("/jobs/j1");
  await waitFor(() => expect(status(q)).toBe("scheduled"));
});

it("X7 · error-copy ladder mirrors web _formatErr", () => {
  expect(formatMarkOpenError({ detail: "plain" })).toBe("plain");
  expect(formatMarkOpenError({ detail: { detail: "nested" } })).toBe("nested");
  expect(formatMarkOpenError({ data: { detail: "data-detail" } })).toBe("data-detail");
  expect(formatMarkOpenError({ message: "msg" })).toBe("msg");
  expect(formatMarkOpenError({})).toBe("Failed to mark job open");
});

it("X8 · wiring lock: missed pill; button on Grid JobRow (both list paths) + Calendar cards; patchJobInPlace drives both", () => {
  expect(SRC).toContain('missed:     { bg: "#FEE2E2", fg: "#B91C1C", label: "Missed" },');
  expect(SRC.match(/<GridView\n\s+onPatchJob=\{patchJobInPlace\}/)).toBeTruthy();
  expect(SRC.match(/<CalendarView\n\s+onPatchJob=\{patchJobInPlace\}/)).toBeTruthy();
  expect(SRC.match(/onPatchJob=\{onPatchJob\}/g)).toHaveLength(2);
  expect(SRC).toContain("{onPatchJob ? <MarkOpenButton job={job} onPatch={onPatchJob} /> : null}");
  expect(SRC).toContain('{onPatchJob ? <MarkOpenButton job={j} onPatch={onPatchJob} size="xs" /> : null}');
});
