/**
 * Phase K16 · Feb-2026 — shared date-time formatter contract.
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";

let _origTZ;
beforeAll(() => { _origTZ = process.env.TZ; process.env.TZ = "America/Phoenix"; });
afterAll(() => { process.env.TZ = _origTZ; });

import { formatCompletedAt } from "../lib/dateTimeFormat";

describe("Phase K16 · formatCompletedAt", () => {
  it("renders 'Mon D, YYYY · h:mm AM/PM' for a valid ISO", () => {
    // 2026-09-01T22:38:00Z → Phoenix (UTC-7, no DST) → 3:38 PM.
    expect(formatCompletedAt("2026-09-01T22:38:00Z"))
      .toBe("Sep 1, 2026 · 3:38 PM");
  });

  it("returns em-dash for null / empty / invalid", () => {
    expect(formatCompletedAt(null)).toBe("—");
    expect(formatCompletedAt("")).toBe("—");
    expect(formatCompletedAt("not-a-date")).toBe("—");
  });

  it("unwraps a job/report object using completed_at first", () => {
    expect(formatCompletedAt({
      completed_at: "2026-09-01T22:38:00Z",
      updated_at: "2020-01-01T00:00:00Z",
      status: "completed",
    })).toBe("Sep 1, 2026 · 3:38 PM");
  });

  it("falls back to updated_at when status=completed and completed_at missing", () => {
    expect(formatCompletedAt({
      completed_at: null,
      updated_at: "2026-09-01T22:38:00Z",
      status: "completed",
    })).toBe("Sep 1, 2026 · 3:38 PM");
  });

  it("does NOT fall back to updated_at for non-completed rows", () => {
    expect(formatCompletedAt({
      completed_at: null,
      updated_at: "2026-09-01T22:38:00Z",
      status: "in_progress",
    })).toBe("—");
  });

  it("honors the tz option for tenants overriding viewer local", () => {
    expect(formatCompletedAt("2026-09-01T22:38:00Z",
                              { tz: "America/New_York" }))
      .toBe("Sep 1, 2026 · 6:38 PM");
  });
});
