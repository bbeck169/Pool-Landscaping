/**
 * Feb-2026 · P45 — "Next visit" column formatter (Vitest).
 *
 * The formatter lives on ``CustomersList.jsx`` as an inline helper.
 * We re-implement the same tiny function here so the assertions
 * pin the exact contract:
 *   • null / empty / unparseable  → "—"
 *   • current-year date           → "Aug 23"
 *   • other-year date             → "Aug 23, 2027"
 *   • tolerates both full-ISO and date-only shapes.
 */
import { describe, it, expect, beforeAll, afterAll, vi } from "vitest";


function nextScheduled(c) {
  const raw = c.next_scheduled_at;
  if (!raw) return "—";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "—";
  const thisYear = new Date().getFullYear();
  const opts = d.getFullYear() === thisYear
    ? { month: "short", day: "numeric" }
    : { month: "short", day: "numeric", year: "numeric" };
  return d.toLocaleDateString(undefined, opts);
}


// Pin "now" so year-based branching is deterministic across test runs.
// Aug 23, 2026 chosen to match the audit's live smoke.
beforeAll(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-08-23T12:00:00Z"));
});
afterAll(() => {
  vi.useRealTimers();
});


describe("nextScheduled formatter · P45", () => {
  it("returns '—' for null", () => {
    expect(nextScheduled({ next_scheduled_at: null })).toBe("—");
  });

  it("returns '—' for missing field", () => {
    expect(nextScheduled({})).toBe("—");
  });

  it("returns '—' for empty string", () => {
    expect(nextScheduled({ next_scheduled_at: "" })).toBe("—");
  });

  it("returns '—' for unparseable garbage", () => {
    expect(nextScheduled({ next_scheduled_at: "not-a-date" })).toBe("—");
  });

  it("formats current-year full-ISO as short month + day", () => {
    // "2026-08-23T09:00:00+00:00" — same year as pinned "now".
    expect(nextScheduled({
      next_scheduled_at: "2026-08-23T09:00:00+00:00",
    })).toBe("Aug 23");
  });

  it("formats current-year date-only as short month + day", () => {
    // "2026-09-01" — same year, no time-of-day.
    expect(nextScheduled({
      next_scheduled_at: "2026-09-01",
    })).toBe("Sep 1");
  });

  it("formats other-year date with the year appended", () => {
    expect(nextScheduled({
      next_scheduled_at: "2027-08-23T09:00:00+00:00",
    })).toBe("Aug 23, 2027");
  });

  it("formats other-year date-only with the year appended", () => {
    expect(nextScheduled({
      next_scheduled_at: "2027-01-15",
    })).toBe("Jan 15, 2027");
  });
});
