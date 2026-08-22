/**
 * Feb-2026 · P37b.1 — OpsHub JobTimers start-method filter chip.
 *
 * Three chips (All / Auto / Manual) filter the active-timers list
 * client-side by ``timer_start_method``. "Auto" = ``gps_arrival``;
 * "Manual" = everything else (including null / undefined / legacy
 * pre-P37 rows started via the manual UI).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: "admin", effectiveRole: "admin",
    isAdmin: true, isAdminOrManager: true, canDo: () => true,
  }),
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin", tenant_id: "t1",
                                  name: "Admin", email: "a@x.com" } }),
  AuthProvider: ({ children }) => children,
}));

const mockGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), warning: vi.fn(),
  }),
}));


import OpsHub from "@/pages/ops/OpsHub";


// 3 auto + 2 manual + 1 null (legacy).
const ROWS = [
  { id: "j-a1", title: "Auto 1", technician_name: "T1",
    status: "active", timer_started_at: "2026-06-01T10:00:00Z",
    timer_start_method: "gps_arrival" },
  { id: "j-a2", title: "Auto 2", technician_name: "T2",
    status: "active", timer_started_at: "2026-06-01T10:05:00Z",
    timer_start_method: "gps_arrival" },
  { id: "j-a3", title: "Auto 3", technician_name: "T3",
    status: "active", timer_started_at: "2026-06-01T10:10:00Z",
    timer_start_method: "gps_arrival" },
  { id: "j-m1", title: "Manual 1", technician_name: "T4",
    status: "active", timer_started_at: "2026-06-01T10:15:00Z",
    timer_start_method: "manual" },
  { id: "j-m2", title: "Manual 2", technician_name: "T5",
    status: "active", timer_started_at: "2026-06-01T10:20:00Z",
    timer_start_method: "manual" },
  { id: "j-null", title: "Legacy", technician_name: "T6",
    status: "active", timer_started_at: "2026-06-01T10:25:00Z" },
];


function _installRouter() {
  mockGet.mockImplementation((path) => {
    const p = typeof path === "string" ? path : "";
    if (p.startsWith("/jobs")) return Promise.resolve(ROWS);
    if (p.startsWith("/technicians")) return Promise.resolve([]);
    if (p.startsWith("/crews")) return Promise.resolve([]);
    return Promise.resolve([]);
  });
}


function _mount() {
  return render(
    <MemoryRouter initialEntries={["/ops?t=timers"]}>
      <OpsHub />
    </MemoryRouter>,
  );
}


function _visibleTimerRows() {
  return screen.queryAllByTestId(/^job-timer-row-/);
}


beforeEach(() => {
  mockGet.mockReset();
  _installRouter();
});


describe("OpsHub · JobTimers · P37b.1 start-method filter chip", () => {
  it("renders 3 filter chips (All / Auto / Manual)", async () => {
    _mount();
    await waitFor(() =>
      expect(screen.getByTestId("job-timer-filter-all")).toBeTruthy());
    expect(screen.getByTestId("job-timer-filter-auto")).toBeTruthy();
    expect(screen.getByTestId("job-timer-filter-manual")).toBeTruthy();
  });

  it("default is All — shows all 6 rows", async () => {
    _mount();
    await waitFor(() => expect(_visibleTimerRows().length).toBe(6));
  });

  it("clicking Auto shows only 3 rows (gps_arrival)", async () => {
    _mount();
    await waitFor(() => expect(_visibleTimerRows().length).toBe(6));
    fireEvent.click(screen.getByTestId("job-timer-filter-auto"));
    await waitFor(() => expect(_visibleTimerRows().length).toBe(3));
    // All 3 must be the auto rows.
    for (const id of ["j-a1", "j-a2", "j-a3"]) {
      expect(screen.getByTestId(`job-timer-row-${id}`)).toBeTruthy();
    }
    // No manual / legacy rows leaked.
    expect(screen.queryByTestId("job-timer-row-j-m1")).toBeNull();
    expect(screen.queryByTestId("job-timer-row-j-null")).toBeNull();
  });

  it("clicking Manual shows 3 rows (2 explicit manual + 1 null)", async () => {
    _mount();
    await waitFor(() => expect(_visibleTimerRows().length).toBe(6));
    fireEvent.click(screen.getByTestId("job-timer-filter-manual"));
    await waitFor(() => expect(_visibleTimerRows().length).toBe(3));
    // Explicit manual + null legacy row present; gps_arrival absent.
    expect(screen.getByTestId("job-timer-row-j-m1")).toBeTruthy();
    expect(screen.getByTestId("job-timer-row-j-m2")).toBeTruthy();
    expect(screen.getByTestId("job-timer-row-j-null")).toBeTruthy();
    expect(screen.queryByTestId("job-timer-row-j-a1")).toBeNull();
  });

  it("clicking All (after a filter) restores all 6 rows", async () => {
    _mount();
    await waitFor(() => expect(_visibleTimerRows().length).toBe(6));
    fireEvent.click(screen.getByTestId("job-timer-filter-auto"));
    await waitFor(() => expect(_visibleTimerRows().length).toBe(3));
    fireEvent.click(screen.getByTestId("job-timer-filter-all"));
    await waitFor(() => expect(_visibleTimerRows().length).toBe(6));
  });
});
