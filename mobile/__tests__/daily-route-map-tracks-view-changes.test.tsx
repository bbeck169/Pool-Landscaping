/**
 * Phase P22 · daily-route-map-tracks-view-changes.test.tsx
 *
 * Verifies the tracksViewChanges initial-true-then-flip pattern
 * via source-level inspection + a focused unit test of the timing logic.
 *
 * The DailyRouteMap component is heavily coupled to native maps +
 * dozens of provider mocks, so we test the pattern structurally and
 * via a minimal hook-level unit test rather than a full component mount.
 */

import * as fs from "fs";
import * as path from "path";
import React from "react";
import { renderHook, act } from "@testing-library/react-native";

const ROOT = path.resolve(__dirname, "..");
const MAP_FILE = "src/components/schedule/DailyRouteMap.native.tsx";

function readSrc(): string {
  return fs.readFileSync(path.join(ROOT, MAP_FILE), "utf-8");
}

describe("DailyRouteMap tracksViewChanges (P22)", () => {
  /* ── Source-level structural assertions ───────────────────────── */

  it("no hardcoded tracksViewChanges={false} in Marker JSX", () => {
    const src = readSrc();
    // After P22, tracksViewChanges should be bound to a state variable,
    // never the literal `{false}`.
    expect(src).not.toMatch(/tracksViewChanges=\{false\}/);
  });

  it("tracksViewChanges is bound to a state variable (markersTracking)", () => {
    const src = readSrc();
    expect(src).toMatch(/tracksViewChanges=\{markersTracking\}/);
  });

  it("markersTracking state initialized to true", () => {
    const src = readSrc();
    // useState(true) for markersTracking.
    expect(src).toMatch(/useState\(true\)/);
    // And the variable name is markersTracking.
    expect(src).toMatch(/\[markersTracking,\s*setMarkersTracking\]\s*=\s*useState\(true\)/);
  });

  it("has a useEffect that flips markersTracking to false after a timeout", () => {
    const src = readSrc();
    expect(src).toMatch(/setMarkersTracking\(false\)/);
    expect(src).toMatch(/setTimeout\(\s*\(\)\s*=>\s*setMarkersTracking\(false\)/);
  });

  it("re-enables tracking when pins change", () => {
    const src = readSrc();
    // A useEffect with [pins] dependency that calls setMarkersTracking(true).
    expect(src).toMatch(/setMarkersTracking\(true\)/);
    expect(src).toMatch(/\[pins\]/);
  });

  /* ── Hook-level unit test of the timing pattern ──────────────── */

  it("tracking hook: starts true, flips false after 350ms, re-enables on dep change", () => {
    jest.useFakeTimers();

    // Minimal reproduction of the pattern from DailyRouteMap.
    function useMarkersTracking(pins: any[]) {
      const [tracking, setTracking] = React.useState(true);
      React.useEffect(() => {
        if (!tracking) return;
        const t = setTimeout(() => setTracking(false), 350);
        return () => clearTimeout(t);
      }, [tracking]);
      React.useEffect(() => {
        setTracking(true);
      }, [pins]);
      return tracking;
    }

    const pins1 = [{ id: "a" }];
    const { result, rerender } = renderHook(
      ({ pins }) => useMarkersTracking(pins),
      { initialProps: { pins: pins1 } },
    );

    // t=0: tracking is true.
    expect(result.current).toBe(true);

    // Advance past 350ms → flips to false.
    act(() => { jest.advanceTimersByTime(400); });
    expect(result.current).toBe(false);

    // New pins → re-enables.
    const pins2 = [{ id: "a" }, { id: "b" }];
    rerender({ pins: pins2 });
    expect(result.current).toBe(true);

    // Flips again after timeout.
    act(() => { jest.advanceTimersByTime(400); });
    expect(result.current).toBe(false);

    jest.useRealTimers();
  });
});
