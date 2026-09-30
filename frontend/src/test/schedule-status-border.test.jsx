/**
 * Feb-2026 · Schedule-UI · status border + day-filter vitest.
 *
 * Covers the two additive changes to the Grid mode of
 * ``pages/schedule/CalendarSchedule.jsx``:
 *
 *   1. ``getStatusBorderColor(status)`` — the helper that decides the
 *      colored left border on each grid job card.
 *         completed  → red (#DC2626)
 *         anything-else / falsy → blue (#2563EB)
 *      The card renders with ``data-status-color=<hex>`` so tests can
 *      assert on the exact color without depending on Tailwind class
 *      resolution.
 *
 *   2. Day-of-week selection filters the visible job list. Three
 *      mock jobs across three different scheduled_date values; the
 *      grid must render only jobs for the currently-focused ISO.
 *
 * The Schedule page is heavy — this test mounts the ``GridPanel``
 * export path via the parent ``CalendarSchedule`` with mocked API
 * responses and asserts on the resulting DOM.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { getStatusBorderColor } from "@/pages/schedule/CalendarSchedule";


// Pin the clock so ``focusISO`` resolves deterministically.
const _FIXED = new Date(2026, 1, 11, 12, 0, 0);   // Wed 2026-02-11


// ─── shared mocks ────────────────────────────────────────────────────
const { apiGetMock, apiPostMock, apiPutMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPostMock: vi.fn(),
  apiPutMock:  vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { get: apiGetMock, post: apiPostMock, put: apiPutMock,
           patch: vi.fn(), del: vi.fn() },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

vi.mock("@/auth", () => ({
  useAuth: () => useAuthMock(),
  AuthProvider: ({ children }) => <>{children}</>,
}));

const { useAuthMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(() => ({
    user: { id: "u1", role: "admin", email: "a@t" },
  })),
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ can: () => true, isAdmin: true }),
  useCan: () => true,
  Gate: ({ children }) => <>{children}</>,
}));

vi.mock("@/hooks/useClockInGate", () => ({
  useClockInGate: () => ({ openJob: (_id, cb) => cb?.() }),
  ClockInGateDialog: () => null,
  // Feb-2026 · Landscaper clock-in gate follow-up — ``<OnMyWayButton>``
  // now consumes ``useClockInStatus`` too.  Stub returns the "not
  // gated / clocked in" shape so the button renders enabled for
  // every existing test in this file (they all mount as admin).
  useClockInStatus: () => ({
    isGated: false, isClockedIn: true, isChecking: false, refresh: () => {},
  }),
  __resetClockInStatusCacheForTests: () => {},
}));

vi.mock("@/components/Weather/WeatherWidget", () => ({
  __esModule: true, default: () => null,
}));
vi.mock("@/components/Weather/JobRainFlag", () => ({
  __esModule: true, default: () => null,
}));
vi.mock("@/components/checklist/ChecklistModal", () => ({
  __esModule: true, default: () => null,
}));
vi.mock("@/components/schedule/ServiceNotePill", () => ({
  __esModule: true, default: () => null,
}));

// react-big-calendar is heavy + rendered lazily under a different
// tab — stub it entirely so the grid path is exercised in isolation.
vi.mock("react-big-calendar", () => ({
  __esModule: true,
  Calendar: () => null,
  dateFnsLocalizer: () => ({}),
}));
vi.mock("react-big-calendar/lib/addons/dragAndDrop", () => ({
  __esModule: true, default: (Cmp) => Cmp,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));


beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true }).setSystemTime(_FIXED);
  apiGetMock.mockReset();
  apiPostMock.mockReset();
  apiPutMock.mockReset();
  // Default auth = admin. Individual tests can override via
  // ``useAuthMock.mockReturnValue(...)`` for the whole render.
  useAuthMock.mockReturnValue({
    user: { id: "u1", role: "admin", email: "a@t" },
  });
  window.sessionStorage.clear();
});
afterEach(() => { vi.useRealTimers(); cleanup(); });


const jobsFixture = [
  { id: "job-a", customer_name: "Alpha",  service_type: "Weekly",
     scheduled_date: "2026-02-11", status: "scheduled" },
  { id: "job-b", customer_name: "Bravo",  service_type: "Weekly",
     scheduled_date: "2026-02-11", status: "completed" },
  { id: "job-c", customer_name: "Charlie", service_type: "Weekly",
     scheduled_date: "2026-02-13", status: "scheduled" },
];


// ─── 1. getStatusBorderColor helper ──────────────────────────────────
describe("Schedule · getStatusBorderColor()", () => {
  it("returns red for completed jobs", () => {
    expect(getStatusBorderColor("completed")).toBe("#DC2626");
    expect(getStatusBorderColor("Completed")).toBe("#DC2626");
    expect(getStatusBorderColor("COMPLETED")).toBe("#DC2626");
  });
  it("returns blue for scheduled / open / anything-not-completed", () => {
    expect(getStatusBorderColor("scheduled")).toBe("#2563EB");
    expect(getStatusBorderColor("active")).toBe("#2563EB");
    expect(getStatusBorderColor("pending")).toBe("#2563EB");
    expect(getStatusBorderColor("requested")).toBe("#2563EB");
    expect(getStatusBorderColor("on_hold")).toBe("#2563EB");
    expect(getStatusBorderColor(undefined)).toBe("#2563EB");
    expect(getStatusBorderColor(null)).toBe("#2563EB");
    expect(getStatusBorderColor("")).toBe("#2563EB");
  });
});


// ─── 2. Full Schedule page — filter + status border ──────────────────
async function mountSchedule() {
  const { default: CalendarSchedule } = await import(
    "@/pages/schedule/CalendarSchedule");
  return render(
    <MemoryRouter initialEntries={["/schedule?mode=grid"]}>
      <CalendarSchedule />
    </MemoryRouter>,
  );
}


describe("Schedule · day-of-week filter + status border", () => {
  it("only shows jobs for the currently-selected day", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path.startsWith("/jobs")) return Promise.resolve(jobsFixture);
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve([]);
    });
    await mountSchedule();
    // Default focus is today (2026-02-11) — jobs A + B render, C does not.
    expect(await screen.findByTestId("grid-job-job-a")).toBeInTheDocument();
    expect(screen.getByTestId("grid-job-job-b")).toBeInTheDocument();
    expect(screen.queryByTestId("grid-job-job-c")).toBeNull();

    // Click Friday (2026-02-13) — job C appears, A + B disappear.
    fireEvent.click(await screen.findByTestId("week-strip-day-2026-02-13"));
    await waitFor(() => {
      expect(screen.getByTestId("grid-job-job-c")).toBeInTheDocument();
      expect(screen.queryByTestId("grid-job-job-a")).toBeNull();
      expect(screen.queryByTestId("grid-job-job-b")).toBeNull();
    });
  });

  it("renders blue left border for scheduled + red for completed", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path.startsWith("/jobs")) return Promise.resolve(jobsFixture);
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve([]);
    });
    await mountSchedule();

    const cardA = await screen.findByTestId("grid-job-job-a");
    const cardB = await screen.findByTestId("grid-job-job-b");
    // Scheduled → blue.
    expect(cardA.getAttribute("data-status-color")).toBe("#2563EB");
    // Completed → red.
    expect(cardB.getAttribute("data-status-color")).toBe("#DC2626");
    // Inline style contains the same left-border color (defense against
    // a future refactor that drops the data attribute).
    expect(cardA.style.borderLeftColor.toLowerCase().replace(/\s/g, "")).toBe("rgb(37,99,235)");
    expect(cardB.style.borderLeftColor.toLowerCase().replace(/\s/g, "")).toBe("rgb(220,38,38)");
  });
});


// ─── 3. Multi-select bulk soft-delete ─────────────────────────────────
describe("Schedule · multi-select bulk soft-delete", () => {
  it("does NOT render the selection checkbox for a tech role", async () => {
    // Override the shared auth mock for THIS render — resets to
    // admin in the next test's beforeEach.
    useAuthMock.mockReturnValue({
      user: { id: "u1", role: "technician", email: "t@t" },
    });
    apiGetMock.mockImplementation((path) => {
      if (path.startsWith("/jobs")) return Promise.resolve(jobsFixture);
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve([]);
    });
    await mountSchedule();
    // Card renders …
    expect(await screen.findByTestId("grid-job-job-a")).toBeInTheDocument();
    // … but the selection checkbox does NOT.
    expect(screen.queryByTestId("grid-select-job-a")).toBeNull();
    expect(screen.queryByTestId("grid-selection-toolbar")).toBeNull();
  });

  it("admin can toggle selection + toolbar shows the count", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path.startsWith("/jobs")) return Promise.resolve(jobsFixture);
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve([]);
    });
    await mountSchedule();
    // Both today-cards render — click their selection boxes.
    fireEvent.click(await screen.findByTestId("grid-select-job-a"));
    // Toolbar surfaces with count=1 …
    expect(await screen.findByTestId("grid-selection-toolbar")).toBeInTheDocument();
    expect(screen.getByTestId("grid-selection-count")).toHaveTextContent("1 selected");
    // Second select bumps to 2.
    fireEvent.click(screen.getByTestId("grid-select-job-b"));
    expect(screen.getByTestId("grid-selection-count")).toHaveTextContent("2 selected");
    // Deselect all → toolbar disappears.
    fireEvent.click(screen.getByTestId("grid-selection-clear"));
    await waitFor(() => {
      expect(screen.queryByTestId("grid-selection-toolbar")).toBeNull();
    });
  });

  it("delete flow POSTs /jobs/bulk-soft-delete with the selected ids", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path.startsWith("/jobs")) return Promise.resolve(jobsFixture);
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve([]);
    });
    apiPostMock.mockImplementation((path) => {
      if (path === "/jobs/bulk-soft-delete") {
        return Promise.resolve({ ok: true, count: 2,
                                   deleted: ["job-a","job-b"], failed: [] });
      }
      return Promise.resolve({});
    });
    await mountSchedule();
    fireEvent.click(await screen.findByTestId("grid-select-job-a"));
    fireEvent.click(await screen.findByTestId("grid-select-job-b"));
    // Click "Delete N" — opens the confirm modal.
    fireEvent.click(screen.getByTestId("grid-selection-delete"));
    expect(await screen.findByTestId("grid-bulk-delete-modal")).toBeInTheDocument();
    // Confirm.
    fireEvent.click(screen.getByTestId("grid-bulk-delete-confirm"));

    await waitFor(() => {
      const bulk = apiPostMock.mock.calls.find(([p]) => p === "/jobs/bulk-soft-delete");
      expect(bulk).toBeTruthy();
      expect(bulk[1]).toEqual({ job_ids: ["job-a", "job-b"] });
    });
    // Modal closes on success.
    await waitFor(() => {
      expect(screen.queryByTestId("grid-bulk-delete-modal")).toBeNull();
    });
  });

  it("cancel button closes the confirm modal without POSTing", async () => {
    apiGetMock.mockImplementation((path) => {
      if (path.startsWith("/jobs")) return Promise.resolve(jobsFixture);
      if (path === "/technicians") return Promise.resolve([]);
      return Promise.resolve([]);
    });
    await mountSchedule();
    fireEvent.click(await screen.findByTestId("grid-select-job-a"));
    fireEvent.click(screen.getByTestId("grid-selection-delete"));
    expect(await screen.findByTestId("grid-bulk-delete-modal")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("grid-bulk-delete-cancel"));
    await waitFor(() => {
      expect(screen.queryByTestId("grid-bulk-delete-modal")).toBeNull();
    });
    expect(apiPostMock.mock.calls.find(([p]) => p === "/jobs/bulk-soft-delete"))
      .toBeUndefined();
  });
});
