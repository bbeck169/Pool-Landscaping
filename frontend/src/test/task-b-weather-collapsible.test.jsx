/**
 * Feb 2026 · Task B — WeatherWidget dashboard-compact mode.
 *
 * Contract:
 *   * When mounted with ``collapsible`` the widget renders only
 *     the current-conditions row plus a 3-button expand toolbar
 *     (Hourly / 7-Day / Radar).
 *   * Clicking a button reveals that view; only ONE expanded view
 *     can be active at a time.
 *   * Clicking the SAME button toggles back to the collapsed
 *     today-only state.
 *   * localStorage['weather.view'] is written on toggle
 *     and read on mount (default "collapsed" on first-ever load).
 *     Feb-2026 · Weather-bar reconciliation renamed the key from
 *     ``weather.view`` → ``weather.view``; migration
 *     fallback is covered in ``weather-bar-reconciliation.test.jsx``.
 *   * When ``collapsible`` is falsy (or omitted) every row still
 *     renders — /schedule stays unchanged.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";


// ─── api + hook mocks (hoisted) ──────────────────────────────────
const { mockApi, mockUseWeatherHourly, mockUseTenantLocation } = vi.hoisted(() => ({
  mockApi: { get: vi.fn(), post: vi.fn() },
  mockUseWeatherHourly: vi.fn(),
  mockUseTenantLocation: vi.fn(),
}));
vi.mock("@/api", () => ({ api: mockApi }));
vi.mock("@/hooks/useWeatherHourly", () => ({ default: mockUseWeatherHourly }));
vi.mock("@/hooks/useTenantLocation", () => ({ default: mockUseTenantLocation }));

// eslint-disable-next-line import/first
import WeatherWidget from "@/components/Weather/WeatherWidget";


const OK_CURRENT = {
  ok: true,
  current: { temp_f: 85, condition_text: "Sunny", humidity: 22, wind_mph: 6, wind_dir: "N", uv: 8 },
  location: { name: "Peoria, AZ" },
};
const OK_HOURLY = {
  ok: true,
  hourly: Array.from({ length: 6 }, (_, i) => ({
    time: `2026-02-15T${String(9 + i).padStart(2, "0")}:00:00`,
    temp_f: 80 + i,
    chance_of_rain: i * 5,
    condition_icon: null,
  })),
};
const OK_DAILY = {
  ok: true,
  daily: Array.from({ length: 7 }, (_, i) => ({
    date: `2026-02-${15 + i}`,
    high: 90 + i,
    low: 65 + i,
    chance_of_rain: i,
    condition_icon: null,
  })),
};
const OK_ALERTS = { ok: true, alerts: [] };
const OK_RADAR = { ok: true, loop_url: "https://example.com/radar.gif", radar_station: "KIWA" };


function _setupHappyPath() {
  mockUseWeatherHourly.mockReturnValue(OK_HOURLY);
  mockUseTenantLocation.mockReturnValue({ lat: 33.79, lon: -112.32 });
  mockApi.get.mockImplementation((path) => {
    if (path.includes("/weather/current")) return Promise.resolve(OK_CURRENT);
    if (path.includes("/weather/daily")) return Promise.resolve(OK_DAILY);
    if (path.includes("/weather/alerts")) return Promise.resolve(OK_ALERTS);
    if (path.includes("/weather/radar")) return Promise.resolve(OK_RADAR);
    return Promise.resolve({ ok: false });
  });
}


beforeEach(() => {
  mockApi.get.mockReset();
  mockUseWeatherHourly.mockReset();
  mockUseTenantLocation.mockReset();
  window.localStorage.clear();
  _setupHappyPath();
});

afterEach(() => {
  // noop
});


const admin = { id: "u1", role: "admin" };


describe("WeatherWidget · collapsible dashboard mode", () => {
  it("renders today-only by default (no hourly / 7-day / radar visible)", async () => {
    render(<WeatherWidget user={admin} collapsible />);
    // Current conditions row always visible.
    await waitFor(() =>
      expect(screen.getByTestId("weather-current-temp")).toBeInTheDocument(),
    );
    // Expand toolbar rendered.
    expect(screen.getByTestId("weather-expand-toolbar")).toBeInTheDocument();
    // Hourly, 7-day, radar all HIDDEN by default.
    expect(screen.queryByTestId("weather-hourly-strip")).not.toBeInTheDocument();
    expect(screen.queryByTestId("weather-5day-forecast")).not.toBeInTheDocument();
    expect(screen.queryByTestId("weather-radar-inline")).not.toBeInTheDocument();
  });

  it("renders all three toggle buttons in the toolbar", async () => {
    render(<WeatherWidget user={admin} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-expand-toolbar")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("weather-toggle-hourly")).toBeInTheDocument();
    expect(screen.getByTestId("weather-toggle-seven-day")).toBeInTheDocument();
    expect(screen.getByTestId("weather-toggle-radar")).toBeInTheDocument();
  });

  it("clicking Hourly reveals the hourly strip and hides the other views", async () => {
    render(<WeatherWidget user={admin} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-current-temp")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("weather-toggle-hourly"));
    await waitFor(() =>
      expect(screen.getByTestId("weather-hourly-strip")).toBeInTheDocument(),
    );
    // Other views stay hidden.
    expect(screen.queryByTestId("weather-5day-forecast")).not.toBeInTheDocument();
    expect(screen.queryByTestId("weather-radar-inline")).not.toBeInTheDocument();
  });

  it("clicking 7-Day reveals the 7-day forecast and hides hourly", async () => {
    render(<WeatherWidget user={admin} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-current-temp")).toBeInTheDocument(),
    );
    // Open Hourly first.
    fireEvent.click(screen.getByTestId("weather-toggle-hourly"));
    await waitFor(() =>
      expect(screen.getByTestId("weather-hourly-strip")).toBeInTheDocument(),
    );
    // Now flip to 7-Day.
    fireEvent.click(screen.getByTestId("weather-toggle-seven-day"));
    await waitFor(() =>
      expect(screen.getByTestId("weather-5day-forecast")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("weather-hourly-strip")).not.toBeInTheDocument();
    expect(screen.queryByTestId("weather-radar-inline")).not.toBeInTheDocument();
  });

  it("clicking Radar reveals the inline radar embed and hides other views", async () => {
    render(<WeatherWidget user={admin} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-current-temp")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("weather-toggle-radar"));
    await waitFor(() =>
      expect(screen.getByTestId("weather-radar-inline")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("weather-hourly-strip")).not.toBeInTheDocument();
    expect(screen.queryByTestId("weather-5day-forecast")).not.toBeInTheDocument();
  });

  it("clicking the same toggle again collapses back to today-only", async () => {
    render(<WeatherWidget user={admin} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-current-temp")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("weather-toggle-hourly"));
    await waitFor(() =>
      expect(screen.getByTestId("weather-hourly-strip")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("weather-toggle-hourly"));
    await waitFor(() =>
      expect(screen.queryByTestId("weather-hourly-strip")).not.toBeInTheDocument(),
    );
  });

  it("close button collapses whichever view is currently open", async () => {
    render(<WeatherWidget user={admin} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-current-temp")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("weather-toggle-seven-day"));
    await waitFor(() =>
      expect(screen.getByTestId("weather-5day-forecast")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("weather-collapse-btn"));
    await waitFor(() =>
      expect(screen.queryByTestId("weather-5day-forecast")).not.toBeInTheDocument(),
    );
  });

  it("persists the chosen view to localStorage['weather.view']", async () => {
    render(<WeatherWidget user={admin} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-current-temp")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("weather-toggle-radar"));
    await waitFor(() => {
      expect(window.localStorage.getItem("weather.view")).toBe("radar");
    });
    fireEvent.click(screen.getByTestId("weather-toggle-hourly"));
    await waitFor(() => {
      expect(window.localStorage.getItem("weather.view")).toBe("hourly");
    });
    fireEvent.click(screen.getByTestId("weather-collapse-btn"));
    await waitFor(() => {
      expect(window.localStorage.getItem("weather.view")).toBe("collapsed");
    });
  });

  it("hydrates the last-chosen view from localStorage on mount", async () => {
    window.localStorage.setItem("weather.view", "seven_day");
    render(<WeatherWidget user={admin} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-5day-forecast")).toBeInTheDocument(),
    );
    // Hourly and radar hidden (mutual exclusivity).
    expect(screen.queryByTestId("weather-hourly-strip")).not.toBeInTheDocument();
    expect(screen.queryByTestId("weather-radar-inline")).not.toBeInTheDocument();
  });

  it("ignores garbage localStorage values and falls back to collapsed", async () => {
    window.localStorage.setItem("weather.view", "totally-not-a-view");
    render(<WeatherWidget user={admin} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-current-temp")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("weather-hourly-strip")).not.toBeInTheDocument();
    expect(screen.queryByTestId("weather-5day-forecast")).not.toBeInTheDocument();
  });

  it("hides the row-1 Radar button in collapsible mode (radar lives in the toolbar)", async () => {
    render(<WeatherWidget user={admin} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-expand-toolbar")).toBeInTheDocument(),
    );
    // Row-1 modal radar button not rendered under collapsible mode.
    expect(screen.queryByTestId("weather-radar-open")).not.toBeInTheDocument();
  });
});


describe("WeatherWidget · non-collapsible (default) mode", () => {
  it("renders every row without expand toolbar when collapsible is false", async () => {
    render(<WeatherWidget user={admin} />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-current-temp")).toBeInTheDocument(),
    );
    // Toolbar is NOT rendered.
    expect(screen.queryByTestId("weather-expand-toolbar")).not.toBeInTheDocument();
    // All rows visible by default (original behaviour).
    expect(screen.getByTestId("weather-hourly-strip")).toBeInTheDocument();
    expect(screen.getByTestId("weather-5day-forecast")).toBeInTheDocument();
    // Row-1 Radar modal button still present.
    expect(screen.getByTestId("weather-radar-open")).toBeInTheDocument();
  });

  it("does not write to localStorage in non-collapsible mode", async () => {
    render(<WeatherWidget user={admin} />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-current-temp")).toBeInTheDocument(),
    );
    expect(window.localStorage.getItem("weather.view")).toBeNull();
  });
});


describe("WeatherWidget · radar-unavailable graceful degrade", () => {
  it("disables the Radar toggle when the radar endpoint reports ok:false", async () => {
    mockApi.get.mockImplementation((path) => {
      if (path.includes("/weather/current")) return Promise.resolve(OK_CURRENT);
      if (path.includes("/weather/daily")) return Promise.resolve(OK_DAILY);
      if (path.includes("/weather/alerts")) return Promise.resolve(OK_ALERTS);
      if (path.includes("/weather/radar")) return Promise.resolve({ ok: false });
      return Promise.resolve({ ok: false });
    });
    render(<WeatherWidget user={admin} collapsible />);
    await waitFor(() =>
      expect(screen.getByTestId("weather-current-temp")).toBeInTheDocument(),
    );
    const radarBtn = screen.getByTestId("weather-toggle-radar");
    expect(radarBtn).toBeDisabled();
  });
});
