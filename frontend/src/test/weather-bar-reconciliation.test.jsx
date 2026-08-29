/**
 * Feb-2026 · Weather-bar reconciliation — Schedule page now mounts
 * the shared WeatherWidget with ``collapsible`` (matches Dashboard
 * density).
 *
 * Locks:
 *   1. When mounted with ``collapsible``, the expand toolbar
 *      (data-testid="weather-expand-toolbar") IS rendered.
 *   2. When mounted with ``collapsible`` AND the default view is
 *      "collapsed" (no LS pref), the always-visible 24h hourly
 *      strip (data-testid="weather-hourly-strip") is NOT rendered.
 *   3. When mounted WITHOUT ``collapsible`` (legacy behaviour, used
 *      to be Schedule pre-reconciliation), the hourly strip IS
 *      rendered and the expand toolbar is NOT.
 *   4. Persistence-key migration — seeding the legacy
 *      ``dashboard.weatherView`` key with a valid value causes the
 *      component to (a) adopt that view on first mount and
 *      (b) write it under the new key ``weather.view`` so
 *      subsequent reads short-circuit the migration.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";


// ── mocks ──────────────────────────────────────────────────────
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/weather/current")) {
        return {
          ok: true,
          current: {
            temp_f: 106, condition_text: "Sunny", humidity: 22,
            wind_mph: 8, wind_dir: "SW", uv: 11,
            condition_icon: "https://cdn.example/sun.png",
          },
          location: { name: "Peoria" },
        };
      }
      if (path.startsWith("/weather/daily")) {
        return {
          ok: true,
          daily: [
            { date: "2026-02-13", high: 108, low: 84, chance_of_rain: 0,
              condition_icon: "https://cdn.example/sun.png" },
            { date: "2026-02-14", high: 106, low: 82, chance_of_rain: 5,
              condition_icon: "https://cdn.example/sun.png" },
          ],
        };
      }
      if (path.startsWith("/weather/alerts")) return { ok: true, alerts: [] };
      if (path.startsWith("/weather/radar")) {
        return { ok: true, loop_url: "https://ridge.example/loop.gif",
                 radar_station: "KIWA" };
      }
      return { ok: false };
    }),
  },
}));

vi.mock("@/hooks/useTenantLocation", () => ({
  default: () => ({ lat: 33.7897, lon: -112.3226 }),
}));

vi.mock("@/hooks/useWeatherHourly", () => ({
  default: () => ({
    ok: true,
    hourly: [
      { time: "2026-02-13T09:00:00-07:00", temp_f: 90,
        chance_of_rain: 0, condition_icon: "https://cdn.example/sun.png" },
      { time: "2026-02-13T10:00:00-07:00", temp_f: 95,
        chance_of_rain: 0, condition_icon: "https://cdn.example/sun.png" },
    ],
  }),
}));


import WeatherWidget from "@/components/Weather/WeatherWidget";


const _adminUser = { id: "u-admin", role: "admin", email: "a@x", name: "A" };


beforeEach(() => {
  try {
    window.localStorage.removeItem("weather.view");
    window.localStorage.removeItem("dashboard.weatherView");
  } catch { /* jsdom */ }
});
afterEach(() => cleanup());


describe("WeatherWidget · collapsible prop (Schedule ↔ Dashboard parity)", () => {
  it("with collapsible=true, renders the expand toolbar", async () => {
    render(<WeatherWidget user={_adminUser} collapsible />);
    // Widget hydrates once the mocked /weather/* promises resolve.
    await waitFor(() =>
      expect(screen.getByTestId("weather-widget")).toBeTruthy(),
    );
    expect(screen.getByTestId("weather-expand-toolbar")).toBeTruthy();
    expect(screen.getByTestId("weather-toggle-hourly")).toBeTruthy();
    expect(screen.getByTestId("weather-toggle-seven-day")).toBeTruthy();
    expect(screen.getByTestId("weather-toggle-radar")).toBeTruthy();
  });

  it("with collapsible=true + default 'collapsed' view, NO always-visible hourly strip", async () => {
    render(<WeatherWidget user={_adminUser} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-widget")).toBeTruthy(),
    );
    // Neither the hourly nor the 7-day strip is painted while view
    // is "collapsed" — that's the whole point of the compact mode.
    expect(screen.queryByTestId("weather-hourly-strip")).toBeNull();
    expect(screen.queryByTestId("weather-5day-forecast")).toBeNull();
  });

  it("without collapsible, the legacy always-visible hourly strip renders + toolbar is absent", async () => {
    render(<WeatherWidget user={_adminUser} />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-widget")).toBeTruthy(),
    );
    expect(screen.getByTestId("weather-hourly-strip")).toBeTruthy();
    // Legacy caller (pre-reconciliation) never got the expand
    // toolbar — locked so an accidental default flip is caught.
    expect(screen.queryByTestId("weather-expand-toolbar")).toBeNull();
  });
});


describe("WeatherWidget · localStorage migration (dashboard.weatherView → weather.view)", () => {
  it("adopts legacy 'dashboard.weatherView' on first mount when new key is absent", async () => {
    // Seed ONLY the legacy key. Reconciliation must pick it up and
    // (a) open the corresponding panel and (b) write the new key.
    window.localStorage.setItem("dashboard.weatherView", "seven_day");

    render(<WeatherWidget user={_adminUser} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-widget")).toBeTruthy(),
    );
    // (a) — 7-day panel visible (view === "seven_day").
    await waitFor(() =>
      expect(screen.getByTestId("weather-5day-forecast")).toBeTruthy(),
    );
    // (b) — new key populated with the migrated value.
    expect(window.localStorage.getItem("weather.view")).toBe("seven_day");
    // Toggle chip reflects the active state via aria-pressed.
    expect(
      screen.getByTestId("weather-toggle-seven-day").getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("new key wins over legacy key when BOTH are set (no migration needed)", async () => {
    window.localStorage.setItem("dashboard.weatherView", "seven_day");
    window.localStorage.setItem("weather.view", "hourly");

    render(<WeatherWidget user={_adminUser} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-widget")).toBeTruthy(),
    );
    // Hourly won — new key beats legacy.
    expect(screen.getByTestId("weather-hourly-strip")).toBeTruthy();
    expect(screen.queryByTestId("weather-5day-forecast")).toBeNull();
    // New key untouched.
    expect(window.localStorage.getItem("weather.view")).toBe("hourly");
  });

  it("invalid legacy value falls through to the default 'collapsed' view", async () => {
    window.localStorage.setItem("dashboard.weatherView", "banana");
    render(<WeatherWidget user={_adminUser} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-widget")).toBeTruthy(),
    );
    // Neither panel opened.
    expect(screen.queryByTestId("weather-hourly-strip")).toBeNull();
    expect(screen.queryByTestId("weather-5day-forecast")).toBeNull();
    expect(screen.queryByTestId("weather-radar-inline")).toBeNull();
    // Migration did NOT stamp a bogus value under the new key.
    expect(window.localStorage.getItem("weather.view")).toBeNull();
  });
});
