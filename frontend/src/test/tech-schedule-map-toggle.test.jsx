/**
 * Feb-2026 · Tech Today Schedule — List | Map sub-mode toggle.
 *
 * Verifies the Phase A wiring on ``TodaySchedule.jsx``:
 *
 *   1. Default mode is "list"; ``ScheduleMap`` is NOT mounted.
 *   2. Clicking the "Map" pill mounts ``ScheduleMap`` and hides the list.
 *   3. Clicking back to "List" restores the list and unmounts the map.
 *   4. Empty-state: when the tech's day has zero geocoded stops, the
 *      map surface renders the fallback "No mappable stops today"
 *      card, NOT the ScheduleMap.
 *   5. Mapping mode persists to localStorage.
 *
 * The ScheduleMap component itself is heavily Google-dependent
 * (@vis.gl/react-google-maps), so we mock it at the module edge to
 * assert the mount + prop shape without loading the Maps SDK.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// ── Mocks (declared BEFORE component import) ────────────────────

// `api` is the only backend surface TodaySchedule hits on mount.
const __apiStubs = {
  get: vi.fn(),
  post: vi.fn(),
};
vi.mock("@/api", () => ({
  api: {
    get: (...a) => __apiStubs.get(...a),
    post: (...a) => __apiStubs.post(...a),
    del: async () => ({}),
  },
  TOKEN_KEY: "auth_token",
}));

// Auth — flip role between tests via mockAuthUser.
const mockAuthUser = { id: "u_tech", role: "technician",
                        display_color_hex: "#f97316",
                        technician_id: "t_1" };
vi.mock("@/auth", () => ({ useAuth: () => ({ user: mockAuthUser }) }));

// ScheduleMap — spy on mount + verify pin count via the passed jobs.
const scheduleMapSpy = vi.fn();
vi.mock("@/pages/schedule/ScheduleMap", () => ({
  __esModule: true,
  default: (props) => {
    scheduleMapSpy(props);
    const geo = (props.jobs || []).filter((j) => {
      const lat = Number(j?.location_lat ?? j?.lat);
      const lng = Number(j?.location_lng ?? j?.lng);
      return Number.isFinite(lat) && Number.isFinite(lng)
             && !(lat === 0 && lng === 0);
    });
    return (
      <div data-testid="__mock-schedule-map">
        <span data-testid="__mock-pin-count">{geo.length}</span>
        {geo.map((j) => (
          <button key={j.id} data-testid={`__mock-schedule-map-pin-${j.id}`}>
            <span data-testid={`__mock-schedule-map-info-customer-${j.id}`}>
              {j.customer_name}
            </span>
            <span data-testid={`__mock-schedule-map-info-address-${j.id}`}>
              {j.address}
            </span>
          </button>
        ))}
      </div>
    );
  },
}));

// @react-google-maps/api's useJsApiLoader — TodaySchedule pulls it in
// for the Distance Matrix badges. Stub to avoid Google SDK load.
vi.mock("@react-google-maps/api", () => ({
  useJsApiLoader: () => ({ isLoaded: false, loadError: null }),
}));

// BulkReorderModal + OnMyWayButton + child chips are irrelevant to the
// toggle assertions — stub for speed.
vi.mock("@/pages/schedule/NumberedReorder", () => ({
  BulkReorderModal: () => null,
}));
vi.mock("@/components/schedule/OnMyWayButton", () => ({
  __esModule: true, default: () => null,
}));
vi.mock("@/components/schedule/ServiceNotePill", () => ({
  __esModule: true, default: () => null,
}));
vi.mock("@/components/schedule/JobNotesCallout", () => ({
  __esModule: true, default: () => null,
}));

// Component under test — imported AFTER mocks.
import TodaySchedule from "@/pages/schedule/TodaySchedule";

// ── Fixtures ────────────────────────────────────────────────────

const TZ = "America/Phoenix";
const TODAY = new Date().toISOString().slice(0, 10);

const _mkJob = (id, over = {}) => ({
  id, type: "job",
  title: `Service ${id}`,
  customer_name: `Customer ${id}`,
  address: `${id} Main St`,
  status: "scheduled",
  scheduled_start: `${TODAY}T09:00:00+00:00`,
  scheduled_end:   `${TODAY}T10:00:00+00:00`,
  location_lat: 33.45,
  location_lng: -112.07,
  ...over,
});

const _DAY_WITH_GEO = {
  date: TODAY, tz: TZ,
  summary: { job_count: 3, scheduled_hours: 6, clocked_in: false,
              miles_logged_today: 0, hours_logged_today: 0 },
  items: [
    _mkJob("j1", { customer_name: "Alice", address: "1 Palm Ln",
                    location_lat: 33.45, location_lng: -112.07 }),
    _mkJob("j2", { customer_name: "Bob", address: "2 Oak St",
                    location_lat: 33.46, location_lng: -112.08 }),
    _mkJob("j3", { customer_name: "Carol", address: "3 Elm Dr",
                    location_lat: 33.47, location_lng: -112.09 }),
  ],
  route_legs: [],
};

const _DAY_ZERO_GEO = {
  date: TODAY, tz: TZ,
  summary: { job_count: 2, scheduled_hours: 4, clocked_in: false,
              miles_logged_today: 0, hours_logged_today: 0 },
  items: [
    // No location_lat/lng — legacy customer without geocode.
    _mkJob("j1", { location_lat: null, location_lng: null }),
    _mkJob("j2", { location_lat: 0, location_lng: 0 }),  // placeholder
  ],
  route_legs: [],
};

async function mountWith(dayPayload) {
  __apiStubs.get.mockImplementation(async (path) => {
    if (String(path).startsWith("/schedule/today")) return dayPayload;
    return {};
  });
  const view = render(
    <MemoryRouter>
      <TodaySchedule />
    </MemoryRouter>,
  );
  // Let the initial /schedule/today fetch settle.
  await waitFor(() => expect(__apiStubs.get).toHaveBeenCalled());
  await act(async () => { await Promise.resolve(); });
  return view;
}

beforeEach(() => {
  __apiStubs.get.mockReset();
  __apiStubs.post.mockReset();
  scheduleMapSpy.mockReset();
  try { localStorage.clear(); } catch {}
  mockAuthUser.role = "technician";
});

// ═══════════════════════════════════════════════════════════════════
describe("TodaySchedule · List | Map sub-mode toggle", () => {
  it("defaults to List mode; ScheduleMap is NOT mounted", async () => {
    await mountWith(_DAY_WITH_GEO);
    // Toggle rendered.
    expect(screen.getByTestId("schedule-sub-mode-toggle")).toBeTruthy();
    // List button reflects the active state.
    expect(screen.getByTestId("schedule-sub-mode-list")).toBeTruthy();
    expect(screen.getByTestId("schedule-sub-mode-map")).toBeTruthy();
    // ScheduleMap NOT mounted by default.
    expect(screen.queryByTestId("__mock-schedule-map")).toBeNull();
    expect(scheduleMapSpy).not.toHaveBeenCalled();
    // Underlying list IS visible.
    expect(screen.getByTestId("schedule-card-list")).toBeTruthy();
  });

  it("clicking Map mounts ScheduleMap with the tech's geocoded jobs, hides the list", async () => {
    await mountWith(_DAY_WITH_GEO);
    await act(async () => {
      fireEvent.click(screen.getByTestId("schedule-sub-mode-map"));
    });
    // Map surface rendered, list gone.
    expect(screen.getByTestId("__mock-schedule-map")).toBeTruthy();
    expect(screen.queryByTestId("schedule-card-list")).toBeNull();
    // Prop shape — three geocoded pins, techColorMap contains self color.
    expect(scheduleMapSpy).toHaveBeenCalled();
    const props = scheduleMapSpy.mock.calls[scheduleMapSpy.mock.calls.length - 1][0];
    expect(props.jobs.length).toBe(3);
    // techColorMap threads the tech's display_color_hex.
    expect(props.techColorMap).toBeInstanceOf(Map);
    expect(props.techColorMap.get("u_tech")).toBe("#f97316");
    // Pin per geocoded job.
    expect(screen.getByTestId("__mock-pin-count").textContent).toBe("3");
  });

  it("map pins expose customer name + address (matches InfoWindow contract)", async () => {
    await mountWith(_DAY_WITH_GEO);
    await act(async () => {
      fireEvent.click(screen.getByTestId("schedule-sub-mode-map"));
    });
    // Each mock pin renders the customer name + address.
    expect(screen.getByTestId("__mock-schedule-map-pin-j1")).toBeTruthy();
    expect(screen.getByTestId("__mock-schedule-map-info-customer-j1").textContent).toBe("Alice");
    expect(screen.getByTestId("__mock-schedule-map-info-address-j1").textContent).toBe("1 Palm Ln");
    expect(screen.getByTestId("__mock-schedule-map-info-customer-j2").textContent).toBe("Bob");
    expect(screen.getByTestId("__mock-schedule-map-info-customer-j3").textContent).toBe("Carol");
  });

  it("clicking List after Map restores the list and unmounts the map", async () => {
    await mountWith(_DAY_WITH_GEO);
    await act(async () => {
      fireEvent.click(screen.getByTestId("schedule-sub-mode-map"));
    });
    expect(screen.getByTestId("__mock-schedule-map")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByTestId("schedule-sub-mode-list"));
    });
    expect(screen.queryByTestId("__mock-schedule-map")).toBeNull();
    expect(screen.getByTestId("schedule-card-list")).toBeTruthy();
  });

  it("empty-state: zero geocoded stops → shows 'No mappable stops today' card, NOT ScheduleMap", async () => {
    await mountWith(_DAY_ZERO_GEO);
    await act(async () => {
      fireEvent.click(screen.getByTestId("schedule-sub-mode-map"));
    });
    // Fallback card rendered; ScheduleMap NOT mounted (mappableCount === 0).
    expect(screen.getByTestId("tech-schedule-map-empty")).toBeTruthy();
    expect(screen.getByTestId("tech-schedule-map-empty").textContent)
      .toContain("No mappable stops today");
    expect(screen.queryByTestId("__mock-schedule-map")).toBeNull();
    // Spy should not have fired because map isn't mounted at all.
    expect(scheduleMapSpy).not.toHaveBeenCalled();
  });

  it("sub-mode preference persists to localStorage", async () => {
    await mountWith(_DAY_WITH_GEO);
    await act(async () => {
      fireEvent.click(screen.getByTestId("schedule-sub-mode-map"));
    });
    expect(localStorage.getItem("schedule_grid_sub_mode")).toBe("map");
    await act(async () => {
      fireEvent.click(screen.getByTestId("schedule-sub-mode-list"));
    });
    expect(localStorage.getItem("schedule_grid_sub_mode")).toBe("list");
  });
});
