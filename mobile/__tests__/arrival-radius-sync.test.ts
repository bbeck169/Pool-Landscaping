/**
 * Arrival-radius sync — locks the mobile arrival-radius constants
 * to 75m, matching the server's DEFAULT_ARRIVAL_RADIUS_M in
 * backend/routers/gps_auto_start.py.
 */

describe("Mobile arrival radius constants", () => {
  it("JobTimerCard ARRIVE_RADIUS_M equals server (75m)", () => {
    // The constant is module-private so we read the source to verify.
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../src/components/job/JobTimerCard.tsx"),
      "utf8",
    );
    const match = src.match(/const ARRIVE_RADIUS_M\s*=\s*(\d+)/);
    expect(match).not.toBeNull();
    expect(Number(match![1])).toBe(75);
  });

  // β-core commit 1 — the dead `src/geofence.ts` (legacy `job-arrival-geofence`
  // task, zero importers) was removed; the live arrival-geofence owner is
  // `src/background/jobGeofence.ts` (radius locked below).
  it("legacy src/geofence.ts stays deleted (single arrival-geofence owner)", () => {
    const fs = require("fs");
    const path = require("path");
    expect(fs.existsSync(path.resolve(__dirname, "../src/geofence.ts"))).toBe(false);
  });

  it("jobGeofence.ts FALLBACK_RADIUS_M equals server (75m)", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../src/background/jobGeofence.ts"),
      "utf8",
    );
    const match = src.match(/const FALLBACK_RADIUS_M\s*=\s*(\d+)/);
    expect(match).not.toBeNull();
    expect(Number(match![1])).toBe(75);
  });
});
