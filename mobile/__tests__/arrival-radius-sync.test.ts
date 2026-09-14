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

  it("geofence.ts RADIUS_M equals server (75m)", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../src/geofence.ts"),
      "utf8",
    );
    const match = src.match(/const RADIUS_M\s*=\s*(\d+)/);
    expect(match).not.toBeNull();
    expect(Number(match![1])).toBe(75);
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
