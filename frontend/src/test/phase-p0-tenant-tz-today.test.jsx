/**
 * Feb-2026 · P0 Timezone Fix · Tenant-tz-aware "today" comparison.
 *
 * Bug context: ``new Date().toISOString().slice(0, 10)`` returns the
 * UTC date, not the tenant-local date. In Phoenix (UTC-7), at 5 PM
 * local the UTC date has already rolled over — the old
 * ``TodaySchedule`` treated "today" as tomorrow, hiding every job
 * scheduled for the actual current day.
 *
 * Guardrails locked here:
 *   1. ``getTenantTodayISO`` returns the tenant-local date even when
 *      the system clock has already crossed UTC midnight.
 *   2. ``getTenantISODate`` is stable across every canonical zone.
 *   3. ``shiftTenantISODate`` doesn't slip a day on DST transitions.
 *   4. ``isTenantTodayISO`` uses the same source-of-truth ladder.
 *   5. Missing / unknown tz falls back to ``America/Phoenix``
 *      (backend default).
 *   6. ``TodaySchedule`` no longer contains ``toISOString().slice(0, 10)``.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import fs from "fs";
import path from "path";
import {
  getTenantTodayISO,
  getTenantISODate,
  shiftTenantISODate,
  isTenantTodayISO,
  TENANT_TZ_FALLBACK,
} from "@/lib/tenantTz";


describe("tenantTz helpers (Phase P0 · Feb-2026 UTC-midnight fix)", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("TENANT_TZ_FALLBACK matches the backend default", () => {
    expect(TENANT_TZ_FALLBACK).toBe("America/Phoenix");
  });

  it("returns the Phoenix-local date at 5 PM local (UTC midnight)", () => {
    // 2026-02-15 17:00 America/Phoenix (UTC-7, no DST) === 2026-02-16 00:00 UTC.
    // The pre-fix code returned "2026-02-16"; the fix must return "2026-02-15".
    vi.setSystemTime(new Date("2026-02-16T00:00:00Z"));
    expect(getTenantTodayISO("America/Phoenix")).toBe("2026-02-15");
    expect(getTenantTodayISO()).toBe("2026-02-15");  // fallback
  });

  it("returns the Los Angeles-local date at 4 PM PST (UTC midnight)", () => {
    // Winter, PST is UTC-8. 4 PM PST === midnight UTC.
    vi.setSystemTime(new Date("2026-02-16T00:00:00Z"));
    expect(getTenantTodayISO("America/Los_Angeles")).toBe("2026-02-15");
  });

  it("returns the New York-local date at 8 PM EST (UTC + next day 01:00)", () => {
    // Winter, EST is UTC-5. 8 PM EST === 01:00 UTC next day.
    vi.setSystemTime(new Date("2026-02-16T01:00:00Z"));
    expect(getTenantTodayISO("America/New_York")).toBe("2026-02-15");
  });

  it("returns the UTC date when tenant is UTC", () => {
    vi.setSystemTime(new Date("2026-02-16T00:30:00Z"));
    expect(getTenantTodayISO("UTC")).toBe("2026-02-16");
  });

  it("falls back to America/Phoenix on an unknown IANA id", () => {
    vi.setSystemTime(new Date("2026-02-16T00:00:00Z"));
    expect(getTenantTodayISO("Mars/Olympus_Mons")).toBe("2026-02-15");
  });

  it("shiftTenantISODate advances/rewinds by whole days in tenant tz", () => {
    expect(shiftTenantISODate("2026-02-15", 1, "America/Phoenix"))
      .toBe("2026-02-16");
    expect(shiftTenantISODate("2026-02-15", -1, "America/Phoenix"))
      .toBe("2026-02-14");
    expect(shiftTenantISODate("2026-02-15", 7, "America/New_York"))
      .toBe("2026-02-22");
  });

  it("shiftTenantISODate handles DST spring-forward without slipping", () => {
    // US DST-start 2026 = Sun Mar 8. Stepping across it in
    // America/Los_Angeles must land on the correct calendar day.
    expect(shiftTenantISODate("2026-03-07", 1, "America/Los_Angeles"))
      .toBe("2026-03-08");
    expect(shiftTenantISODate("2026-03-08", 1, "America/Los_Angeles"))
      .toBe("2026-03-09");
  });

  it("isTenantTodayISO uses the tenant tz for comparison", () => {
    vi.setSystemTime(new Date("2026-02-16T00:00:00Z"));
    // Phoenix says today is Feb 15; UTC says today is Feb 16.
    expect(isTenantTodayISO("2026-02-15", "America/Phoenix")).toBe(true);
    expect(isTenantTodayISO("2026-02-16", "America/Phoenix")).toBe(false);
    expect(isTenantTodayISO("2026-02-16", "UTC")).toBe(true);
  });

  it("getTenantISODate accepts ISO strings + epoch millis", () => {
    const midnightUtc = new Date("2026-02-16T00:00:00Z");
    expect(getTenantISODate(midnightUtc, "America/Phoenix")).toBe("2026-02-15");
    expect(getTenantISODate(midnightUtc.toISOString(), "America/Phoenix"))
      .toBe("2026-02-15");
    expect(getTenantISODate(midnightUtc.getTime(), "America/Phoenix"))
      .toBe("2026-02-15");
  });
});


describe("TodaySchedule source no longer uses UTC for today", () => {
  it("TodaySchedule.jsx contains zero ``toISOString().slice(0, 10)`` calls", () => {
    const src = fs.readFileSync(
      path.resolve(
        __dirname,
        "..",
        "pages",
        "schedule",
        "TodaySchedule.jsx",
      ),
      "utf-8",
    );
    // Regex tolerates both "0, 10" and "0,10" spacings.
    expect(src).not.toMatch(/toISOString\(\)\.slice\(0\s*,\s*10\)/);
  });

  it("TodaySchedule.jsx imports the tenant-tz helper module", () => {
    const src = fs.readFileSync(
      path.resolve(
        __dirname,
        "..",
        "pages",
        "schedule",
        "TodaySchedule.jsx",
      ),
      "utf-8",
    );
    expect(src).toMatch(/from\s+["']@\/lib\/tenantTz["']/);
    expect(src).toMatch(/getTenantTodayISO/);
  });
});
