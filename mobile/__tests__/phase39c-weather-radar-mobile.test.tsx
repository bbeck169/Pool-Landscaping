/**
 * Feb-2026 · P39c — mobile radar swap to NWS ridge/standard GIF.
 *
 * Coverage:
 *   1. Radar button hidden when radar.ok:false.
 *   2. Radar button rendered when radar.ok:true.
 *   3. Opening the modal renders <Image> with the loop_url URI.
 *   4. Station caption below the image shows the code.
 *   5. Refresh button appends a timestamp query param to the URI.
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


function _current() {
  return {
    ok: true, temp_f: 92.5, condition: "Sunny",
    high: 100, low: 75, humidity: 20, wind_mph: 8, uv: 5,
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
  mockFetchDaily.mockResolvedValue({ ok: true, daily: [] });
  mockFetchAlerts.mockResolvedValue({ ok: true, alerts: [] });
});


describe("Mobile WeatherWidget · P39c radar swap", () => {
  it("hides Radar button when radar.ok === false", async () => {
    mockFetchRadar.mockResolvedValue({ ok: false, reason: "out_of_us" });
    const WeatherWidget = require("../src/components/weather/WeatherWidget").default;
    const utils = render(<WeatherWidget />);
    await utils.findByTestId("weather-widget");
    expect(utils.queryByTestId("weather-radar-open")).toBeNull();
  });

  it("renders Radar button when radar.ok === true", async () => {
    mockFetchRadar.mockResolvedValue({
      ok: true, provider: "nws", radar_station: "KIWA",
      loop_url: "https://radar.weather.gov/ridge/standard/KIWA_loop.gif",
      still_url: "https://radar.weather.gov/ridge/standard/KIWA_0.gif",
    });
    const WeatherWidget = require("../src/components/weather/WeatherWidget").default;
    const utils = render(<WeatherWidget />);
    await utils.findByTestId("weather-radar-open");
  });

  it("opens modal with <Image> whose URI is loop_url + station caption", async () => {
    mockFetchRadar.mockResolvedValue({
      ok: true, provider: "nws", radar_station: "KMPX",
      loop_url: "https://radar.weather.gov/ridge/standard/KMPX_loop.gif",
      still_url: "https://radar.weather.gov/ridge/standard/KMPX_0.gif",
    });
    const WeatherWidget = require("../src/components/weather/WeatherWidget").default;
    const utils = render(<WeatherWidget />);
    const btn = await utils.findByTestId("weather-radar-open");
    await act(async () => { fireEvent.press(btn); });
    const img = await utils.findByTestId("mobile-weather-radar-img");
    expect(img.props.source.uri).toBe(
      "https://radar.weather.gov/ridge/standard/KMPX_loop.gif");
    const caption = await utils.findByTestId("mobile-weather-radar-station");
    expect(caption.props.children).toEqual(
      expect.arrayContaining([expect.any(String), "KMPX"]));
  });

  it("refresh button appends timestamp query param to URI", async () => {
    mockFetchRadar.mockResolvedValue({
      ok: true, provider: "nws", radar_station: "KIWA",
      loop_url: "https://radar.weather.gov/ridge/standard/KIWA_loop.gif",
      still_url: "https://radar.weather.gov/ridge/standard/KIWA_0.gif",
    });
    const WeatherWidget = require("../src/components/weather/WeatherWidget").default;
    const utils = render(<WeatherWidget />);
    const btn = await utils.findByTestId("weather-radar-open");
    await act(async () => { fireEvent.press(btn); });
    const imgBefore = await utils.findByTestId("mobile-weather-radar-img");
    expect(imgBefore.props.source.uri).toBe(
      "https://radar.weather.gov/ridge/standard/KIWA_loop.gif");
    const refresh = utils.getByTestId("mobile-weather-radar-refresh");
    await act(async () => { fireEvent.press(refresh); });
    await waitFor(() => {
      const img = utils.getByTestId("mobile-weather-radar-img");
      expect(img.props.source.uri).toMatch(
        /^https:\/\/radar\.weather\.gov\/ridge\/standard\/KIWA_loop\.gif\?t=\d+$/);
    });
  });
});
