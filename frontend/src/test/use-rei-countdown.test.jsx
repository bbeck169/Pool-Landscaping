/**
 * Feb-2026 · C3 · ``useReiCountdown`` hook.
 *
 * Covers:
 *   1. Locked shape when unlock is 4h in the future.
 *   2. Unlocked shape after unlock timestamp passes.
 *   3. Ticks every 60 s under fake timers — transitions from
 *      locked → unlocked without re-render prompt.
 *   4. Cleans up the interval on unmount.
 *   5. Null / malformed input returns unlocked shape and
 *      schedules NO timer.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { act } from "react-dom/test-utils";

import { useReiCountdown } from "../hooks/useReiCountdown";


/**
 * Renders the hook inside a probe component so we can read the
 * returned snapshot without pulling `renderHook` (avoids a fresh
 * testing-library-react-hooks dep just for one file).
 */
function _renderHook(iso, tickMs) {
  const capture = { value: null };
  function Probe() {
    capture.value = useReiCountdown(iso, tickMs);
    return null;
  }
  const utils = render(<Probe />);
  return { capture, utils };
}


describe("useReiCountdown", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Anchor "now" at 2026-02-20 12:00 UTC so every test's math is
    // reproducible regardless of the host clock.
    vi.setSystemTime(new Date("2026-02-20T12:00:00Z"));
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("returns locked shape with hoursRemaining when unlock is 4h away", () => {
    const iso = "2026-02-20T16:00:00Z"; // +4h from anchored now
    const { capture } = _renderHook(iso);
    expect(capture.value.isLocked).toBe(true);
    expect(capture.value.hoursRemaining).toBe(4);
    expect(capture.value.minutesRemaining).toBe(0);
    expect(capture.value.msRemaining).toBeGreaterThan(0);
  });

  it("returns partial hours + minutes for a 4h 12m gap", () => {
    const iso = "2026-02-20T16:12:00Z"; // +4h 12m
    const { capture } = _renderHook(iso);
    expect(capture.value.isLocked).toBe(true);
    expect(capture.value.hoursRemaining).toBe(4);
    expect(capture.value.minutesRemaining).toBe(12);
  });

  it("returns unlocked shape when unlock timestamp has already passed", () => {
    const iso = "2026-02-20T11:00:00Z"; // 1h ago
    const { capture } = _renderHook(iso);
    expect(capture.value.isLocked).toBe(false);
    expect(capture.value.hoursRemaining).toBe(0);
    expect(capture.value.minutesRemaining).toBe(0);
    expect(capture.value.msRemaining).toBe(0);
  });

  it("transitions locked → unlocked on the tick after the unlock passes", () => {
    const iso = "2026-02-20T12:00:30Z"; // +30 s so the 60 s tick clears it
    const { capture } = _renderHook(iso);
    expect(capture.value.isLocked).toBe(true);
    // Advance system time PAST the unlock, then fire the 60 s tick.
    act(() => {
      vi.setSystemTime(new Date("2026-02-20T12:01:00Z")); // +30 s past
      vi.advanceTimersByTime(60_000);
    });
    expect(capture.value.isLocked).toBe(false);
    expect(capture.value.hoursRemaining).toBe(0);
  });

  it("clears the interval on unmount (no timer leak)", () => {
    const iso = "2026-02-20T14:00:00Z";
    const { utils } = _renderHook(iso);
    const before = vi.getTimerCount();
    expect(before).toBeGreaterThan(0);
    utils.unmount();
    const after = vi.getTimerCount();
    expect(after).toBeLessThan(before);
  });

  it("returns unlocked shape and schedules NO timer for null iso", () => {
    const before = vi.getTimerCount();
    const { capture } = _renderHook(null);
    expect(capture.value.isLocked).toBe(false);
    // No new interval scheduled.
    expect(vi.getTimerCount()).toBe(before);
  });

  it("returns unlocked shape for malformed iso", () => {
    const before = vi.getTimerCount();
    const { capture } = _renderHook("not-a-date");
    expect(capture.value.isLocked).toBe(false);
    expect(vi.getTimerCount()).toBe(before);
  });
});
