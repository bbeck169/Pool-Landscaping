/**
 * Feb-2026 · P39b — WeatherWidget alerts banner + 7-day + UV null.
 *
 * Coverage:
 *   1. Alerts banner renders when getAlerts returns rows.
 *   2. Expand pill shows the hidden alerts inline.
 *   3. Banner NOT rendered when alerts.ok === false.
 *   4. Severity coloring pinned:
 *        Extreme + Severe → red   (bg #FEE2E2)
 *        Moderate         → amber (bg #FEF3C7)
 *        Minor + Unknown  → slate (bg #E2E8F0)
 *   5. 7 daily cells rendered when daily.daily.length === 7.
 *   6. UV null → renders "—" text (row remains visible).
 *   7. Alerts fetch rejection → widget still renders current + daily.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const mockGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("@/hooks/useTenantLocation", () => ({
  default: () => ({ lat: 33.5806, lon: -112.2374 }),
}));

vi.mock("@/hooks/useWeatherHourly", () => ({
  default: () => ({ ok: true, hourly: [
    { time: "2026-06-01 12:00", temp_f: 92, chance_of_rain: 10 },
    { time: "2026-06-01 13:00", temp_f: 94, chance_of_rain: 10 },
  ]}),
}));


import WeatherWidget from "@/components/Weather/WeatherWidget";


function _daily(n = 7) {
  const rows = [];
  for (let i = 0; i < n; i++) {
    rows.push({
      date: `2026-06-0${i + 1}`,
      high: 100 + i, low: 75 + i,
      chance_of_rain: 10 + i,
      condition_text: "Sunny",
      condition_icon: `https://icon/${i}`,
    });
  }
  return { ok: true, daily: rows };
}


function _currentPayload({ uv = 5 } = {}) {
  return {
    ok: true,
    current: {
      temp_f: 92.5, condition_text: "Sunny",
      condition_icon: "https://icon/current",
      humidity: 20, wind_mph: 8, wind_dir: "NW", uv,
    },
    location: { name: "KDVT", tz_id: "America/Phoenix" },
  };
}


function _installRouter({ current, daily, alerts } = {}) {
  mockGet.mockImplementation((path) => {
    if (path.startsWith("/weather/current"))
      return Promise.resolve(current ?? _currentPayload());
    if (path.startsWith("/weather/daily"))
      return Promise.resolve(daily ?? _daily(7));
    if (path.startsWith("/weather/alerts"))
      return Promise.resolve(alerts ?? { ok: true, alerts: [] });
    return Promise.resolve({});
  });
}


function _mount() {
  return render(
    <MemoryRouter>
      <WeatherWidget user={{ role: "admin" }} />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  mockGet.mockReset();
});


describe("WeatherWidget · P39b alerts banner + 7-day + UV null", () => {
  it("renders alerts banner with two alerts collapsed then expandable", async () => {
    _installRouter({
      alerts: { ok: true, alerts: [
        { event: "Freeze Warning", severity: "Moderate",
          headline: "Freeze Warning in effect", expires_at: "2026-11-15T16:00:00+00:00",
          url: "u1" },
        { event: "High Wind Advisory", severity: "Minor",
          headline: "High Wind Advisory", expires_at: "2026-11-15T22:00:00+00:00",
          url: "u2" },
      ]},
    });
    _mount();
    await waitFor(() =>
      expect(screen.getByTestId("weather-alerts-banner")).toBeTruthy());
    // First alert visible; second collapsed behind "and 1 more".
    expect(screen.getByTestId("weather-alert-item-0")).toBeTruthy();
    expect(screen.queryByTestId("weather-alert-item-1")).toBeNull();
    const pill = screen.getByTestId("weather-alerts-more-pill");
    expect(pill.textContent).toMatch(/and\s+1\s+more/i);
    fireEvent.click(pill);
    await waitFor(() =>
      expect(screen.getByTestId("weather-alert-item-1")).toBeTruthy());
  });

  it("does not render the banner when alerts.ok === false", async () => {
    _installRouter({
      alerts: { ok: false, reason: "out_of_us" },
    });
    _mount();
    // Wait for the widget to settle (weather-widget mount).
    await waitFor(() =>
      expect(screen.getByTestId("weather-widget")).toBeTruthy());
    expect(screen.queryByTestId("weather-alerts-banner")).toBeNull();
  });

  it("severity coloring: Extreme + Severe → red", async () => {
    _installRouter({
      alerts: { ok: true, alerts: [
        { event: "Extreme Heat", severity: "Extreme", headline: "H1", expires_at: null },
      ]},
    });
    _mount();
    const banner = await screen.findByTestId("weather-alerts-banner");
    // #FEE2E2 = rgb(254, 226, 226) — red-tinted.
    expect(banner.style.background).toMatch(/254.*226.*226|#fee2e2/i);
  });

  it("severity coloring: Moderate → amber", async () => {
    _installRouter({
      alerts: { ok: true, alerts: [
        { event: "Freeze", severity: "Moderate", headline: "H", expires_at: null },
      ]},
    });
    _mount();
    const banner = await screen.findByTestId("weather-alerts-banner");
    // #FEF3C7 = rgb(254, 243, 199).
    expect(banner.style.background).toMatch(/254.*243.*199|#fef3c7/i);
  });

  it("severity coloring: Minor/Unknown → slate", async () => {
    _installRouter({
      alerts: { ok: true, alerts: [
        { event: "Air Quality", severity: "Unknown", headline: "H", expires_at: null },
      ]},
    });
    _mount();
    const banner = await screen.findByTestId("weather-alerts-banner");
    // #E2E8F0 = rgb(226, 232, 240).
    expect(banner.style.background).toMatch(/226.*232.*240|#e2e8f0/i);
  });

  it("renders 7 daily cells when daily.daily.length === 7", async () => {
    _installRouter({ daily: _daily(7) });
    _mount();
    // First cell renders after settle.
    await waitFor(() =>
      expect(screen.getByTestId("weather-day-0")).toBeTruthy());
    // All 7 cells present, 8th absent.
    for (let i = 0; i < 7; i++) {
      expect(screen.getByTestId(`weather-day-${i}`)).toBeTruthy();
    }
    expect(screen.queryByTestId("weather-day-7")).toBeNull();
  });

  it("UV null renders '—' and does not hide the UV row", async () => {
    _installRouter({ current: _currentPayload({ uv: null }) });
    _mount();
    const uv = await screen.findByTestId("weather-current-uv");
    expect(uv.textContent).toMatch(/UV\s+—/);
  });

  it("alerts fetch rejection still renders current + daily", async () => {
    mockGet.mockImplementation((path) => {
      if (path.startsWith("/weather/current"))
        return Promise.resolve(_currentPayload());
      if (path.startsWith("/weather/daily"))
        return Promise.resolve(_daily(7));
      if (path.startsWith("/weather/alerts"))
        return Promise.reject(new Error("network down"));
      return Promise.resolve({});
    });
    _mount();
    // Widget mounts; alerts banner is absent; daily strip present.
    await waitFor(() =>
      expect(screen.getByTestId("weather-widget")).toBeTruthy());
    expect(screen.queryByTestId("weather-alerts-banner")).toBeNull();
    expect(screen.getByTestId("weather-day-0")).toBeTruthy();
    expect(screen.getByTestId("weather-current-temp")).toBeTruthy();
  });
});
