/**
 * TechWeatherWidget — Feb-2026.
 *
 * Compact live-weather widget rendered in the tech dashboard
 * (OpsHub) header only. Talks to the FastAPI proxies at
 * ``/api/weather/current``, ``/api/weather/hourly`` and
 * ``/api/weather/radar`` — the WeatherAPI.com key never leaves the
 * server.
 *
 * Role gate: renders ``null`` unless the current user's role is
 * ``technician``. Admins/customers are intentionally NOT shown the
 * widget (their dashboards are different surfaces — spec says
 * "tech dashboard header ONLY").
 *
 * Failure behaviour: any upstream failure or missing config
 * collapses the widget to ``null`` silently — no red banners on
 * the tech dashboard.
 */
import React from "react";
import { CloudSun, Radar as RadarIcon, Droplets, Wind, X } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

// Same Peoria, AZ fallback the rest of the codebase already uses
// (see routers/ops.py + WeatherWidget5Day). Tenant-configured
// geocode would override this in the future.
const DEFAULT_LAT = 33.7897;
const DEFAULT_LON = -112.3226;
const REFRESH_MS = 5 * 60 * 1000;

function fmtHour(iso) {
  if (!iso) return "";
  // WeatherAPI returns "YYYY-MM-DD HH:MM" in the location's local tz.
  const parts = iso.split(" ");
  if (parts.length < 2) return iso;
  const [h] = parts[1].split(":").map(Number);
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${hour12}${h >= 12 ? "p" : "a"}`;
}

export default function TechWeatherWidget({ user }) {
  const [current, setCurrent] = React.useState(null);
  const [hourly, setHourly] = React.useState(null);
  const [radar, setRadar] = React.useState(null);
  const [radarOpen, setRadarOpen] = React.useState(false);
  const [hidden, setHidden] = React.useState(false);

  const role = (user?.role || "").toLowerCase();
  const isTech = role === "technician";

  // Tenant/tech geocode is not yet plumbed — fall back to the
  // shared Peoria fallback.
  const lat = DEFAULT_LAT;
  const lon = DEFAULT_LON;

  const load = React.useCallback(async () => {
    try {
      const [cur, hr] = await Promise.all([
        api.get(`/weather/current?lat=${lat}&lon=${lon}`),
        api.get(`/weather/hourly?lat=${lat}&lon=${lon}&hours=24`),
      ]);
      if (cur?.ok === false || hr?.ok === false) {
        setHidden(true);
        return;
      }
      setCurrent(cur);
      setHourly(hr);
      setHidden(false);
    } catch {
      setHidden(true);
    }
  }, [lat, lon]);

  React.useEffect(() => {
    if (!isTech) return undefined;
    load();
    const iv = setInterval(load, REFRESH_MS);
    const onVis = () => {
      if (document.visibilityState === "visible") load();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      clearInterval(iv);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [isTech, load]);

  const openRadar = async () => {
    if (!radar) {
      try {
        const r = await api.get(`/weather/radar?lat=${lat}&lon=${lon}`);
        if (r?.ok !== false) setRadar(r);
        else return;
      } catch { return; }
    }
    setRadarOpen(true);
  };

  if (!isTech || hidden || !current?.ok || !hourly?.ok) return null;

  const cur = current.current || {};
  const hi = Math.max(...(hourly.hourly || []).map((h) => h.temp_f).filter((v) => v != null));
  const lo = Math.min(...(hourly.hourly || []).map((h) => h.temp_f).filter((v) => v != null));

  return (
    <div
      className="mb-4 rounded-2xl overflow-hidden"
      style={{
        background: `linear-gradient(135deg, ${colors.brandTertiary} 0%, ${colors.surface} 100%)`,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="weather-widget"
    >
      {/* Row 1 — current conditions */}
      <div className="flex items-center gap-4 px-4 py-3">
        {cur.condition_icon ? (
          <img
            src={cur.condition_icon}
            alt={cur.condition_text || "condition"}
            className="w-12 h-12 shrink-0"
            data-testid="weather-current-icon"
          />
        ) : (
          <CloudSun size={40} className="shrink-0" style={{ color: colors.brand }} />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2">
            <span
              className="text-2xl font-bold"
              style={{ color: colors.onSurface }}
              data-testid="weather-current-temp"
            >
              {cur.temp_f != null ? `${Math.round(cur.temp_f)}°` : "—"}
            </span>
            <span
              className="text-sm font-semibold"
              style={{ color: colors.onSurfaceSecondary }}
            >
              {cur.condition_text || ""}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs mt-1"
                style={{ color: colors.onSurfaceSecondary }}>
            <span>H {Math.round(hi)}° / L {Math.round(lo)}°</span>
            <span className="inline-flex items-center gap-1">
              <Droplets size={12} /> {cur.humidity ?? "—"}%
            </span>
            <span className="inline-flex items-center gap-1">
              <Wind size={12} /> {cur.wind_mph ?? "—"} mph {cur.wind_dir || ""}
            </span>
            <span>UV {cur.uv ?? "—"}</span>
          </div>
        </div>
        <button
          type="button"
          onClick={openRadar}
          className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full transition"
          style={{
            background: colors.brand,
            color: "#fff",
          }}
          data-testid="weather-radar-open"
        >
          <RadarIcon size={13} /> Radar
        </button>
      </div>

      {/* Row 2 — 24h horizontal strip */}
      <div
        className="flex items-center gap-3 overflow-x-auto px-4 py-2 border-t"
        style={{ borderColor: colors.border, background: colors.surface }}
        data-testid="weather-hourly-strip"
      >
        {(hourly.hourly || []).map((h, i) => (
          <div
            key={h.time || i}
            className="flex flex-col items-center gap-0.5 shrink-0 min-w-[52px]"
            data-testid={`weather-hour-${i}`}
          >
            <span
              className="text-[10px] font-semibold"
              style={{ color: colors.onSurfaceSecondary }}
            >
              {i === 0 ? "Now" : fmtHour(h.time)}
            </span>
            {h.condition_icon ? (
              <img
                src={h.condition_icon}
                alt=""
                className="w-6 h-6"
              />
            ) : <div className="w-6 h-6" />}
            <span
              className="text-xs font-bold"
              style={{ color: colors.onSurface }}
            >
              {h.temp_f != null ? `${Math.round(h.temp_f)}°` : "—"}
            </span>
            <span
              className="text-[10px]"
              style={{ color: colors.brand }}
            >
              {h.chance_of_rain != null ? `${h.chance_of_rain}%` : ""}
            </span>
          </div>
        ))}
      </div>

      {/* Radar modal */}
      {radarOpen && radar?.embed_url ? (
        <div
          className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
          onClick={() => setRadarOpen(false)}
          data-testid="weather-radar-modal"
        >
          <div
            className="w-full max-w-4xl rounded-2xl overflow-hidden bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div
              className="flex items-center justify-between px-4 py-2 border-b"
              style={{ borderColor: colors.border }}
            >
              <span className="text-sm font-bold" style={{ color: colors.onSurface }}>
                Live radar — {current?.location?.name || ""}
              </span>
              <button
                type="button"
                onClick={() => setRadarOpen(false)}
                className="p-1 rounded-md hover:bg-gray-100"
                data-testid="weather-radar-close"
              >
                <X size={16} />
              </button>
            </div>
            <iframe
              title="radar"
              src={radar.embed_url}
              className="w-full h-[70vh]"
              frameBorder="0"
              data-testid="weather-radar-iframe"
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
