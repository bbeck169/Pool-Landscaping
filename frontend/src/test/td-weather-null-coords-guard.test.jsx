/**
 * TD-weather-null-coords-guard · Feb-2026
 *
 * Production logs showed /api/weather/{current,daily,alerts,radar,hourly}
 * being called with the literal string ``lat=null&lon=null`` as query
 * params, which the BE Pydantic validator correctly 422s.
 *
 * Root cause: a hypothetical caller that passes JS ``null`` (or
 * ``undefined``) into a template literal interpolates the string
 * "null"/"undefined" rather than skipping the fetch.  The current
 * WeatherWidget `?? DEFAULT_LAT` fallback should keep lat/lon numeric,
 * but the guard here is belt-and-braces so a future refactor can't
 * silently re-introduce the leak.
 *
 * This suite uses source-inspection (readFileSync + regex) so no
 * Stripe/Mongo/etc. mocks are required — same pattern as the
 * ``phase47c-add-card-restore`` and
 * ``td-portal-add-card-disable-stripe-link`` guards.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const WEATHER_WIDGET = resolve(
  __dirname,
  "../components/Weather/WeatherWidget.jsx",
);
const USE_WEATHER_HOURLY = resolve(
  __dirname,
  "../hooks/useWeatherHourly.js",
);

describe("TD-weather-null-coords-guard · WeatherWidget", () => {
  const src = readFileSync(WEATHER_WIDGET, "utf8");

  it("load() returns early when lat is null/undefined", () => {
    // Must guard inside the ``load`` callback body with a check that
    // covers both null and undefined (``== null`` is the canonical
    // one-liner for both).
    expect(src).toMatch(
      /const\s+load\s*=\s*React\.useCallback\s*\(\s*async\s*\(\s*\)\s*=>\s*\{[\s\S]*?lat\s*==\s*null[\s\S]*?lon\s*==\s*null[\s\S]*?return/,
    );
  });

  it("ticket reference is anchored in the file", () => {
    expect(src).toContain("TD-weather-null-coords-guard");
  });

  it("still calls the five weather endpoints when lat/lon are valid", () => {
    // Regression — the fetch call sites themselves must still exist
    // so a careless edit cannot delete the whole load() body under
    // the pretense of "guard shipped".
    expect(src).toMatch(/\/weather\/current\?lat=\$\{lat\}&lon=\$\{lon\}/);
    expect(src).toMatch(/\/weather\/daily\?lat=\$\{lat\}&lon=\$\{lon\}/);
    expect(src).toMatch(/\/weather\/alerts\?lat=\$\{lat\}&lon=\$\{lon\}/);
    expect(src).toMatch(/\/weather\/radar\?lat=\$\{lat\}&lon=\$\{lon\}/);
  });
});

describe("TD-weather-null-coords-guard · useWeatherHourly", () => {
  const src = readFileSync(USE_WEATHER_HOURLY, "utf8");

  it("_fetch() returns early when lat is null/undefined", () => {
    expect(src).toMatch(
      /async\s+function\s+_fetch\s*\(\s*lat\s*,\s*lon\s*\)\s*\{[\s\S]*?lat\s*==\s*null[\s\S]*?lon\s*==\s*null[\s\S]*?return/,
    );
  });

  it("hook-level ``enabled && lat != null && lon != null`` key guard stays", () => {
    // Pre-existing guard — must not be weakened by this ticket.
    expect(src).toMatch(
      /const\s+key\s*=\s*enabled\s*&&\s*lat\s*!=\s*null\s*&&\s*lon\s*!=\s*null/,
    );
  });

  it("ticket reference is anchored in the file", () => {
    expect(src).toContain("TD-weather-null-coords-guard");
  });

  it("still calls /weather/hourly when lat/lon are valid", () => {
    expect(src).toMatch(
      /\/weather\/hourly\?lat=\$\{lat\}&lon=\$\{lon\}&hours=24/,
    );
  });
});
