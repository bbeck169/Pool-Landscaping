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
  useAuth: () => ({ user: { id: "u1", role: "admin", email: "a@t" } }),
  AuthProvider: ({ children }) => <>{children}</>,
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ can: () => true, isAdmin: true }),
  useCan: () => true,
  Gate: ({ children }) => <>{children}</>,
}));

vi.mock("@/hooks/useClockInGate", () => ({
  useClockInGate: () => ({ openJob: (_id, cb) => cb?.() }),
  ClockInGateDialog: () => null,
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
