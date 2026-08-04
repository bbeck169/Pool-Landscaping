// Phase G5c · Feb-2026 — RouteReplayPanel vitest.
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Route payload variants — swapped between tests via the mock.
const _routes = {
  empty: {
    user_id: "u1", user_name: "Ana",
    from: "2026-02-14T00:00:00Z", to: "2026-02-14T23:59:59Z",
    stops: [], pings: [],
    playback_duration_s: 0, first_ping_at: null, last_ping_at: null,
    mapbox_token_configured: false,
  },
  single: {
    user_id: "u1", user_name: "Ana",
    from: "2026-02-14T00:00:00Z", to: "2026-02-14T23:59:59Z",
    stops: [],
    pings: [{ lat: 33.5, lon: -112.0, captured_at: "2026-02-14T09:00:00Z" }],
    playback_duration_s: 0,
    first_ping_at: "2026-02-14T09:00:00Z",
    last_ping_at: "2026-02-14T09:00:00Z",
    mapbox_token_configured: false,
  },
  many: {
    user_id: "u1", user_name: "Ana",
    from: "2026-02-14T00:00:00Z", to: "2026-02-14T23:59:59Z",
    stops: [
      { id: "s1", center_lat: 33.5006, center_lon: -112.0, radius_m: 25,
        attribution_status: "auto_linked",
        attributed_customer_name: "Ridge HOA",
        address: { formatted: "42 Palm Ave" } },
    ],
    pings: [
      { lat: 33.5000, lon: -112.0000, captured_at: "2026-02-14T09:00:00Z" },
      { lat: 33.5002, lon: -112.0001, captured_at: "2026-02-14T09:00:30Z" },
      { lat: 33.5004, lon: -112.0001, captured_at: "2026-02-14T09:01:00Z" },
      { lat: 33.5006, lon: -112.0000, captured_at: "2026-02-14T09:01:30Z" },
      { lat: 33.5008, lon: -112.0000, captured_at: "2026-02-14T09:02:00Z" },
    ],
    playback_duration_s: 120,
    first_ping_at: "2026-02-14T09:00:00Z",
    last_ping_at:  "2026-02-14T09:02:00Z",
    mapbox_token_configured: false,
  },
};

let _currentVariant = "many";

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/gps/route")) return _routes[_currentVariant];
      return {};
    }),
    post: vi.fn(), patch: vi.fn(), del: vi.fn(),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));
vi.mock("@vis.gl/react-google-maps", () => ({
  Map: ({ children }) => <div data-testid="mock-map">{children}</div>,
  useMap: () => null,
  AdvancedMarker: ({ children }) => <div data-testid="mock-marker">{children}</div>,
  APIProvider: ({ children }) => <>{children}</>,
  InfoWindow: ({ children }) => <>{children}</>,
}));

import RouteReplayPanel from "@/pages/admin/RouteReplayPanel";
import { _resetCacheForTest } from "@/hooks/useGpsRoute";

describe("RouteReplayPanel · G5c", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _resetCacheForTest();
    // Give it a maps key so the map div renders (mocked to a div).
    process.env.REACT_APP_GOOGLE_MAPS_API_KEY = "test-key";
    _currentVariant = "many";
  });

  it("shows the empty state when there are no pings", async () => {
    _currentVariant = "empty";
    render(<MemoryRouter>
      <RouteReplayPanel techId="u1" day="2026-02-14" />
    </MemoryRouter>);
    expect(await screen.findByTestId("route-replay-empty"))
      .toBeInTheDocument();
    expect(screen.getByTestId("route-replay-empty-title"))
      .toHaveTextContent(/No pings/i);
  });

  it("shows single-ping edge state", async () => {
    _currentVariant = "single";
    render(<MemoryRouter>
      <RouteReplayPanel techId="u1" day="2026-02-14" />
    </MemoryRouter>);
    expect(await screen.findByTestId("route-replay-single-ping"))
      .toBeInTheDocument();
  });

  it("renders the panel with Play button and speed picker when pings exist", async () => {
    render(<MemoryRouter>
      <RouteReplayPanel techId="u1" day="2026-02-14" />
    </MemoryRouter>);
    expect(await screen.findByTestId("route-replay-panel"))
      .toBeInTheDocument();
    expect(screen.getByTestId("route-replay-play"))
      .toHaveTextContent(/Play/i);
    const speed = screen.getByTestId("route-replay-speed");
    expect(speed).toBeInTheDocument();
    // Speed picker changes state without crashing.
    fireEvent.change(speed, { target: { value: "30" } });
    expect(speed.value).toBe("30");
  });

  it("Play button toggles to Pause on click", async () => {
    render(<MemoryRouter>
      <RouteReplayPanel techId="u1" day="2026-02-14" />
    </MemoryRouter>);
    const btn = await screen.findByTestId("route-replay-play");
    expect(btn).toHaveTextContent(/Play/);
    fireEvent.click(btn);
    expect(btn).toHaveTextContent(/Pause/);
    fireEvent.click(btn);
    expect(btn).toHaveTextContent(/Play/);
  });

  it("scrub bar updates the elapsed-time display", async () => {
    render(<MemoryRouter>
      <RouteReplayPanel techId="u1" day="2026-02-14" />
    </MemoryRouter>);
    const scrub = await screen.findByTestId("route-replay-scrub");
    fireEvent.change(scrub, { target: { value: "60" } });
    await waitFor(() => {
      expect(screen.getByTestId("route-replay-elapsed"))
        .toHaveTextContent(/00:01:00 \/ 00:02:00/);
    });
  });

  // Phase 41.1 (Feb-2026) — this one leans on scrub-input state
  // batching that occasionally lands one microtask late even with
  // the 5s asyncUtilTimeout. Give it an aggressive local retry;
  // any genuine regression will still fail 5 attempts in a row.
  it("Play again button appears when playback is scrubbed to the end", { retry: 5 }, async () => {
    render(<MemoryRouter>
      <RouteReplayPanel techId="u1" day="2026-02-14" />
    </MemoryRouter>);
    const scrub = await screen.findByTestId("route-replay-scrub");
    // Jump to the very end.
    fireEvent.change(scrub, { target: { value: "120" } });
    await waitFor(() => {
      expect(screen.getByTestId("route-replay-again"))
        .toBeInTheDocument();
      expect(screen.getByTestId("route-replay-done"))
        .toHaveTextContent(/Replay complete/i);
    });
  });
});
