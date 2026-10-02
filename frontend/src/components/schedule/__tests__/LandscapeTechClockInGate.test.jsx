import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
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


import LandscapeTechClockInGate from
  "@/components/schedule/LandscapeTechClockInGate";
import { __resetClockInStatusCacheForTests } from "@/hooks/useClockInGate";


const _Children = () =>
  <div data-testid="gate-child">OK</div>;


function _mockGeo(opts) {
  const stub = {
    getCurrentPosition: (ok, err) => {
      if (opts?.denied) err?.();
      else ok({
        coords: {
          latitude: opts.lat,
          longitude: opts.lng,
          accuracy: opts.acc,
        },
      });
    },
  };
  Object.defineProperty(global.navigator, "geolocation", {
    value: stub, configurable: true,
  });
}


beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  __resetClockInStatusCacheForTests();
});
afterEach(() => {
  cleanup();
  try {
    Object.defineProperty(global.navigator, "geolocation", {
      value: undefined, configurable: true,
    });
  } catch { /* ignore */ }
});


describe("LandscapeTechClockInGate", () => {
  it("gates landscape tech who is NOT clocked in", async () => {
    _mockUser = { id: "lu", role: "technician",
                   department: "landscaping" };
    getMock.mockImplementation(() =>
      Promise.resolve({ clocked_in: false }));
    render(
      <LandscapeTechClockInGate><_Children /></LandscapeTechClockInGate>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("landscape-clock-gate"))
        .toBeInTheDocument());
    expect(screen.queryByTestId("gate-child")).toBeNull();
  });

  it("passes through landscape tech who IS clocked in", async () => {
    _mockUser = { id: "lu2", role: "technician",
                   department: "landscaping" };
    getMock.mockImplementation(() =>
      Promise.resolve({ clocked_in: true }));
    render(
      <LandscapeTechClockInGate><_Children /></LandscapeTechClockInGate>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("gate-child")).toBeInTheDocument());
    expect(screen.queryByTestId("landscape-clock-gate")).toBeNull();
  });

  it("passes through pool tech immediately (gate short-circuits)",
      async () => {
    _mockUser = { id: "pu", role: "technician", department: "pool" };
    render(
      <LandscapeTechClockInGate><_Children /></LandscapeTechClockInGate>,
    );
    expect(screen.getByTestId("gate-child")).toBeInTheDocument();
    expect(screen.queryByTestId("landscape-clock-gate")).toBeNull();
    expect(getMock).not.toHaveBeenCalled();
  });

  it("passes through admin immediately (gate short-circuits)", () => {
    _mockUser = { id: "au", role: "admin" };
    render(
      <LandscapeTechClockInGate><_Children /></LandscapeTechClockInGate>,
    );
    expect(screen.getByTestId("gate-child")).toBeInTheDocument();
    expect(getMock).not.toHaveBeenCalled();
  });

  it("Clock In button fires POST /timeclock/punch with GPS payload "
      + "and flips to children on success", async () => {
    _mockUser = { id: "lu3", role: "technician",
                   department: "landscaping" };
    _mockGeo({ lat: 33.5, lng: -112.1, acc: 20 });
    let probeCount = 0;
    getMock.mockImplementation(() => {
      probeCount += 1;
      return Promise.resolve({ clocked_in: probeCount > 1 });
    });
    postMock.mockResolvedValue({});
    render(
      <LandscapeTechClockInGate><_Children /></LandscapeTechClockInGate>,
    );
    const btn = await waitFor(() =>
      screen.getByTestId("landscape-clock-gate-in-btn"));
    await act(async () => { fireEvent.click(btn); });
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    expect(postMock.mock.calls[0][0]).toBe("/timeclock/punch");
    expect(postMock.mock.calls[0][1]).toMatchObject({
      punch_type: "in", source: "web",
      lat: 33.5, lng: -112.1,
      geo_denied: false,
    });
    await waitFor(() =>
      expect(screen.getByTestId("gate-child")).toBeInTheDocument());
  });

  it("shows error testid when POST fails and keeps the gate up",
      async () => {
    _mockUser = { id: "lu4", role: "technician",
                   department: "landscaping" };
    _mockGeo({ lat: 33.5, lng: -112.1, acc: 20 });
    getMock.mockResolvedValue({ clocked_in: false });
    postMock.mockRejectedValue(new Error("Boom"));
    render(
      <LandscapeTechClockInGate><_Children /></LandscapeTechClockInGate>,
    );
    const btn = await waitFor(() =>
      screen.getByTestId("landscape-clock-gate-in-btn"));
    await act(async () => { fireEvent.click(btn); });
    await waitFor(() =>
      expect(screen.getByTestId("landscape-clock-gate-error"))
        .toBeInTheDocument());
    expect(screen.queryByTestId("gate-child")).toBeNull();
  });
});
