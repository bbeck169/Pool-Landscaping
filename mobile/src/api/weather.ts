/**
 * Weather + Tenant location API — Mobile Parity.
 * All endpoints require tech or admin role.
 */
import { api } from "@/src/api";

export type CurrentWeather = {
  ok: boolean;
  cache?: boolean;
  temp_f?: number;
  condition?: string;
  condition_icon?: string;
  high?: number;
  low?: number;
  humidity?: number;
  wind_mph?: number;
  uv?: number;
  last_updated?: string;
};

export type HourlyEntry = {
  time: string;
  temp_f: number;
  condition: string;
  condition_icon: string;
  chance_of_rain: number;
  precip_mm: number;
  wind_mph: number;
};

export type DailyEntry = {
  date: string;
  condition: string;
  condition_icon: string;
  high: number;
  low: number;
  chance_of_rain: number;
  precip_mm: number;
};

export type TenantLocation = {
  hq_lat: number;
  hq_lng: number;
  hq_address_formatted?: string;
};

export const fetchTenantLocation = (): Promise<TenantLocation> =>
  api.get("/tenants/mine/location");

export const fetchCurrentWeather = (lat: number, lon: number): Promise<CurrentWeather> =>
  api.get(`/weather/current?lat=${lat}&lon=${lon}`);

export const fetchHourlyWeather = (
  lat: number,
  lon: number,
  hours = 24
): Promise<{ ok: boolean; hourly: HourlyEntry[] }> =>
  api.get(`/weather/hourly?lat=${lat}&lon=${lon}&hours=${hours}`);

export const fetchDailyWeather = (
  lat: number,
  lon: number,
  days = 5
): Promise<{ ok: boolean; daily: DailyEntry[] }> =>
  api.get(`/weather/daily?lat=${lat}&lon=${lon}&days=${days}`);

export type WeatherAlert = {
  event?: string;
  severity?: string;
  headline?: string;
  expires_at?: string;
  url?: string;
};

export const fetchWeatherRadar = (
  lat: number,
  lon: number
): Promise<{ ok: boolean; embed_url: string }> =>
  api.get(`/weather/radar?lat=${lat}&lon=${lon}`);

// Feb-2026 · P39b — active NWS alerts for the tech's location.
// Envelope: {ok, alerts: WeatherAlert[]}. Returns ok:false on
// out-of-US or upstream error — caller must render nothing on
// ok:false (never surface an error banner).
export const fetchWeatherAlerts = (
  lat: number,
  lon: number
): Promise<{ ok: boolean; alerts?: WeatherAlert[]; reason?: string }> =>
  api.get(`/weather/alerts?lat=${lat}&lon=${lon}`);
