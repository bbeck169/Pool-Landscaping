/**
 * feat(mobile-calendar): schedule card redesign — NavigateJobButton removal,
 * name+address open native map, resolveJobCoords extraction.
 */
import * as fs from "fs";
import * as path from "path";
import { resolveJobCoords } from "../src/utils/nativeNav";

const CALENDAR_PATH = path.resolve(
  __dirname,
  "../app/(app)/schedule/calendar.tsx",
);

describe("resolveJobCoords", () => {
  it("resolves canonical latitude/longitude", () => {
    expect(resolveJobCoords({ latitude: 33.45, longitude: -112.07 })).toEqual({
      lat: 33.45,
      lng: -112.07,
    });
  });

  it("falls back to location_lat/location_lng", () => {
    expect(
      resolveJobCoords({ location_lat: 40.71, location_lng: -74.01 }),
    ).toEqual({ lat: 40.71, lng: -74.01 });
  });

  it("returns null for (0, 0) sentinel", () => {
    expect(resolveJobCoords({ latitude: 0, longitude: 0 })).toBeNull();
  });

  it("returns null for non-finite coords", () => {
    expect(resolveJobCoords({ latitude: NaN, longitude: Infinity })).toBeNull();
    expect(resolveJobCoords({ latitude: "abc", longitude: "def" })).toBeNull();
  });

  it("returns null for missing job or fields", () => {
    expect(resolveJobCoords(null)).toBeNull();
    expect(resolveJobCoords(undefined)).toBeNull();
    expect(resolveJobCoords({})).toBeNull();
  });

  it("prefers canonical over legacy when both present", () => {
    const job = {
      latitude: 10,
      longitude: 20,
      location_lat: 30,
      location_lng: 40,
    };
    expect(resolveJobCoords(job)).toEqual({ lat: 10, lng: 20 });
  });
});

describe("calendar card redesign — source inspection", () => {
  let source: string;

  beforeAll(() => {
    source = fs.readFileSync(CALENDAR_PATH, "utf-8");
  });

  it("does NOT import NavigateJobButton", () => {
    expect(source).not.toMatch(
      /import\s+NavigateJobButton\s+from/,
    );
  });

  it("does NOT render <NavigateJobButton", () => {
    expect(source).not.toMatch(/<NavigateJobButton/);
  });

  it("imports resolveJobCoords from nativeNav", () => {
    expect(source).toMatch(/import\s*\{[^}]*resolveJobCoords[^}]*\}\s*from\s*["']@\/src\/utils\/nativeNav["']/);
  });

  it("imports openNativeNavTo from nativeNav", () => {
    expect(source).toMatch(/import\s*\{[^}]*openNativeNavTo[^}]*\}\s*from\s*["']@\/src\/utils\/nativeNav["']/);
  });

  it("has name-tap Pressable with testID job-card-name-nav-", () => {
    expect(source).toMatch(/testID=\{`job-card-name-nav-\$\{job\.id\}`\}/);
  });

  it("has address-tap Pressable with testID job-card-addr-nav-", () => {
    expect(source).toMatch(/testID=\{`job-card-addr-nav-\$\{job\.id\}`\}/);
  });

  it("address style uses fontSize.base (not fontSize.xs)", () => {
    expect(source).toMatch(/addr:.*fontSize:\s*fontSize\.base/);
  });
});
