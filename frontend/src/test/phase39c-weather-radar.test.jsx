/**
 * Feb-2026 · P39c — WeatherWidget radar swap: Windy iframe →
 * NWS ridge/standard animated GIF.
 *
 * Coverage:
 *   1. Radar button hidden when radar.ok === false (no teasing an
 *      empty modal).
 *   2. Radar button rendered when radar.ok === true.
 *   3. Clicking the button opens the modal with an <img> tag
 *      whose src is loop_url.
 *   4. Alt text mentions the station code.
 *   5. Station caption below the img shows the code.
 *   6. Refresh button appends ``?t=<timestamp>`` to the img src.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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
  default: () => ({ ok: true, hourly: [] }),
}));


import WeatherWidget from "@/components/Weather/WeatherWidget";


function _daily() {
  return { ok: true, daily: [
    { date: "2026-06-01", high: 100, low: 75, chance_of_rain: 10,
      condition_text: "Sunny", condition_icon: "https://icon/0" },
  ]};
}


function _current() {
  return {
    ok: true,
    current: { temp_f: 92.5, condition_text: "Sunny",
                  condition_icon: "https://icon/x",
                  humidity: 20, wind_mph: 8, uv: 5 },
    location: { name: "KDVT", tz_id: "America/Phoenix" },
  };
}


function _installRouter({ radar } = {}) {
  mockGet.mockImplementation((path) => {
    const p = typeof path === "string" ? path : "";
    if (p.startsWith("/weather/current"))
      return Promise.resolve(_current());
    if (p.startsWith("/weather/daily"))
      return Promise.resolve(_daily());
    if (p.startsWith("/weather/alerts"))
      return Promise.resolve({ ok: true, alerts: [] });
    if (p.startsWith("/weather/radar"))
      return Promise.resolve(radar);
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


beforeEach(() => mockGet.mockReset());


describe("WeatherWidget · P39c NWS radar", () => {
  it("hides the Radar button when radar.ok === false", async () => {
    _installRouter({ radar: { ok: false, reason: "out_of_us" } });
    _mount();
    await waitFor(() =>
      expect(screen.getByTestId("weather-widget")).toBeTruthy());
    expect(screen.queryByTestId("weather-radar-open")).toBeNull();
  });

  it("renders the Radar button when radar.ok === true", async () => {
    _installRouter({ radar: {
      ok: true, provider: "nws", radar_station: "KIWA",
      loop_url: "https://radar.weather.gov/ridge/standard/KIWA_loop.gif",
      still_url: "https://radar.weather.gov/ridge/standard/KIWA_0.gif",
    }});
    _mount();
    await waitFor(() =>
      expect(screen.getByTestId("weather-radar-open")).toBeTruthy());
  });

  it("opens the modal with an <img> whose src is loop_url", async () => {
    _installRouter({ radar: {
      ok: true, provider: "nws", radar_station: "KIWA",
      loop_url: "https://radar.weather.gov/ridge/standard/KIWA_loop.gif",
      still_url: "https://radar.weather.gov/ridge/standard/KIWA_0.gif",
    }});
    _mount();
    const btn = await screen.findByTestId("weather-radar-open");
    fireEvent.click(btn);
    const img = await screen.findByTestId("weather-radar-img");
    expect(img.tagName).toBe("IMG");
    expect(img.getAttribute("src")).toBe(
      "https://radar.weather.gov/ridge/standard/KIWA_loop.gif");
  });

  it("alt text mentions the station code", async () => {
    _installRouter({ radar: {
      ok: true, provider: "nws", radar_station: "KIWA",
      loop_url: "https://radar.weather.gov/ridge/standard/KIWA_loop.gif",
      still_url: "https://radar.weather.gov/ridge/standard/KIWA_0.gif",
    }});
    _mount();
    const btn = await screen.findByTestId("weather-radar-open");
    fireEvent.click(btn);
    const img = await screen.findByTestId("weather-radar-img");
    expect(img.getAttribute("alt")).toMatch(/NEXRAD.*KIWA/);
  });

  it("station caption below the img shows the code", async () => {
    _installRouter({ radar: {
      ok: true, provider: "nws", radar_station: "KMPX",
      loop_url: "https://radar.weather.gov/ridge/standard/KMPX_loop.gif",
      still_url: "https://radar.weather.gov/ridge/standard/KMPX_0.gif",
    }});
    _mount();
    const btn = await screen.findByTestId("weather-radar-open");
    fireEvent.click(btn);
    const caption = await screen.findByTestId("weather-radar-station");
    expect(caption.textContent).toMatch(/NEXRAD radar station:\s*KMPX/);
  });

  it("refresh button appends a timestamp query param to the img src", async () => {
    _installRouter({ radar: {
      ok: true, provider: "nws", radar_station: "KIWA",
      loop_url: "https://radar.weather.gov/ridge/standard/KIWA_loop.gif",
      still_url: "https://radar.weather.gov/ridge/standard/KIWA_0.gif",
    }});
    _mount();
    const btn = await screen.findByTestId("weather-radar-open");
    fireEvent.click(btn);
    const imgBefore = await screen.findByTestId("weather-radar-img");
    expect(imgBefore.getAttribute("src")).toBe(
      "https://radar.weather.gov/ridge/standard/KIWA_loop.gif");
    fireEvent.click(screen.getByTestId("weather-radar-refresh"));
    await waitFor(() => {
      const img = screen.getByTestId("weather-radar-img");
      const src = img.getAttribute("src");
      expect(src).toMatch(
        /^https:\/\/radar\.weather\.gov\/ridge\/standard\/KIWA_loop\.gif\?t=\d+$/);
    });
  });
});
