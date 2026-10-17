/**
 * TD-64 · Feb-2026 — ``shouldShowTimeClock`` helper vitests.
 *
 * Mirrors ``backend/tests/test_users_me_effective_department.py``:
 * the BE-authoritative ``show_time_clock`` boolean wins when
 * present; falls back to ``effective_department`` → ``department``
 * with case + whitespace normalization against the shared
 * ``LANDSCAPE_DEPTS`` frozenset.
 */
import { describe, it, expect } from "vitest";
import {
  LANDSCAPE_DEPTS,
  shouldShowTimeClock,
} from "@/lib/timeClockVisibility";


describe("shouldShowTimeClock · basic contract", () => {
  it("returns false for null / undefined user", () => {
    expect(shouldShowTimeClock(null)).toBe(false);
    expect(shouldShowTimeClock(undefined)).toBe(false);
  });

  it("returns false for pool department", () => {
    expect(shouldShowTimeClock({ department: "pool" })).toBe(false);
    expect(shouldShowTimeClock({ department: "pool_tech" })).toBe(false);
  });

  it("returns true for every member of LANDSCAPE_DEPTS", () => {
    for (const dept of LANDSCAPE_DEPTS) {
      expect(shouldShowTimeClock({ department: dept })).toBe(true);
    }
  });

  it("reads effective_department when present (BE denorm fallback)", () => {
    expect(
      shouldShowTimeClock({ effective_department: "landscape_tech" }),
    ).toBe(true);
    expect(
      shouldShowTimeClock({ effective_department: "pool" }),
    ).toBe(false);
  });

  it("BE-computed show_time_clock boolean wins over department", () => {
    // Even when department would say "pool", the BE boolean wins.
    expect(
      shouldShowTimeClock({ show_time_clock: true, department: "pool" }),
    ).toBe(true);
    // Reverse — BE says hide, dept would say show.
    expect(
      shouldShowTimeClock({
        show_time_clock: false,
        department: "landscaping",
      }),
    ).toBe(false);
  });

  it("tolerates case + leading/trailing whitespace", () => {
    expect(
      shouldShowTimeClock({ department: " LANDSCAPER " }),
    ).toBe(true);
    expect(
      shouldShowTimeClock({ department: "LandscApIng" }),
    ).toBe(true);
    expect(
      shouldShowTimeClock({ effective_department: "   both   " }),
    ).toBe(true);
  });

  it("preserves BE boolean false — bogus truthy strings do NOT flip the chip", () => {
    // Only strict boolean type wins per the helper contract.
    expect(
      shouldShowTimeClock({ show_time_clock: "yes", department: "pool" }),
    ).toBe(false);
    expect(
      shouldShowTimeClock({ show_time_clock: 1, department: "pool" }),
    ).toBe(false);
  });

  it("returns false for unassigned department", () => {
    expect(shouldShowTimeClock({ department: "" })).toBe(false);
    expect(shouldShowTimeClock({ department: null })).toBe(false);
    expect(shouldShowTimeClock({ department: undefined })).toBe(false);
  });
});
