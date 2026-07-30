// Phase G5b addendum #2 · Feb-2026 — Driver Activity filter inputs.
//
// Verifies the customer/address search inputs debounce → refetch
// /gps/stops with q_customer / q_address query params, and that the
// Clear button resets both. Also verifies the customer name renders
// inline when present on the row (addendum #1).
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _users = [{ id: "u1", name: "Ana Tech", role: "technician" }];

// Return varying payloads based on query string so we can assert on
// which filters were sent.
const _makeStops = (opts = {}) => ({
  user_id: "u1",
  user_name: "Ana Tech",
  from: "2026-02-14T00:00:00Z",
  to: "2026-02-14T23:59:59Z",
  stops: [
    { id: "stop-1",
      started_at: "2026-02-14T09:00:00Z",
      ended_at:   "2026-02-14T09:15:00Z",
      duration_s: 900,
      center_lat: 33.5, center_lon: -112.0,
      radius_m: 20, ping_count: 12, source: "batch",
      address: { formatted: "42 Main Street" },
      attribution_status: "auto_linked",
      attributed_job_id: "j-1",
      attributed_customer_id: "c-1",
      attributed_customer_name: "Alice Waters",
      attribution_distance_m: 3.5 },
  ],
  count: 1,
  ...opts,
});

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/users")) return _users;
      if (path.startsWith("/gps/stops")) return _makeStops();
      if (path.startsWith("/jobs")) return [];
      return {};
    }),
    post: vi.fn(), patch: vi.fn(), del: vi.fn(),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

// Stub the map + safe-scroll to keep the render lean.
vi.mock("@/components/layout/SafeScrollContainer", () => ({
  default: ({ children }) => <div>{children}</div>,
}));
vi.mock("@vis.gl/react-google-maps", () => ({
  Map: ({ children }) => <div>{children}</div>,
  useMap: () => null,
  APIProvider: ({ children }) => <>{children}</>,
  AdvancedMarker: ({ children }) => <>{children}</>,
  InfoWindow: ({ children }) => <>{children}</>,
}));

import DriverActivityPage from "@/pages/admin/DriverActivityPage";
import { api } from "@/api";

describe("DriverActivityPage · G5b addendum #2 filters", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders the customer + address search inputs", async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    expect(await screen.findByTestId("driver-activity-q-customer"))
      .toBeInTheDocument();
    expect(screen.getByTestId("driver-activity-q-address"))
      .toBeInTheDocument();
  });

  it("shows the attributed customer name inline on the stop row", async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    await waitFor(() => {
      const cell = screen.getByTestId("driver-activity-stop-customer-stop-1");
      expect(cell).toHaveTextContent(/Alice Waters/);
    }, { timeout: 2000 });
  });

  it("typing in Customer debounces and refetches with q_customer param", async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    const input = await screen.findByTestId("driver-activity-q-customer");
    // Reset call log so we only see the follow-up refetch.
    api.get.mockClear();
    fireEvent.change(input, { target: { value: "Alice" } });
    await waitFor(() => {
      const calls = api.get.mock.calls.filter(
        (c) => c[0].startsWith("/gps/stops") && c[0].includes("q_customer=Alice"));
      expect(calls.length).toBeGreaterThan(0);
    }, { timeout: 2000 });
  });

  it("Clear button resets both filters", async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    const custInput = await screen.findByTestId("driver-activity-q-customer");
    const addrInput = screen.getByTestId("driver-activity-q-address");
    fireEvent.change(custInput, { target: { value: "Alice" } });
    fireEvent.change(addrInput, { target: { value: "Main" } });
    const clearBtn = await screen.findByTestId("driver-activity-q-clear");
    fireEvent.click(clearBtn);
    expect(custInput.value).toBe("");
    expect(addrInput.value).toBe("");
  });
});
