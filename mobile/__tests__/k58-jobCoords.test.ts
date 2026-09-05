/**
 * K58 · Feb-2026 — Mobile shared coord-resolver ladder assertions.
 *
 * Guards ``mobile/src/utils/jobCoords.ts::resolveJobCoords`` against
 * ladder-order regressions.  Slice B of Phase K58 (Mobile Schedule
 * Map empty-state fix).
 *
 * Also asserts the parity contract: BOTH ``ScheduleMap.native.tsx``
 * AND ``DailyRouteMap.native.tsx`` import ``resolveJobCoords`` from
 * the shared helper — no per-component drift allowed.
 *
 * See /app/memory/PHASE_K58_MAP_COORD_LADDER.md.
 */
import fs from "fs";
import path from "path";
import { resolveJobCoords, jobHasCoords } from "@/src/utils/jobCoords";

describe("K58 · Slice B — resolveJobCoords ladder", () => {
  it("Rung 1 — location_lat/lng wins over all lower rungs", () => {
    const job = {
      location_lat: 1.0, location_lng: 1.0,
      latitude: 2.0, longitude: 2.0,
      site_lat: 3.0, site_lng: 3.0,
      property: { location: { lat: 4.0, lng: 4.0 } },
    };
    expect(resolveJobCoords(job)).toEqual({ lat: 1.0, lng: 1.0 });
  });

  it("Rung 2 — latitude/longitude wins when location_* is absent", () => {
    const job = {
      latitude: 2.0, longitude: 2.0,
      site_lat: 3.0, site_lng: 3.0,
      property: { location: { lat: 4.0, lng: 4.0 } },
    };
    expect(resolveJobCoords(job)).toEqual({ lat: 2.0, lng: 2.0 });
  });

  it("Rung 3 — site_lat/lng wins when location_* + latitude are absent", () => {
    const job = {
      site_lat: 3.0, site_lng: 3.0,
      property: { location: { lat: 4.0, lng: 4.0 } },
    };
    expect(resolveJobCoords(job)).toEqual({ lat: 3.0, lng: 3.0 });
  });

  it("Rung 4 — property.location.{lat,lng} wins when no job-level coord", () => {
    const job = { property: { location: { lat: 4.0, lng: 4.0 } } };
    expect(resolveJobCoords(job)).toEqual({ lat: 4.0, lng: 4.0 });
  });

  it("returns null when every rung is null / undefined / absent", () => {
    expect(resolveJobCoords({})).toBeNull();
    expect(resolveJobCoords(null)).toBeNull();
    expect(resolveJobCoords(undefined)).toBeNull();
    expect(resolveJobCoords({
      location_lat: null, location_lng: null,
      latitude: undefined, longitude: undefined,
    })).toBeNull();
  });

  it("treats the (0, 0) null-island coord pair as absent (falls through to next rung)", () => {
    const job = {
      location_lat: 0, location_lng: 0,
      latitude: 5.0, longitude: 5.0,
    };
    expect(resolveJobCoords(job)).toEqual({ lat: 5.0, lng: 5.0 });
  });

  it("rejects non-finite coord values (NaN, Infinity)", () => {
    expect(resolveJobCoords({ location_lat: NaN, location_lng: 1 })).toBeNull();
    expect(resolveJobCoords({ location_lat: 1, location_lng: NaN })).toBeNull();
    expect(resolveJobCoords({ location_lat: Infinity, location_lng: 1 })).toBeNull();
  });

  it("accepts string-typed coord values that Number() can parse (legacy DB rows)", () => {
    const job = { location_lat: "1.5", location_lng: "2.5" };
    expect(resolveJobCoords(job as any)).toEqual({ lat: 1.5, lng: 2.5 });
  });

  it("tolerates ``property.location.lon`` (spelling variant) as an alternative to ``.lng``", () => {
    const job = { property: { location: { lat: 4.0, lon: 4.0 } } };
    expect(resolveJobCoords(job as any)).toEqual({ lat: 4.0, lng: 4.0 });
  });

  it("jobHasCoords is equivalent to resolveJobCoords(...) !== null", () => {
    expect(jobHasCoords({ location_lat: 1, location_lng: 1 })).toBe(true);
    expect(jobHasCoords({})).toBe(false);
    expect(jobHasCoords(null)).toBe(false);
  });
});

describe("K58 · Slice B parity — both map components use the shared helper", () => {
  const SCHEDULE_MAP = path.resolve(__dirname, "../src/components/schedule/ScheduleMap.native.tsx");
  const DAILY_ROUTE_MAP = path.resolve(__dirname, "../src/components/schedule/DailyRouteMap.native.tsx");

  it("ScheduleMap.native.tsx imports resolveJobCoords from @/src/utils/jobCoords", () => {
    const src = fs.readFileSync(SCHEDULE_MAP, "utf8");
    expect(src).toMatch(/from\s+["']@\/src\/utils\/jobCoords["']/);
    expect(src).toMatch(/\bresolveJobCoords\b/);
  });

  it("DailyRouteMap.native.tsx imports (or re-exports) resolveJobCoords from the shared helper", () => {
    const src = fs.readFileSync(DAILY_ROUTE_MAP, "utf8");
    expect(src).toMatch(/from\s+["']@\/src\/utils\/jobCoords["']/);
  });

  it("ScheduleMap.native.tsx no longer contains the pre-K58 strict-flat predicate", () => {
    // The pre-K58 code was:
    //   jobs.filter((j) => j.location_lat != null && j.location_lng != null)
    // K58 replaces that with the shared helper.  Regression guard —
    // if this ever comes back, ScheduleMap will silently ignore all
    // the non-``location_*`` coord shapes the ladder now exposes.
    const src = fs.readFileSync(SCHEDULE_MAP, "utf8");
    expect(src).not.toMatch(/j\.location_lat\s*!=\s*null\s*&&\s*j\.location_lng\s*!=\s*null/);
  });
});
