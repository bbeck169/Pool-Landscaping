/**
 * β-core 2 · JobGeofenceSyncRunner lifecycle — runs P37c sync after login,
 * on jobs-changed + foreground, never before login, stops on logout.
 */
import React from "react";
import { AppState } from "react-native";
import { render, act } from "@testing-library/react-native";

let mockUser: any = null;
const mockSync = jest.fn(async () => ({ registered: 0 }));
const mockStop = jest.fn(async () => {});
const mockListeners = new Set<() => void>();
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: mockUser }) }));
jest.mock("@/src/background/jobGeofence", () => ({
  syncJobGeofencesP37c: () => mockSync(),
  stopJobGeofencesP37c: () => mockStop(),
  onJobsChanged: (cb: () => void) => { mockListeners.add(cb); return () => mockListeners.delete(cb); },
}));

import JobGeofenceSyncRunner from "@/src/components/fleet/JobGeofenceSyncRunner";

let appStateCb: ((s: string) => void) | null = null;
beforeEach(() => {
  mockUser = null; mockSync.mockClear(); mockStop.mockClear(); mockListeners.clear(); appStateCb = null;
  jest.spyOn(AppState, "addEventListener").mockImplementation((_e: any, cb: any) => { appStateCb = cb; return { remove: jest.fn() } as any; });
});
afterEach(() => jest.restoreAllMocks());
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

describe("JobGeofenceSyncRunner", () => {
  it("does not sync before login (no /jobs call); stops stale regions instead", async () => {
    render(<JobGeofenceSyncRunner />);
    await flush();
    expect(mockSync).not.toHaveBeenCalled();
    expect(mockStop).toHaveBeenCalledTimes(1);
  });

  it("runs on login for a fleet-role tech", async () => {
    const q = render(<JobGeofenceSyncRunner />);
    mockUser = { id: "u1", role: "technician" };
    q.rerender(<JobGeofenceSyncRunner />);
    await flush();
    expect(mockSync).toHaveBeenCalledTimes(1);
  });

  it("non-fleet roles never sync", async () => {
    for (const role of ["admin", "super_admin", "manager", "customer"]) {
      mockUser = { id: "u1", role };
      const q = render(<JobGeofenceSyncRunner />);
      await flush();
      q.unmount();
    }
    expect(mockSync).not.toHaveBeenCalled();
  });

  it("re-runs on jobs-changed and on app foreground", async () => {
    mockUser = { id: "u1", role: "landscaper" };
    render(<JobGeofenceSyncRunner />);
    await flush();
    expect(mockSync).toHaveBeenCalledTimes(1);
    await act(async () => { mockListeners.forEach((cb) => cb()); });
    await flush();
    expect(mockSync).toHaveBeenCalledTimes(2);
    await act(async () => { appStateCb?.("background"); });
    await flush();
    expect(mockSync).toHaveBeenCalledTimes(2);
    await act(async () => { appStateCb?.("active"); });
    await flush();
    expect(mockSync).toHaveBeenCalledTimes(3);
  });

  it("calls during an in-flight sync coalesce into one trailing run", async () => {
    let release: () => void = () => {};
    mockSync.mockImplementationOnce(() => new Promise<any>((r) => { release = () => r({}); }));
    mockUser = { id: "u1", role: "technician" };
    render(<JobGeofenceSyncRunner />);
    await act(async () => { mockListeners.forEach((cb) => cb()); mockListeners.forEach((cb) => cb()); });
    expect(mockSync).toHaveBeenCalledTimes(1);
    await act(async () => { release(); });
    await flush();
    expect(mockSync).toHaveBeenCalledTimes(2);
  });

  it("logout stops the geofences and unsubscribes", async () => {
    mockUser = { id: "u1", role: "technician" };
    const q = render(<JobGeofenceSyncRunner />);
    await flush();
    mockStop.mockClear();
    mockUser = null;
    q.rerender(<JobGeofenceSyncRunner />);
    await flush();
    expect(mockStop).toHaveBeenCalledTimes(1);
    expect(mockListeners.size).toBe(0);
    await act(async () => { mockListeners.forEach((cb) => cb()); });
    expect(mockSync).toHaveBeenCalledTimes(1);
  });
});

describe("boot / mount wiring (source lock)", () => {
  const fs = require("fs");
  const path = require("path");
  const LAYOUT = fs.readFileSync(path.join(__dirname, "../app/_layout.tsx"), "utf8");
  it("_layout no longer calls syncJobGeofencesP37c in the boot effect; runner mounted next to FleetEmitterRunner", () => {
    expect(LAYOUT).not.toMatch(/syncJobGeofencesP37c\(/);
    expect(LAYOUT).toMatch(/<FleetEmitterRunner \/>\s*<JobGeofenceSyncRunner \/>/);
  });
  it("Schedule load notifies jobs-changed", () => {
    const CAL = fs.readFileSync(path.join(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf8");
    expect(CAL).toMatch(/setJobs\(arr\);\s*notifyJobsChanged\(\);/);
  });
});
