/**
 * WeatherWidget — Feb-2026.
 *
 * Compact live-weather widget rendered on the tech landing page
 * (``/schedule``) and on the admin dashboard. Talks to the FastAPI
 * proxies at ``/api/weather/current``, ``/api/weather/hourly``
 * and ``/api/weather/radar`` — the WeatherAPI.com key never
 * leaves the server.
 *
 * Role gate: renders ``null`` for anyone other than
 * ``admin`` / ``super_admin`` / ``technician``. Customers and
 * anonymous callers are intentionally NOT shown the widget. The
 * backend endpoints already enforce the same allow-list via
 * ``require_tech_or_admin`` (see ``routers/weather_v2.py``).
 *
 * Failure behaviour: any upstream failure or missing config
 * collapses the widget to ``null`` silently — no red banners.
 */
import React from "react";
import { CloudSun, Radar as RadarIcon, Droplets, Wind, X } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import useWeatherHourly from "@/hooks/useWeatherHourly";
import useTenantLocation from "@/hooks/useTenantLocation";

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

export default function WeatherWidget({ user }) {
  const [current, setCurrent] = React.useState(null);
  const [daily, setDaily] = React.useState(null);
  const [radar, setRadar] = React.useState(null);
  const [radarOpen, setRadarOpen] = React.useState(false);
  const [hidden, setHidden] = React.useState(false);
  // Feb-2026 · P39b — NWS active alerts banner.
  const [alerts, setAlerts] = React.useState([]);
  const [alertsExpanded, setAlertsExpanded] = React.useState(false);

  const role = (user?.role || "").toLowerCase();
  const allowed = role === "technician" || role === "admin" || role === "super_admin";

  // Location resolution — Feb-2026:
  //   1. ``tenant.hq_lat/hq_lng`` (set via super-admin Settings)
  //   2. Hardcoded Peoria fallback (kept so demo tenants without
  //      an HQ configured still see a working widget).
  // Tech ``home_base`` override is TBD — no schema on the tech
  // side yet. When it lands, prepend it above tenant HQ.
  const tenantLoc = useTenantLocation({ enabled: allowed });
  const lat = tenantLoc?.lat ?? DEFAULT_LAT;
  const lon = tenantLoc?.lon ?? DEFAULT_LON;

  // Hourly is fetched through the shared hook so JobRainFlag badges
  // on job cards can reuse the same payload without extra HTTP calls.
  const hourly = useWeatherHourly(lat, lon, { enabled: allowed });

  const load = React.useCallback(async () => {
    try {
      const [cur, dl, al, rd] = await Promise.all([
        api.get(`/weather/current?lat=${lat}&lon=${lon}`),
        // Feb-2026 · P39b — bumped 5 → 7 days (NWS supports up to 10;
        // P39a spec puts the widget at 7).
        api.get(`/weather/daily?lat=${lat}&lon=${lon}&days=7`),
        // Feb-2026 · P39b — active alerts (safety-critical banner
        // above current conditions). ``ok:false`` (out-of-US /
        // upstream error) is fine — banner just doesn't render.
        api.get(`/weather/alerts?lat=${lat}&lon=${lon}`).catch(() => null),
        // Feb-2026 · P39c — NWS ridge/standard radar loop URL.
        // Pre-fetch so the Radar button can be hidden proactively on
        // out-of-US / no_radar_station tenants (avoid teasing a
        // click that would open an empty modal).
        api.get(`/weather/radar?lat=${lat}&lon=${lon}`).catch(() => null),
      ]);
      if (cur?.ok === false) {
        setHidden(true);
        return;
      }
      setCurrent(cur);
      // Daily is optional — a graceful ok:false just hides the
      // 7-day strip without collapsing the whole widget.
      setDaily(dl?.ok === false ? null : dl);
      // Alerts is optional — never blocks the widget.
      setAlerts(al?.ok === false || !al ? [] : (al.alerts || []));
      // Radar is optional — Radar button hides when ok:false.
      setRadar(rd?.ok === false || !rd ? null : rd);
      setHidden(false);
    } catch {
      setHidden(true);
    }
  }, [lat, lon]);

  React.useEffect(() => {
    if (!allowed) return undefined;
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
  }, [allowed, load]);

  const openRadar = () => {
    // Feb-2026 · P39c — radar is pre-fetched in ``load()``. If it
    // came back ok:false the button below is hidden entirely and
    // this handler will never fire; keeping the guard defensively.
    if (radar?.loop_url) setRadarOpen(true);
  };
  // Feb-2026 · P39c — cache-busting refresh for the NWS GIF. The
  // GIF is refreshed server-side ~every 10 min but the browser
  // caches by URL, so we append ``?t=<Date.now()>`` when the user
  // asks for a fresh loop.
  const [radarBust, setRadarBust] = React.useState(0);
  const _radarSrc = radar?.loop_url
    ? (radarBust ? `${radar.loop_url}?t=${radarBust}` : radar.loop_url)
    : null;

  if (!allowed || hidden || !current?.ok || !hourly?.ok) return null;

  const cur = current.current || {};
  const hi = Math.max(...(hourly.hourly || []).map((h) => h.temp_f).filter((v) => v != null));
  const lo = Math.min(...(hourly.hourly || []).map((h) => h.temp_f).filter((v) => v != null));

  const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const dayLabel = (dateStr, idx) => {
    if (idx === 0) return "Today";
    try {
      const d = new Date(`${dateStr}T12:00:00`);
      if (Number.isNaN(d.getTime())) return dateStr;
      return DAY_NAMES[d.getDay()];
    } catch {
      return dateStr;
    }
  };
  const dailyRows = (daily?.daily || []).slice(0, 7);

  // Feb-2026 · P39b — alerts banner styling by severity.
  // Extreme + Severe → red; Moderate → amber; Minor/Unknown → slate.
  const _severityRank = (s) => {
    const t = String(s || "").toLowerCase();
    if (t === "extreme" || t === "severe") return "red";
    if (t === "moderate") return "amber";
    return "slate";
  };
  const _alertPalette = (rank) => {
    if (rank === "red") return { bg: "#FEE2E2", border: "#FCA5A5", fg: "#7F1D1D" };
    if (rank === "amber") return { bg: "#FEF3C7", border: "#FCD34D", fg: "#78350F" };
    return { bg: "#E2E8F0", border: "#94A3B8", fg: "#1E293B" };
  };
  // Ordered by severity descending so the highest-priority alert
  // drives the banner container color and appears first. Inline
  // rather than ``useMemo`` — cheap sort, and keeping hook count
  // stable across the early-return branch above.
  const _rank = { red: 0, amber: 1, slate: 2 };
  const _sortedAlerts = [...(alerts || [])].sort(
    (a, b) => _rank[_severityRank(a.severity)] - _rank[_severityRank(b.severity)]
  );
  const _topRank = _sortedAlerts.length ? _severityRank(_sortedAlerts[0].severity) : "slate";
  const _bannerPalette = _alertPalette(_topRank);
  const _fmtExpires = (iso) => {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return "";
      const h = d.getHours();
      const m = d.getMinutes();
      const hour12 = h % 12 === 0 ? 12 : h % 12;
      const mm = String(m).padStart(2, "0");
      return `${hour12}:${mm}${h >= 12 ? "pm" : "am"}`;
    } catch { return ""; }
  };
  const _truncate = (s, n = 180) => {
    if (!s) return "";
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  };
  const _visibleAlerts = alertsExpanded
    ? _sortedAlerts
    : _sortedAlerts.slice(0, 1);
  const _hiddenAlertCount = Math.max(0, _sortedAlerts.length - _visibleAlerts.length);

  return (
    <div
      className="mb-4 rounded-2xl overflow-hidden"
      style={{
        background: `linear-gradient(135deg, ${colors.brandTertiary} 0%, ${colors.surface} 100%)`,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="weather-widget"
    >
      {/* Feb-2026 · P39b — Alerts banner. Rendered ABOVE current
          conditions because severe-weather alerts are safety-critical
          and must be seen first. Container tint matches the top-ranked
          alert's severity (Extreme/Severe = red, Moderate = amber,
          Minor/Unknown = slate). Multi-alert case shows the first plus
          an "and N more" pill that expands the list inline. */}
      {_sortedAlerts.length > 0 ? (
        <div
          className="px-4 py-2.5 border-b"
          style={{
            background: _bannerPalette.bg,
            borderColor: _bannerPalette.border,
            color: _bannerPalette.fg,
          }}
          data-testid="weather-alerts-banner"
        >
          {_visibleAlerts.map((a, i) => (
            <div
              key={i}
              className={i === 0 ? "" : "mt-2 pt-2 border-t"}
              style={i === 0 ? undefined
                : { borderColor: _bannerPalette.border }}
              data-testid={`weather-alert-item-${i}`}
            >
              <div className="text-sm font-bold">{a.event || "Alert"}</div>
              <div className="text-xs mt-0.5">
                {_truncate(a.headline || "", 180)}
              </div>
              {a.expires_at ? (
                <div className="text-[10px] mt-0.5 opacity-80">
                  Expires {_fmtExpires(a.expires_at)}
                </div>
              ) : null}
            </div>
          ))}
          {_hiddenAlertCount > 0 ? (
            <button
              type="button"
              onClick={() => setAlertsExpanded(true)}
              className="inline-block mt-2 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full"
              style={{
                background: _bannerPalette.fg,
                color: _bannerPalette.bg,
              }}
              data-testid="weather-alerts-more-pill"
            >
              and {_hiddenAlertCount} more
            </button>
          ) : null}
        </div>
      ) : null}

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
            <span data-testid="weather-current-uv">
              UV {cur.uv == null ? "—" : cur.uv}
            </span>
          </div>
        </div>
        {radar?.loop_url ? (
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
        ) : null}
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

      {/* Row 3 — 5-day forecast strip (renders only what the
          provider actually returned; free tier may cap at 3). */}
      {dailyRows.length > 0 ? (
        <div
          className="flex items-stretch gap-2 overflow-x-auto px-4 py-3 border-t"
          style={{ borderColor: colors.border, background: colors.surfaceSecondary }}
          data-testid="weather-5day-forecast"
        >
          {dailyRows.map((d, i) => (
            <div
              key={d.date || i}
              className="flex flex-col items-center gap-0.5 shrink-0 min-w-[68px] rounded-xl px-2 py-2"
              style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
              data-testid={`weather-day-${i}`}
              data-date={d.date || ""}
            >
              <span
                className="text-[10px] font-bold uppercase tracking-wider"
                style={{ color: colors.onSurfaceSecondary }}
              >
                {dayLabel(d.date, i)}
              </span>
              {d.condition_icon ? (
                <img src={d.condition_icon} alt="" className="w-7 h-7" />
              ) : (
                <div className="w-7 h-7" />
              )}
              <div
                className="text-xs font-bold whitespace-nowrap"
                style={{ color: colors.onSurface }}
              >
                {d.high != null ? `${Math.round(d.high)}°` : "—"}
                <span style={{ color: colors.muted, fontWeight: 500 }}>
                  {" / "}
                  {d.low != null ? `${Math.round(d.low)}°` : "—"}
                </span>
              </div>
              <span
                className="text-[10px] font-semibold"
                style={{ color: colors.brand }}
              >
                {d.chance_of_rain != null ? `${d.chance_of_rain}%` : ""}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {/* Feb-2026 · P39c — Radar modal. Windy iframe swapped for the
          NWS ridge/standard animated GIF anchored on the point's
          radar_station code. Browser handles caching; no server-side
          cache. Refresh button appends a timestamp query param to
          bust the browser cache when the user asks for a fresh loop. */}
      {radarOpen && radar?.loop_url ? (
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
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setRadarBust(Date.now())}
                  className="p-1 rounded-md hover:bg-gray-100"
                  title="Refresh radar loop"
                  data-testid="weather-radar-refresh"
                >
                  <RadarIcon size={16} />
                </button>
                <button
                  type="button"
                  onClick={() => setRadarOpen(false)}
                  className="p-1 rounded-md hover:bg-gray-100"
                  data-testid="weather-radar-close"
                >
                  <X size={16} />
                </button>
              </div>
            </div>
            <img
              src={_radarSrc}
              alt={`NEXRAD radar loop for ${radar.radar_station}`}
              loading="lazy"
              className="w-full h-[70vh] object-contain bg-black"
              data-testid="weather-radar-img"
            />
            <div
              className="px-4 py-2 text-[11px] border-t"
              style={{
                borderColor: colors.border,
                color: colors.onSurfaceSecondary,
                background: colors.surface,
              }}
              data-testid="weather-radar-station"
            >
              NEXRAD radar station: {radar.radar_station}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
