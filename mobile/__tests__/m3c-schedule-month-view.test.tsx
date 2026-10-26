/**
 * M3c · Schedule Month view (web Ticket W parity).
 * ScheduleMonthView is rendered for behaviour (cachedGet mocked to inspect the
 * fetch + cache options); calendar.tsx mode wiring is pinned by source lock
 * (no screen render harness — known baseline).
 */
import React from "react";
import fs from "fs";
import path from "path";
import { StyleSheet } from "react-native";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockCachedGet = jest.fn();
const mockWriteThroughJobs = jest.fn();
jest.mock("@/src/lib/offline/apiCache", () => ({
  cachedGet: (...a: any[]) => mockCachedGet(...a),
  readCachedWeekJobs: jest.fn(async () => []),
  writeThroughJobs: (...a: any[]) => mockWriteThroughJobs(...a),
}));
jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("@/src/components/schedule/MarkOpenButton", () => () => null);

import ScheduleMonthView from "@/src/components/schedule/ScheduleMonthView";
import { buildMonthGrid, monthBorderColor, filterMonthJobs, monthJobsUrl } from "@/src/lib/monthGrid";

const SRC = fs.readFileSync(path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf8");
const NOV = new Date(2026, 10, 10);
const job = (id: string, date: string, extra: any = {}) => ({ id, scheduled_date: date, service_type: `Svc ${id}`, customer_name: `Cust ${id}`, status: "scheduled", ...extra });
const mount = (jobs: any[], props: any = {}) => {
  mockCachedGet.mockResolvedValue(jobs);
  const onOpenJob = jest.fn(); const onOpenDay = jest.fn();
  const q = render(<ScheduleMonthView initialDate={NOV} scopeQuery="" clientFilter={(a) => a} userId="u1" onOpenJob={onOpenJob} onOpenDay={onOpenDay} {...props} />);
  return { q, onOpenJob, onOpenDay };
};
const flat = (n: any) => StyleSheet.flatten(n.props.style) || {};

beforeEach(() => { mockCachedGet.mockReset(); mockWriteThroughJobs.mockReset(); jest.useFakeTimers(); jest.setSystemTime(new Date(2026, 10, 10, 9)); });
afterEach(() => { jest.useRealTimers(); });

it("W1 · mode chip group: Calendar / Grid / Month with active state; Month persisted + restored", () => {
  expect(SRC).toContain('type Mode = "grid" | "calendar" | "month";');
  expect(SRC).toContain('{(["calendar", "grid", "month"] as const).map((m) => {');
  expect(SRC).toContain('{m === "grid" ? "Grid" : m === "month" ? "Month" : "Calendar"}');
  expect(SRC).toContain("style={[styles.modeBtn, active && styles.modeBtnActive]}");
  expect(SRC).toContain('if (saved === "grid" || saved === "calendar" || saved === "month") setMode(saved);');
  expect(SRC).toMatch(/\) : mode === "calendar" \? \(\n\s+<CalendarView/);
  expect(SRC).toMatch(/\) : \(\n\s+<ScheduleMonthView\n\s+initialDate=\{focus\}\n\s+scopeQuery=\{monthScopeQuery\}/);
});

it("W2 · Month fetches the widened grid range (≤42 days) with an explicit limit", async () => {
  mount([]);
  await waitFor(() => expect(mockCachedGet).toHaveBeenCalled());
  expect(mockCachedGet.mock.calls[0][0]).toBe("/jobs?start=2026-10-26&end=2026-12-06&limit=5000");
});

it("W3 · Month fetch result is NOT written to the offline cache (no writeThrough; read fallback only)", async () => {
  mount([job("a", "2026-11-10")]);
  await waitFor(() => expect(mockCachedGet).toHaveBeenCalled());
  const opts = mockCachedGet.mock.calls[0][1];
  expect(opts.writeThrough).toBeUndefined();
  expect(typeof opts.readCache).toBe("function");
  expect(mockWriteThroughJobs).not.toHaveBeenCalled();
});

it("W4 · Mon-start columns in order", () => {
  const { q } = mount([]);
  expect([0, 1, 2, 3, 4, 5, 6].map((i) => q.getByTestId(`month-dow-${i}`).props.children)).toEqual(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
});

it("W5 · fixtures: Nov 2026 = 6 rows (Oct 26 → Dec 6); Feb 2026 = 5 rows (Jan 26 → Mar 1); every row starts Monday", () => {
  const nov = buildMonthGrid(new Date(2026, 10, 1));
  expect(nov.weeks).toHaveLength(6); expect([nov.start, nov.end]).toEqual(["2026-10-26", "2026-12-06"]);
  const feb = buildMonthGrid(new Date(2026, 1, 1));
  expect(feb.weeks).toHaveLength(5); expect([feb.start, feb.end]).toEqual(["2026-01-26", "2026-03-01"]);
  for (const w of [...nov.weeks, ...feb.weeks]) expect(w[0].getDay()).toBe(1);
  const { q } = mount([]);
  expect(q.getByTestId("month-week-5")).toBeTruthy();
  expect(q.queryByTestId("month-week-6")).toBeNull();
});

it("W6 · day cell renders two-line cards (job name + customer name); today highlighted; adjacent-month cells muted", async () => {
  const { q } = mount([job("a", "2026-11-10"), job("b", "2026-11-10", { customer_name: "" })]);
  await waitFor(() => expect(q.getByTestId("month-card-a")).toBeTruthy());
  expect(q.getByTestId("month-card-a-jobname").props.children).toBe("Svc a");
  expect(q.getByTestId("month-card-a-customername").props.children).toBe("Cust a");
  expect(q.getByTestId("month-card-b-customername").props.children).toBe("—");
  expect(flat(q.getByTestId("month-day-num-2026-11-10")).backgroundColor).toBeTruthy(); // today accent
  expect(flat(q.getByTestId("month-day-num-2026-11-11")).backgroundColor).toBeUndefined();
  expect(flat(q.getByTestId("month-cell-2026-10-26")).backgroundColor).not.toBe(flat(q.getByTestId("month-cell-2026-11-02")).backgroundColor);
});

it("W7 · status-colour left border (web STATUS_COLORS; unknown → #64748B)", async () => {
  const { q } = mount([job("s", "2026-11-03"), job("m", "2026-11-04", { status: "MISSED" }), job("x", "2026-11-05", { status: "weird" })]);
  await waitFor(() => expect(q.getByTestId("month-card-s")).toBeTruthy());
  expect(flat(q.getByTestId("month-card-s"))).toMatchObject({ borderLeftWidth: 3, borderLeftColor: "#0EA5E9" });
  expect(flat(q.getByTestId("month-card-m")).borderLeftColor).toBe("#B91C1C");
  expect(flat(q.getByTestId("month-card-x")).borderLeftColor).toBe("#64748B");
  expect(monthBorderColor(undefined)).toBe("#0EA5E9");
});

it("W8 · '+N more' only when > 3 visits; tap opens the sheet listing ALL visits; close dismisses", async () => {
  const five = ["1", "2", "3", "4", "5"].map((i) => job(`d${i}`, "2026-11-12"));
  const { q } = mount([...five, job("e1", "2026-11-13"), job("e2", "2026-11-13"), job("e3", "2026-11-13")]);
  await waitFor(() => expect(q.getByTestId("month-more-pill-2026-11-12")).toBeTruthy());
  expect(q.getByText("+2 more")).toBeTruthy();
  expect(q.queryByTestId("month-card-d4")).toBeNull(); // preview capped at 3
  expect(q.queryByTestId("month-more-pill-2026-11-13")).toBeNull(); // exactly 3 → no pill
  fireEvent.press(q.getByTestId("month-more-pill-2026-11-12"));
  for (const j of five) expect(q.getByTestId(`month-sheet-row-${j.id}`)).toBeTruthy();
  fireEvent.press(q.getByTestId("month-day-sheet-close"));
  expect(q.queryByTestId("month-sheet-row-d1")).toBeNull();
});

it("W9 · category filter composes: calendar passes the same crew/tech/category scope; scope change refetches", async () => {
  expect(SRC).toContain("const monthScopeQuery = `${!isTech && crewFilter ? `&crew_id=${crewFilter}` : \"\"}${isTech && resolvedTechId ? `&technician_id=${resolvedTechId}` : \"\"}${serviceCategoryParam(serviceCategory)}`;");
  expect(monthJobsUrl(NOV, "&crew_id=c1&service_category=pool")).toBe("/jobs?start=2026-10-26&end=2026-12-06&limit=5000&crew_id=c1&service_category=pool");
  mockCachedGet.mockResolvedValue([]);
  const p = { initialDate: NOV, clientFilter: (a: any[]) => a, userId: "u1", onOpenJob: jest.fn() };
  const q = render(<ScheduleMonthView {...p} scopeQuery="" />);
  await waitFor(() => expect(mockCachedGet).toHaveBeenCalledTimes(1));
  q.rerender(<ScheduleMonthView {...p} scopeQuery="&service_category=landscaping" />);
  await waitFor(() => expect(mockCachedGet).toHaveBeenCalledTimes(2));
  expect(mockCachedGet.mock.calls[1][0]).toBe("/jobs?start=2026-10-26&end=2026-12-06&limit=5000&service_category=landscaping");
});

it("W10 · card tap + sheet-row tap fire the existing job-detail handler; day number → onOpenDay", async () => {
  const four = ["1", "2", "3", "4"].map((i) => job(`t${i}`, "2026-11-20"));
  const { q, onOpenJob, onOpenDay } = mount(four);
  await waitFor(() => expect(q.getByTestId("month-card-t1")).toBeTruthy());
  fireEvent.press(q.getByTestId("month-card-t1"));
  expect(onOpenJob).toHaveBeenCalledWith("t1");
  fireEvent.press(q.getByTestId("month-more-pill-2026-11-20"));
  fireEvent.press(q.getByTestId("month-sheet-row-t4"));
  expect(onOpenJob).toHaveBeenLastCalledWith("t4");
  expect(q.queryByTestId("month-sheet-row-t4")).toBeNull();
  fireEvent.press(q.getByTestId("month-day-num-2026-11-20"));
  expect(onOpenDay.mock.calls[0][0].getDate()).toBe(20);
  expect(SRC).toContain('onOpenJob={(id) => router.push(`/job/${id}/checklist` as any)}\n          onOpenDay={(d) => { setFocus(d); setModePersist("grid"); }}');
});

it("W11 · prev/next month re-fetch the new grid range; client filter (tech / hide cancelled) applied", async () => {
  const { q } = mount([job("c", "2026-11-04", { status: "cancelled" }), job("k", "2026-11-04")], { clientFilter: (a: any[]) => filterMonthJobs(a, { isTech: false, techFilter: "all", showCancelled: false }) });
  await waitFor(() => expect(q.getByTestId("month-card-k")).toBeTruthy());
  expect(q.queryByTestId("month-card-c")).toBeNull();
  await act(async () => { fireEvent.press(q.getByTestId("month-next")); });
  expect(mockCachedGet.mock.calls.at(-1)[0]).toBe("/jobs?start=2026-11-30&end=2027-01-03&limit=5000");
  expect(filterMonthJobs([{ technician_id: "x" }, {}], { isTech: true, techFilter: "all", resolvedTechId: null, showCancelled: true })).toEqual([]);
});
