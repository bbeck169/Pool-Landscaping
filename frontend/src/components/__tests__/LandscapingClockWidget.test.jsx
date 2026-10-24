/**
 * TD-timeclock-tech-clock-out-flow · Feb-2026 · FE contract tests.
 *
 * LandscapingClockWidget pivot from /api/timeclock/* onto
 * /api/workforce/* (time_entries source of truth).  Specs lock the
 * contract covering:
 *
 *   • renders "Clock In" when ``/workforce/open-shift`` returns
 *     ``{entry: null}``
 *   • clicking Clock In POSTs ``/workforce/clock-in`` with
 *     ``job_id: null`` + geo, then re-renders as "Clock Out" with
 *     the running timer visible
 *   • timer ticks (via mocked Date.now) off the open entry's
 *     ``clock_in_at`` field
 *   • clicking Clock Out POSTs ``/workforce/clock-out`` with the
 *     open entry's id, then re-renders back to "Clock In"
 *   • widget hides for non-landscape users (visibility contract)
 *   • widget renders for landscapers who have ``show_time_clock``
 *     but ``department`` missing (projection fallback)
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  render, screen, cleanup, waitFor, fireEvent, act,
} from "@testing-library/react";


const getMock = vi.fn();
const postMock = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    patch: vi.fn().mockResolvedValue({}),
    put: vi.fn().mockResolvedValue({}),
  },
  TOKEN_KEY: "token",
}));


let _mockUser = null;
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: _mockUser }),
}));

// Stub geolocation so readGeo() resolves synchronously-ish without
// touching the browser permissions prompt in jsdom.
beforeEach(() => {
  Object.defineProperty(globalThis.navigator, "geolocation", {
    configurable: true,
    value: {
      getCurrentPosition: (ok) => ok({
        coords: { latitude: 33.70, longitude: -112.22, accuracy: 10 },
      }),
    },
  });
});

afterEach(() => {
  cleanup();
  getMock.mockReset();
  postMock.mockReset();
  _mockUser = null;
  vi.useRealTimers();
});


import LandscapingClockWidget from "@/components/LandscapingClockWidget";


function _render() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <LandscapingClockWidget />
    </MemoryRouter>,
  );
}


function _landscaper() {
  _mockUser = {
    id: "u-land", role: "technician",
    department: "landscaping", show_time_clock: true,
  };
}


function _poolTech() {
  _mockUser = {
    id: "u-pool", role: "technician",
    department: "pool", show_time_clock: false,
  };
}


function _landscaperWithoutDeptField() {
  // Widget visibility must still work when the raw JWT lacks
  // ``department`` as long as ``show_time_clock`` is projected
  // (BE helper ``_resolve_tech_department`` + /auth/me do this).
  _mockUser = {
    id: "u-land-nodept", role: "technician",
    show_time_clock: true,
  };
}


describe("LandscapingClockWidget · pivot to /workforce/*", () => {
  it("renders 'Clock In' when /workforce/open-shift returns null", async () => {
    _landscaper();
    getMock.mockImplementation((url) => {
      if (String(url).startsWith("/workforce/open-shift"))
        return Promise.resolve({ entry: null });
      if (String(url).startsWith("/workforce/timesheets"))
        return Promise.resolve([]);
      return Promise.resolve({});
    });
    _render();
    await waitFor(() => {
      expect(screen.getByTestId("landscape-clock-widget-in")).toBeTruthy();
    });
    expect(screen.getByTestId("landscape-clock-widget-timer").textContent)
      .toMatch(/0h 00m/);
  });

  it("hides for non-landscape users", async () => {
    _poolTech();
    getMock.mockResolvedValue({ entry: null });
    _render();
    // No widget renders at all.
    await waitFor(() => {
      expect(screen.queryByTestId("landscape-clock-widget")).toBeNull();
    });
  });

  it("renders when show_time_clock=true even if department is missing", async () => {
    _landscaperWithoutDeptField();
    getMock.mockImplementation((url) => {
      if (String(url).startsWith("/workforce/open-shift"))
        return Promise.resolve({ entry: null });
      return Promise.resolve([]);
    });
    _render();
    await waitFor(() => {
      expect(screen.getByTestId("landscape-clock-widget")).toBeTruthy();
    });
  });

  it("clicking Clock In posts /workforce/clock-in and flips to Clock Out + timer", async () => {
    _landscaper();
    // Stateful mock — tracks whether we've clocked in yet.
    let _hasOpen = false;
    const _IN_AT = "2026-10-24T06:00:00+00:00";
    const _entry = {
      id: "entry-1", clock_in_at: _IN_AT, clock_out_at: null,
      job_id: null, job_title: "General work", user_id: "u-land",
      status: "open",
    };
    getMock.mockImplementation((url) => {
      if (String(url).startsWith("/workforce/open-shift"))
        return Promise.resolve({ entry: _hasOpen ? _entry : null });
      if (String(url).startsWith("/workforce/timesheets"))
        return Promise.resolve([]);
      return Promise.resolve({});
    });

    postMock.mockImplementation((url) => {
      if (String(url).startsWith("/workforce/clock-in")) {
        _hasOpen = true;
        return Promise.resolve(_entry);
      }
      return Promise.resolve({});
    });

    _render();
    await waitFor(() => {
      expect(screen.getByTestId("landscape-clock-widget-in")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("landscape-clock-widget-in"));
    });

    // Post was fired with job_id: null + geo.
    const call = postMock.mock.calls.find(
      (c) => String(c[0]).startsWith("/workforce/clock-in"),
    );
    expect(call).toBeTruthy();
    expect(call[1]).toMatchObject({ job_id: null });
    expect(typeof call[1].lat).toBe("number");

    // Button has flipped to Clock Out.
    await waitFor(() => {
      expect(screen.getByTestId("landscape-clock-widget-out")).toBeTruthy();
    });

    // Timer renders a non-zero elapsed from the clock_in_at
    // timestamp.  Walk Date.now() forward 1 hour and tick the
    // widget's setInterval manually.
    const _origNow = Date.now;
    Date.now = () => new Date("2026-10-24T07:00:00+00:00").getTime();
    try {
      // Trigger a re-render by advancing the widget's tick state.
      // The widget uses setInterval(1000) — easier to just fire a
      // synthetic event that re-reads runningSeconds via a probe
      // re-render.  Clicking refresh is not exposed, so wait for
      // the natural tick (max ~1.1s).
      await new Promise((r) => setTimeout(r, 1200));
      expect(screen.getByTestId("landscape-clock-widget-timer").textContent)
        .toMatch(/1h 00m/);
    } finally {
      Date.now = _origNow;
    }
  });

  it("clicking Clock Out posts /workforce/clock-out and flips back to Clock In", async () => {
    _landscaper();
    const _IN_AT = "2026-10-24T06:00:00+00:00";
    const _entry = {
      id: "entry-2", clock_in_at: _IN_AT, clock_out_at: null,
      job_id: null, job_title: "General work", user_id: "u-land",
      status: "open",
    };
    // Stateful mock — ``_hasOpen`` flips when clock-out POST fires.
    let _hasOpen = true;
    getMock.mockImplementation((url) => {
      if (String(url).startsWith("/workforce/open-shift"))
        return Promise.resolve({ entry: _hasOpen ? _entry : null });
      if (String(url).startsWith("/workforce/timesheets"))
        return Promise.resolve([]);
      return Promise.resolve({});
    });
    postMock.mockImplementation((url) => {
      if (String(url).startsWith("/workforce/clock-out")) {
        _hasOpen = false;
        return Promise.resolve({ ..._entry, clock_out_at: "2026-10-24T07:00:00+00:00" });
      }
      return Promise.resolve({});
    });

    _render();
    await waitFor(() => {
      expect(screen.getByTestId("landscape-clock-widget-out")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("landscape-clock-widget-out"));
    });

    const call = postMock.mock.calls.find(
      (c) => String(c[0]).startsWith("/workforce/clock-out"),
    );
    expect(call).toBeTruthy();
    expect(call[1]).toMatchObject({ entry_id: "entry-2" });

    // Button flips back.
    await waitFor(() => {
      expect(screen.getByTestId("landscape-clock-widget-in")).toBeTruthy();
    });
  });
});
