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
import { CloudSun, Radar as RadarIcon, Droplets, Wind, X, Clock as ClockIcon, CalendarDays } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import useWeatherHourly from "@/hooks/useWeatherHourly";
import useTenantLocation from "@/hooks/useTenantLocation";

// Feb 2026 · Task B — dashboard-compact mode. When ``collapsible`` is
// true (Dashboard.jsx passes this), the widget renders only the
// current-conditions row plus three toggle buttons (Hourly / 7-Day /
// Radar). Last-chosen view persists under
// ``localStorage['weather.view']`` so refresh keeps user preference.
// Feb-2026 · Weather-bar reconciliation — the Schedule page now
// passes ``collapsible`` too (matching Dashboard density). The key
// was renamed from ``dashboard.weatherView`` → ``weather.view`` so
// both pages share one preference. A one-shot migration in
// ``_loadViewPref`` reads the legacy key on first load so existing
// Dashboard users don't reset. Non-collapsible callers (if any land
// in the future) leave the prop off and continue to see every panel
// by default.
const LS_VIEW_KEY = "weather.view";
const LS_LEGACY_VIEW_KEY = "dashboard.weatherView";
const VALID_VIEWS = new Set(["collapsed", "hourly", "seven_day", "radar"]);
function _loadViewPref() {
  try {
    let v = window.localStorage.getItem(LS_VIEW_KEY);
    // One-shot migration — Feb-2026 · Weather-bar reconciliation.
    // If the new key is absent but the legacy Dashboard-scoped key
    // holds a valid value, adopt it and persist under the new name
    // so subsequent reads short-circuit. Legacy key is left in
    // place (harmless; a future cleanup migration can strip it).
    if ((v == null || !VALID_VIEWS.has(v))
        && window.localStorage.getItem(LS_LEGACY_VIEW_KEY)) {
      const legacy = window.localStorage.getItem(LS_LEGACY_VIEW_KEY);
      if (VALID_VIEWS.has(legacy)) {
        v = legacy;
        try { window.localStorage.setItem(LS_VIEW_KEY, legacy); }
        catch { /* noop */ }
      }
    }
    return VALID_VIEWS.has(v) ? v : "collapsed";
  } catch { return "collapsed"; }
}
function _saveViewPref(v) {
  try { window.localStorage.setItem(LS_VIEW_KEY, v); } catch { /* noop */ }
}

// Same Peoria, AZ fallback the rest of the codebase already uses
// (see routers/ops.py + WeatherWidget5Day). Tenant-configured
// geocode would override this in the future.
const DEFAULT_LAT = 33.7897;
const DEFAULT_LON = -112.3226;
const REFRESH_MS = 5 * 60 * 1000;

// Exported for regression tests (see
// ``test/schedule-weather-hour-format.test.jsx``); the component
// still consumes it directly.
export function fmtHour(iso) {
  if (!iso) return "";
  // Feb-2026 · UX fix — accept BOTH upstream shapes:
  //   1. WeatherAPI legacy:  "YYYY-MM-DD HH:MM" (space-separated).
  //   2. NWS / newer proxy:  "YYYY-MM-DDTHH:MM:SS±HH:MM" (ISO 8601).
  // Older code split on " " and returned the raw ISO string on the
  // ISO shape — hence "2026-08-26T09:00:00-07:00" leaked into the
  // hourly strip. Use ``Intl.DateTimeFormat`` (native, no deps) so
  // the result honours the user's browser locale (12-hour US default)
  // and correctly renders "12 AM"/"12 PM" at hour boundaries.
  try {
    const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T"));
    if (Number.isNaN(d.getTime())) return iso;
    return new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      hour12: true,
    }).format(d);
  } catch {
    return iso;
  }
}

export default function WeatherWidget({ user, collapsible = false }) {
  const [current, setCurrent] = React.useState(null);
  const [daily, setDaily] = React.useState(null);
  const [radar, setRadar] = React.useState(null);
  const [radarOpen, setRadarOpen] = React.useState(false);
  const [hidden, setHidden] = React.useState(false);
  // Feb-2026 · P39b — NWS active alerts banner.
  const [alerts, setAlerts] = React.useState([]);
  const [alertsExpanded, setAlertsExpanded] = React.useState(false);
  // Feb 2026 · Task B — collapsible-mode view state. Only consulted
  // when ``collapsible`` is truthy; ignored on tech /schedule where
  // every row still renders.
  const [view, setView] = React.useState(() => (collapsible ? _loadViewPref() : "expanded_all"));
  const setViewPersist = React.useCallback((v) => {
    setView(v);
    if (collapsible) _saveViewPref(v);
  }, [collapsible]);

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
        {radar?.loop_url && !collapsible ? (
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

      {/* Feb 2026 · Task B — compact-mode expand toolbar. Renders
          only when the widget was mounted with ``collapsible=true``
          (Dashboard). Three mutually-exclusive buttons drive the
          view state; the same button clicked twice collapses back
          to the today-only row above. Active-state chip uses the
          sky-500 accent per the recent color pass so weather has a
          coherent water/sky vibe. */}
      {collapsible ? (
        <div
          className="flex items-center gap-2 px-4 py-2 border-t"
          style={{ borderColor: colors.border, background: colors.surface }}
          data-testid="weather-expand-toolbar"
        >
          <ExpandChip
            active={view === "hourly"}
            onClick={() => setViewPersist(view === "hourly" ? "collapsed" : "hourly")}
            icon={<ClockIcon size={12} />}
            label="Hourly"
            testId="weather-toggle-hourly"
          />
          <ExpandChip
            active={view === "seven_day"}
            onClick={() => setViewPersist(view === "seven_day" ? "collapsed" : "seven_day")}
            icon={<CalendarDays size={12} />}
            label="7-Day"
            testId="weather-toggle-seven-day"
          />
          <ExpandChip
            active={view === "radar"}
            onClick={() => setViewPersist(view === "radar" ? "collapsed" : "radar")}
            icon={<RadarIcon size={12} />}
            label="Radar"
            disabled={!radar?.loop_url}
            testId="weather-toggle-radar"
          />
          {view !== "collapsed" ? (
            <button
              type="button"
              onClick={() => setViewPersist("collapsed")}
              className="ml-auto p-1 rounded-md hover:bg-slate-100"
              style={{ color: colors.onSurfaceSecondary }}
              data-testid="weather-collapse-btn"
              aria-label="Collapse to today only"
            >
              <X size={14} />
            </button>
          ) : null}
        </div>
      ) : null}

      {/* Row 2 — 24h horizontal strip. Feb 2026 · Task B — in
          collapsible mode this only renders when the user picked
          "Hourly" via the expand toolbar; on other pages every row
          renders as before. */}
      {(!collapsible || view === "hourly") ? (
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
      ) : null}

      {/* Row 3 — 7-day forecast strip. In collapsible mode gated on
          the "seven_day" view; otherwise renders whenever the provider
          returned rows (free tier may cap at 3). */}
      {dailyRows.length > 0 && (!collapsible || view === "seven_day") ? (
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

      {/* Feb 2026 · Task B — inline radar (collapsible mode).
          Uses the same NWS radar loop as the modal; renders in-line
          instead of overlaying so users can flip between Hourly /
          7-Day / Radar without dismissing the widget. Non-dashboard
          consumers keep using the modal via the radar button in
          row 1. */}
      {collapsible && view === "radar" && radar?.loop_url ? (
        <div
          className="border-t"
          style={{ borderColor: colors.border, background: colors.surface }}
          data-testid="weather-radar-inline"
        >
          <img
            src={_radarSrc}
            alt={`NEXRAD radar loop for ${radar.radar_station}`}
            loading="lazy"
            className="w-full max-h-[320px] object-contain bg-black"
            data-testid="weather-radar-inline-img"
          />
          <div
            className="px-4 py-1.5 text-[11px] flex items-center justify-between"
            style={{ color: colors.onSurfaceSecondary }}
          >
            <span>NEXRAD station: {radar.radar_station}</span>
            <button
              type="button"
              onClick={() => setRadarBust(Date.now())}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md hover:bg-slate-100"
              data-testid="weather-radar-inline-refresh"
            >
              <RadarIcon size={12} /> Refresh
            </button>
          </div>
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


// Feb 2026 · Task B — Reusable expand-toolbar chip. Kept co-located
// with WeatherWidget because it's only ever used inside the compact
// toolbar; extracting to its own file adds import overhead for zero
// reuse elsewhere.
function ExpandChip({ active, onClick, icon, label, disabled = false, testId }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold transition"
      style={{
        // Active-state uses accent.sky[500] per the color pass so the
        // weather widget has a coherent water/sky vibe.
        background: active ? colors.accent.sky[500] : colors.surfaceSecondary,
        color: active ? "#fff" : (disabled ? colors.muted : colors.onSurface),
        border: `1px solid ${active ? colors.accent.sky[500] : colors.border}`,
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
      data-testid={testId}
      aria-pressed={active}
    >
      {icon}
      {label}
    </button>
  );
}
