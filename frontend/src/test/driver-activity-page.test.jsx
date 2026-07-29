import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/users")) {
        return { users: [
          { id: "tech-1", name: "Luis Marquez", email: "landscaper@a.com",
            role: "technician", is_active: true },
        ], count: 1 };
      }
      if (path.startsWith("/gps/stops")) {
        return {
          user_id: "tech-1",
          user_name: "Luis Marquez",
          from: "2026-02-14T00:00:00Z",
          to:   "2026-02-14T23:59:59Z",
          stops: [
            { id: "s1", started_at: "2026-02-14T09:00:00Z",
              ended_at: "2026-02-14T09:08:00Z", duration_s: 480,
              center_lat: 33.7, center_lon: -112.2, ping_count: 8 },
            { id: "s2", started_at: "2026-02-14T09:20:00Z",
              ended_at: "2026-02-14T09:35:00Z", duration_s: 900,
              center_lat: 33.71, center_lon: -112.19, ping_count: 15 },
          ],
          count: 2,
        };
      }
      return {};
    }),
  },
}));

import DriverActivityPage from "@/pages/admin/DriverActivityPage";

describe("DriverActivityPage", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("renders the page shell + summary tiles", async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    expect(screen.getByTestId("driver-activity-page")).toBeTruthy();
    expect(screen.getByTestId("driver-activity-title")).toBeTruthy();
    expect(screen.getByTestId("driver-activity-summary")).toBeTruthy();
  });

  it("populates the tech dropdown from /api/users?role=technician", async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    const sel = await screen.findByTestId("driver-activity-tech-select");
    await waitFor(() => {
      expect(sel.querySelectorAll("option").length).toBeGreaterThanOrEqual(1);
    });
    expect(sel.textContent).toContain("Luis Marquez");
  });

  it("fetches stops and renders a block per stop on the timeline", async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    // Two stop rows appear once fetch resolves.
    const s1 = await screen.findByTestId("driver-activity-stop-s1");
    const s2 = await screen.findByTestId("driver-activity-stop-s2");
    expect(s1).toBeTruthy();
    expect(s2).toBeTruthy();
    // Stop-row list below the band.
    expect(screen.getByTestId("driver-activity-stop-row-s1")).toBeTruthy();
    expect(screen.getByTestId("driver-activity-stop-row-s2")).toBeTruthy();
  });

  it("shows the total-stops tile equal to stops.length", async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    await screen.findByTestId("driver-activity-stop-s2");
    const tile = screen.getByTestId("driver-activity-tile-stops");
    expect(tile.textContent).toContain("2");
  });
});
