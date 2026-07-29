import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act } from "@testing-library/react";

// Mock the api module used by useLiveTechPositions.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(() =>
      Promise.resolve({
        as_of: "2026-02-14T10:00:00Z",
        positions: [
          { user_id: "u1", user_name: "Test Tech", lat: 33.7, lon: -112.2,
            staleness_s: 30, accuracy_m: 10, captured_at: "2026-02-14T09:59:30Z",
            clock_in_id: "shift-1" },
        ],
      })
    ),
  },
}));

import useLiveTechPositions from "@/hooks/useLiveTechPositions";
import LiveTechPinsLayer from "@/pages/dispatch/LiveTechPinsLayer";

// Test-only React component that surfaces the hook's return value.
function Probe({ enabled = true, intervalMs = 30000, onChange }) {
  const state = useLiveTechPositions({ enabled, intervalMs });
  React.useEffect(() => { onChange(state); });
  return <div>{state.positions.length}</div>;
}

describe("useLiveTechPositions polling hook", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("starts a poll on mount and stops on unmount", async () => {
    const { api } = await import("@/api");
    const seen = { last: null };
    const { unmount } = render(
      <Probe enabled={true} intervalMs={30000}
             onChange={(s) => { seen.last = s; }} />,
    );
    // Let the initial fetch resolve.
    await act(async () => { await Promise.resolve(); });
    expect(api.get).toHaveBeenCalledWith("/gps/live-positions");
    expect(api.get).toHaveBeenCalledTimes(1);

    // Advance 30 seconds — expect a second poll.
    await act(async () => { vi.advanceTimersByTime(30000); await Promise.resolve(); });
    expect(api.get).toHaveBeenCalledTimes(2);

    // Unmount — no more polls after another 60 s.
    unmount();
    await act(async () => { vi.advanceTimersByTime(60000); await Promise.resolve(); });
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("does not fetch when disabled=false", async () => {
    const { api } = await import("@/api");
    const seen = { last: null };
    render(<Probe enabled={false} onChange={(s) => { seen.last = s; }} />);
    await act(async () => { await Promise.resolve(); });
    expect(api.get).not.toHaveBeenCalled();
  });
});

describe("LiveTechPinsLayer marker rendering", () => {
  // Stub the AdvancedMarker + InfoWindow so we can assert markup without
  // pulling in the whole Google Maps context.
  vi.mock("@vis.gl/react-google-maps", () => ({
    AdvancedMarker: ({ children, position }) => (
      <div data-testid={`marker-${position.lat}-${position.lng}`}>{children}</div>
    ),
    InfoWindow: ({ children }) => <div data-testid="live-info">{children}</div>,
  }));

  it("renders nothing when positions=[]", async () => {
    const { container } = render(<LiveTechPinsLayer positions={[]} />);
    expect(container.textContent).toBe("");
  });

  it("renders one marker per position with first-name label", async () => {
    const { getByTestId, getAllByTestId } = render(
      <LiveTechPinsLayer positions={[
        { user_id: "u1", user_name: "Alice Green", lat: 33.7, lon: -112.2,
          staleness_s: 30, accuracy_m: 12 },
        { user_id: "u2", user_name: "Bob White",  lat: 33.8, lon: -112.3,
          staleness_s: 200, accuracy_m: 20 },
      ]} />,
    );
    expect(getByTestId("dispatch-live-tech-u1")).toBeTruthy();
    expect(getByTestId("dispatch-live-tech-u2")).toBeTruthy();
    const markers = getAllByTestId(/^marker-/);
    expect(markers.length).toBe(2);
  });
});

describe("dispatch showLiveTechs localStorage toggle", () => {
  const KEY = "dispatch.showLiveTechs";
  beforeEach(() => { localStorage.clear(); });

  it("persists the toggle across reads", () => {
    localStorage.setItem(KEY, "false");
    expect(localStorage.getItem(KEY)).toBe("false");
    localStorage.setItem(KEY, "true");
    expect(localStorage.getItem(KEY)).toBe("true");
  });
});
