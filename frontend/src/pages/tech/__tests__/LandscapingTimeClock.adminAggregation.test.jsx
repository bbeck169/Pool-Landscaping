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


import LandscapingTimeClock from "@/pages/tech/LandscapingTimeClock";


function _render() {
  return render(
    <MemoryRouter initialEntries={["/landscape/time-clock"]}>
      <LandscapingTimeClock />
    </MemoryRouter>,
  );
}


function _mineBaseMock() {
  return (url) => {
    if (String(url).startsWith("/timeclock/mine-today")) {
      return Promise.resolve({ punches: [], seconds: 0,
                                clocked_in: false });
    }
    if (String(url).startsWith("/timeclock/mine-summary")) {
      return Promise.resolve({ days: [], total_seconds: 0,
                                punches: [] });
    }
    if (String(url).startsWith("/timeclock/admin-summary")) {
      return Promise.resolve({
        range: { start: "2026-02-02", end: "2026-02-08" },
        techs: [
          {
            user_id: "u-alice",
            name: "Alice Green",
            status: "in",
            total_seconds: 7200,
            last_punch: {
              ts: "2026-02-03T10:00:00+00:00",
              lat: 33.5, lng: -112.1, punch_type: "in",
            },
            punches: [
              { id: "p1", ts: "2026-02-03T08:00:00+00:00",
                lat: 33.5, lng: -112.1,
                punch_type: "in", job_id: null },
              { id: "p2", ts: "2026-02-03T10:00:00+00:00",
                lat: 33.5, lng: -112.1,
                punch_type: "in", job_id: "j-77" },
            ],
          },
          {
            user_id: "u-bob",
            name: "Bob Shears",
            status: "out",
            total_seconds: 3600,
            last_punch: {
              ts: "2026-02-04T17:00:00+00:00",
              lat: 33.6, lng: -112.2, punch_type: "out",
            },
            punches: [
              { id: "p3", ts: "2026-02-04T16:00:00+00:00",
                lat: 33.6, lng: -112.2,
                punch_type: "in", job_id: null },
              { id: "p4", ts: "2026-02-04T17:00:00+00:00",
                lat: 33.6, lng: -112.2,
                punch_type: "out", job_id: null },
            ],
          },
        ],
      });
    }
    return Promise.resolve({});
  };
}


beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});
afterEach(() => cleanup());


describe("LandscapingTimeClock · admin aggregation", () => {
  it("does NOT render admin section for non-admin viewers", async () => {
    _mockUser = { id: "u-x", role: "technician",
                   department: "landscaping" };
    getMock.mockImplementation(_mineBaseMock());
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("landscape-time-clock"))
        .toBeInTheDocument());
    expect(
      screen.queryByTestId("landscape-time-clock-admin-aggregation"),
    ).toBeNull();
  });

  it("renders admin aggregation section for admin viewer", async () => {
    _mockUser = { id: "u-admin", role: "admin" };
    getMock.mockImplementation(_mineBaseMock());
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("landscape-time-clock-admin-aggregation"))
        .toBeInTheDocument());
    expect(screen.getByTestId("landscape-time-clock-admin-range-start"))
      .toBeInTheDocument();
    expect(screen.getByTestId("landscape-time-clock-admin-range-end"))
      .toBeInTheDocument();
    expect(screen.getByTestId("landscape-time-clock-admin-refresh"))
      .toBeInTheDocument();
    expect(screen.getByTestId("landscape-time-clock-admin-reset"))
      .toBeInTheDocument();
  });

  it("renders per-tech rows with name, status, total, last punch",
      async () => {
    _mockUser = { id: "u-admin", role: "manager" };
    getMock.mockImplementation(_mineBaseMock());
    _render();
    await waitFor(() => expect(screen.getByTestId(
      "landscape-time-clock-admin-tech-name-u-alice",
    )).toBeInTheDocument());
    expect(screen.getByTestId(
      "landscape-time-clock-admin-tech-status-u-alice",
    )).toHaveTextContent(/clocked in/i);
    expect(screen.getByTestId(
      "landscape-time-clock-admin-tech-total-u-alice",
    )).toHaveTextContent("2:00");
    expect(screen.getByTestId(
      "landscape-time-clock-admin-tech-last-u-alice",
    )).toBeInTheDocument();
    expect(screen.getByTestId(
      "landscape-time-clock-admin-tech-name-u-bob",
    )).toBeInTheDocument();
    expect(screen.getByTestId(
      "landscape-time-clock-admin-tech-status-u-bob",
    )).toHaveTextContent(/clocked out/i);
  });

  it("expands a tech's history when View History is clicked",
      async () => {
    _mockUser = { id: "u-admin", role: "super_admin" };
    getMock.mockImplementation(_mineBaseMock());
    _render();
    const btn = await waitFor(() => screen.getByTestId(
      "landscape-time-clock-admin-tech-expand-u-alice",
    ));
    await act(async () => { fireEvent.click(btn); });
    await waitFor(() => expect(screen.getByTestId(
      "landscape-time-clock-admin-tech-punches-u-alice",
    )).toBeInTheDocument());
  });

  it("re-fires GET /timeclock/admin-summary on Refresh with the "
      + "updated date range", async () => {
    _mockUser = { id: "u-admin", role: "admin" };
    getMock.mockImplementation(_mineBaseMock());
    _render();
    await waitFor(() => expect(screen.getByTestId(
      "landscape-time-clock-admin-aggregation",
    )).toBeInTheDocument());
    const beforeCount = getMock.mock.calls.filter(
      (c) => String(c[0]).includes("/timeclock/admin-summary"),
    ).length;
    const startInput = screen.getByTestId(
      "landscape-time-clock-admin-range-start",
    );
    fireEvent.change(startInput, { target: { value: "2026-01-05" } });
    const endInput = screen.getByTestId(
      "landscape-time-clock-admin-range-end",
    );
    fireEvent.change(endInput, { target: { value: "2026-01-11" } });
    const refresh = screen.getByTestId(
      "landscape-time-clock-admin-refresh",
    );
    await act(async () => { fireEvent.click(refresh); });
    await waitFor(() => {
      const afterCount = getMock.mock.calls.filter(
        (c) => String(c[0]).includes("/timeclock/admin-summary"),
      ).length;
      expect(afterCount).toBeGreaterThan(beforeCount);
    });
    const lastCall = [...getMock.mock.calls].reverse().find(
      (c) => String(c[0]).includes("/timeclock/admin-summary"),
    );
    expect(lastCall[0]).toContain("start=2026-01-05");
    expect(lastCall[0]).toContain("end=2026-01-11");
  });

  it("resets the range back to the current week on Reset", async () => {
    _mockUser = { id: "u-admin", role: "owner" };
    getMock.mockImplementation(_mineBaseMock());
    _render();
    const start = await waitFor(() => screen.getByTestId(
      "landscape-time-clock-admin-range-start",
    ));
    const initial = start.value;
    fireEvent.change(start, { target: { value: "2026-01-05" } });
    expect(start.value).toBe("2026-01-05");
    const reset = screen.getByTestId(
      "landscape-time-clock-admin-reset",
    );
    await act(async () => { fireEvent.click(reset); });
    await waitFor(() => expect(start.value).toBe(initial));
  });
});
