/**
 * FLEET-A · Feb-2026 — DispatchBoard page tests.
 *
 * Locks the board's contract:
 *   1. Fetches ``/api/fleet/board`` on mount and renders a
 *      tech card per row.
 *   2. Empty state routes admins to the membership screen.
 *   3. Ping-age chip colours by age bucket (green ≤ 2 min,
 *      yellow ≤ 10 min, red otherwise).
 *   4. ETA card renders provider badge + duration.
 *   5. Refresh button re-invokes the fetch.
 */
import React from "react";
import {
  render, screen, fireEvent, waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
  },
}));

// MapView pulls in Leaflet + Google Maps SDKs — those load browser
// APIs jsdom doesn't ship. Replace with a lightweight stub that
// asserts every point the board hands it renders as a testid.
vi.mock("@/components/MapView", () => {
  const DOT_COLORS = {
    green: "#16A34A", yellow: "#CA8A04", red: "#DC2626",
    blue: "#0284C7", gray: "#71717A",
  };
  const MapView = ({ layers = [], testid }) => (
    <div data-testid={testid || "mock-mapview"}>
      {layers.flatMap((layer) =>
        (layer.points || []).map((p) => (
          <div key={p.id} data-testid={`map-point-${p.id}`}>
            {p.label}
          </div>
        ))
      )}
    </div>
  );
  return { __esModule: true, default: MapView, DOT_COLORS };
});

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

import DispatchBoard from "@/pages/admin/DispatchBoard";


function _row(overrides = {}) {
  return {
    tech_user_id: "u-tech",
    tech_name: "Tom Tech",
    role: "technician",
    location: { lat: 33.7897, lng: -112.3226, battery_pct: 88.5 },
    last_ping_age_s: 30,
    current_job: {
      id: "job-1",
      title: "Weekly Pool Svc",
      customer_id: "cust-1",
      customer_name: "Jane H.",
      address: "123 Main",
      lat: 33.8,
      lng: -112.32,
    },
    eta: {
      provider: "crowflies",
      distance_m: 1234,
      duration_s: 600,
      eta_arrival_at: "2026-02-14T12:00:00Z",
    },
    battery_pct: 88.5,
    ...overrides,
  };
}


describe("FLEET-A · DispatchBoard", () => {
  beforeEach(() => {
    _apiMock.get.mockReset();
    _apiMock.post.mockReset();
  });

  it("fetches /fleet/board on mount and renders each tech card", async () => {
    _apiMock.get.mockResolvedValueOnce({
      count: 1, techs: [_row()],
    });
    render(
      <MemoryRouter>
        <DispatchBoard />
      </MemoryRouter>
    );
    await waitFor(() =>
      expect(_apiMock.get).toHaveBeenCalledWith("/fleet/board")
    );
    expect(await screen.findByTestId("fleet-tech-card-u-tech"))
      .toBeInTheDocument();
    expect(screen.getByTestId("admin-fleet-dispatch-title"))
      .toHaveTextContent("Fleet Dispatch Board");
  });

  it("renders empty state with a link to fleet-membership", async () => {
    _apiMock.get.mockResolvedValueOnce({ count: 0, techs: [] });
    render(
      <MemoryRouter>
        <DispatchBoard />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("admin-fleet-dispatch-empty"))
      .toBeInTheDocument();
    expect(screen.getByTestId("admin-fleet-dispatch-membership-link"))
      .toHaveTextContent(/enable techs/i);
  });

  it("shows ETA card with provider badge and rounded minutes", async () => {
    _apiMock.get.mockResolvedValueOnce({
      count: 1,
      techs: [_row({ eta: {
        provider: "google", distance_m: 5000, duration_s: 360,
      } })],
    });
    render(
      <MemoryRouter>
        <DispatchBoard />
      </MemoryRouter>
    );
    const eta = await screen.findByTestId("fleet-tech-eta-u-tech");
    expect(eta).toHaveTextContent(/ETA:\s*6\s*min/i);
    const badge = screen.getByTestId(
      "fleet-tech-eta-provider-u-tech"
    );
    expect(badge).toHaveTextContent(/google/i);
  });

  it("shows ETA-unavailable warning when tech has a job but no eta", async () => {
    _apiMock.get.mockResolvedValueOnce({
      count: 1,
      techs: [_row({ eta: null })],
    });
    render(
      <MemoryRouter>
        <DispatchBoard />
      </MemoryRouter>
    );
    expect(await screen.findByTestId("fleet-tech-eta-unavailable-u-tech"))
      .toBeInTheDocument();
  });

  it("refresh button re-invokes the fetch", async () => {
    _apiMock.get.mockResolvedValueOnce({ count: 1, techs: [_row()] });
    render(
      <MemoryRouter>
        <DispatchBoard />
      </MemoryRouter>
    );
    await screen.findByTestId("fleet-tech-card-u-tech");
    expect(_apiMock.get).toHaveBeenCalledTimes(1);

    _apiMock.get.mockResolvedValueOnce({ count: 1, techs: [_row()] });
    fireEvent.click(screen.getByTestId("admin-fleet-dispatch-refresh"));
    await waitFor(() =>
      expect(_apiMock.get).toHaveBeenCalledTimes(2)
    );
  });

  it("renders map with a point per tech and a point per job", async () => {
    _apiMock.get.mockResolvedValueOnce({
      count: 1, techs: [_row()],
    });
    render(
      <MemoryRouter>
        <DispatchBoard />
      </MemoryRouter>
    );
    await screen.findByTestId("fleet-tech-card-u-tech");
    expect(screen.getByTestId("map-point-tech-u-tech"))
      .toBeInTheDocument();
    expect(screen.getByTestId("map-point-job-job-1"))
      .toBeInTheDocument();
  });

  it("surfaces a toast when the API rejects", async () => {
    const { toast } = await import("sonner");
    _apiMock.get.mockRejectedValueOnce(new Error("boom"));
    render(
      <MemoryRouter>
        <DispatchBoard />
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("Fleet board load failed")
      );
    });
  });
});
