/**
 * Feb-2026 · P39b — mobile WeatherWidget alerts + 7-day + UV null.
 */
import React from "react";
import { render, act, waitFor, fireEvent } from "@testing-library/react-native";

const mockFetchTenantLocation = jest.fn();
const mockFetchCurrent = jest.fn();
const mockFetchHourly = jest.fn();
const mockFetchDaily = jest.fn();
const mockFetchRadar = jest.fn();
const mockFetchAlerts = jest.fn();

jest.mock("@/src/api/weather", () => ({
  fetchTenantLocation: (...a: any[]) => mockFetchTenantLocation(...a),
  fetchCurrentWeather: (...a: any[]) => mockFetchCurrent(...a),
  fetchHourlyWeather: (...a: any[]) => mockFetchHourly(...a),
  fetchDailyWeather: (...a: any[]) => mockFetchDaily(...a),
  fetchWeatherRadar: (...a: any[]) => mockFetchRadar(...a),
  fetchWeatherAlerts: (...a: any[]) => mockFetchAlerts(...a),
}));

jest.mock("react-native-webview", () => ({ WebView: () => null }));

jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));

jest.mock("@/src/theme", () => ({
  colors: { bg: "#000", card: "#111", surface: "#222", surfaceHover: "#333",
             border: "#444", brand: "#0af", brandTertiary: "#0af",
             text: "#fff", muted: "#888", danger: "#f00", ok: "#0f0",
             warn: "#fa0", info: "#0af", success: "#0f0", onSurface: "#fff",
             onSurfaceMuted: "#aaa" },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, "2xl": 24, "3xl": 32 },
  radius: { sm: 4, md: 8, lg: 12, xl: 16 },
  font: { regular: "System", medium: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, md: 14, lg: 16, xl: 20 },
}));


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


function _current({ uv = 5 }: { uv?: number | null } = {}) {
  return {
    ok: true,
    temp_f: 92.5,
    condition: "Sunny",
    high: 100, low: 75,
    humidity: 20, wind_mph: 8,
    uv,
    icon: "https://icon/current",
  };
}


beforeEach(() => {
  mockFetchTenantLocation.mockReset();
  mockFetchCurrent.mockReset();
  mockFetchHourly.mockReset();
  mockFetchDaily.mockReset();
  mockFetchRadar.mockReset();
  mockFetchAlerts.mockReset();
  mockFetchTenantLocation.mockResolvedValue({ hq_lat: 33.5806, hq_lng: -112.2374 });
  mockFetchCurrent.mockResolvedValue(_current());
  mockFetchHourly.mockResolvedValue({ ok: true, hourly: [] });
  mockFetchDaily.mockResolvedValue(_daily(7));
  mockFetchAlerts.mockResolvedValue({ ok: true, alerts: [] });
  // Feb-2026 · P39c — radar is now pre-fetched by loadAll; default
  // to ok:false so the Radar button is hidden in tests that don't
  // set an explicit radar payload.
  mockFetchRadar.mockResolvedValue({ ok: false, reason: "out_of_us" });
});


describe("Mobile WeatherWidget · P39b alerts + 7-day + UV null", () => {
  it("renders alerts banner + expandable more pill", async () => {
    mockFetchAlerts.mockResolvedValue({ ok: true, alerts: [
      { event: "Freeze Warning", severity: "Moderate",
        headline: "Freeze Warning in effect", expires_at: "2026-11-15T16:00:00+00:00",
        url: "u1" },
      { event: "High Wind Advisory", severity: "Minor",
        headline: "High Wind Advisory", expires_at: "2026-11-15T22:00:00+00:00",
        url: "u2" },
    ]});
    const WeatherWidget = require("../src/components/weather/WeatherWidget").default;
    const utils = render(<WeatherWidget />);
    const banner = await utils.findByTestId("mobile-weather-alerts-banner");
    expect(banner).toBeTruthy();
    // First alert visible; second collapsed.
    expect(utils.getByTestId("mobile-weather-alert-item-0")).toBeTruthy();
    expect(utils.queryByTestId("mobile-weather-alert-item-1")).toBeNull();
    const pill = utils.getByTestId("mobile-weather-alerts-more-pill");
    await act(async () => { fireEvent.press(pill); });
    await waitFor(() =>
      expect(utils.getByTestId("mobile-weather-alert-item-1")).toBeTruthy());
  });

  it("banner not rendered when alerts.ok === false", async () => {
    mockFetchAlerts.mockResolvedValue({ ok: false, reason: "out_of_us" });
    const WeatherWidget = require("../src/components/weather/WeatherWidget").default;
    const utils = render(<WeatherWidget />);
    await utils.findByTestId("weather-widget");
    expect(utils.queryByTestId("mobile-weather-alerts-banner")).toBeNull();
  });

  it("severity coloring: Extreme → red banner", async () => {
    mockFetchAlerts.mockResolvedValue({ ok: true, alerts: [
      { event: "Extreme Heat", severity: "Extreme", headline: "H", expires_at: null },
    ]});
    const WeatherWidget = require("../src/components/weather/WeatherWidget").default;
    const utils = render(<WeatherWidget />);
    const banner = await utils.findByTestId("mobile-weather-alerts-banner");
    // Style flattens to an array. Grab the object with backgroundColor.
    const flat = Array.isArray(banner.props.style)
      ? Object.assign({}, ...banner.props.style)
      : banner.props.style || {};
    expect(String(flat.backgroundColor).toLowerCase()).toBe("#fee2e2");
  });

  it("severity coloring: Moderate → amber banner", async () => {
    mockFetchAlerts.mockResolvedValue({ ok: true, alerts: [
      { event: "Freeze", severity: "Moderate", headline: "H", expires_at: null },
    ]});
    const WeatherWidget = require("../src/components/weather/WeatherWidget").default;
    const utils = render(<WeatherWidget />);
    const banner = await utils.findByTestId("mobile-weather-alerts-banner");
    const flat = Array.isArray(banner.props.style)
      ? Object.assign({}, ...banner.props.style)
      : banner.props.style || {};
    expect(String(flat.backgroundColor).toLowerCase()).toBe("#fef3c7");
  });

  it("renders 7 daily cells", async () => {
    mockFetchDaily.mockResolvedValue(_daily(7));
    const WeatherWidget = require("../src/components/weather/WeatherWidget").default;
    const utils = render(<WeatherWidget />);
    await waitFor(() =>
      expect(utils.getByTestId("mobile-weather-day-0")).toBeTruthy());
    for (let i = 0; i < 7; i++) {
      expect(utils.getByTestId(`mobile-weather-day-${i}`)).toBeTruthy();
    }
    expect(utils.queryByTestId("mobile-weather-day-7")).toBeNull();
  });

  it("UV null renders 'UV —'", async () => {
    mockFetchCurrent.mockResolvedValue(_current({ uv: null }));
    const WeatherWidget = require("../src/components/weather/WeatherWidget").default;
    const utils = render(<WeatherWidget />);
    const uv = await utils.findByTestId("mobile-weather-current-uv");
    expect(uv).toBeTruthy();
    // MiniStat contains a Text node with "UV —". findAllByText handles nested renders.
    const uvText = await utils.findByText(/UV\s+—/);
    expect(uvText).toBeTruthy();
  });
});
