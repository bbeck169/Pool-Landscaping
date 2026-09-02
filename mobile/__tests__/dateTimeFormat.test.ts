/**
 * dateTimeFormat.test.ts — Phase K22 · Unit tests for formatCompletedAt.
 * Mirrors the web K16 test cases.
 */
import { formatCompletedAt } from "@/src/lib/dateTimeFormat";

describe("formatCompletedAt", () => {
  // ── canonical string render ──
  it('renders "Sep 1, 2026 · HH:MM AM/PM" for a valid ISO string', () => {
    const result = formatCompletedAt("2026-09-01T15:38:00Z");
    // Timezone-dependent, so just check structure.
    expect(result).toMatch(/Sep 1, 2026 · \d{1,2}:\d{2}\s?[AP]M/);
  });

  // ── null / undefined / empty ──
  it("returns em-dash for null", () => {
    expect(formatCompletedAt(null)).toBe("\u2014");
  });

  it("returns em-dash for undefined", () => {
    expect(formatCompletedAt(undefined)).toBe("\u2014");
  });

  it("returns em-dash for empty string", () => {
    expect(formatCompletedAt("")).toBe("\u2014");
  });

  // ── invalid date ──
  it("returns em-dash for invalid date string", () => {
    expect(formatCompletedAt("not-a-date")).toBe("\u2014");
  });

  // ── object unwrap ──
  it("unwraps object with completed_at (snake_case)", () => {
    const result = formatCompletedAt({ completed_at: "2026-09-01T15:38:00Z" });
    expect(result).toMatch(/Sep 1, 2026/);
    expect(result).toContain("·");
  });

  it("unwraps object with completedAt (camelCase)", () => {
    const result = formatCompletedAt({ completedAt: "2026-12-25T18:00:00Z" });
    expect(result).toMatch(/Dec 25, 2026/);
  });

  // ── updated_at fallback ──
  it("falls back to updated_at when status is 'completed'", () => {
    const result = formatCompletedAt({
      status: "completed",
      updated_at: "2026-09-01T15:38:00Z",
    });
    expect(result).toMatch(/Sep 1, 2026/);
  });

  it("does NOT use updated_at when status is not 'completed'", () => {
    const result = formatCompletedAt({
      status: "open",
      updated_at: "2026-09-01T15:38:00Z",
    });
    expect(result).toBe("\u2014");
  });

  // ── timezone option ──
  it("respects tz option (America/Phoenix = UTC-7, no DST)", () => {
    // 15:38 UTC → 8:38 AM MST
    const result = formatCompletedAt("2026-09-01T15:38:00Z", {
      tz: "America/Phoenix",
    });
    expect(result).toMatch(/Sep 1, 2026 · 8:38\s?AM/);
  });

  // ── both completed_at and updated_at present ──
  it("prefers completed_at over updated_at", () => {
    const result = formatCompletedAt({
      completed_at: "2026-01-15T10:00:00Z",
      updated_at: "2026-06-01T10:00:00Z",
      status: "completed",
    });
    expect(result).toMatch(/Jan 15, 2026/);
  });
});
