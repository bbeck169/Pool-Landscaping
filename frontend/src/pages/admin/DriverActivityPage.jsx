import React from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { RefreshCw, MapPin, Clock, AlertTriangle } from "lucide-react";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";

/**
 * G2 · Feb-2026 — Driver Activity report (first-pass timeline).
 *
 * Lets an admin+/manager pick a technician and a day, and see the
 * stops detected by the server-side algorithm on a simple horizontal
 * time-of-day timeline (00:00 → 24:00). Gaps between stops are
 * implicitly "driving".
 *
 * G3 (deferred) will add:
 *   - map view of the route
 *   - reverse-geocoded stop addresses (Mapbox)
 *   - job/customer correlation on each stop
 */

function _isoDay(d) {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function _todayIso() {
  return _isoDay(new Date());
}

function _fmtHMS(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

function _minutesOfDay(iso) {
  if (!iso) return 0;
  const d = new Date(iso);
  return d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60;
}

export default function DriverActivityPage() {
  const [techs, setTechs] = React.useState([]);
  const [techId, setTechId] = React.useState("");
  const [day, setDay] = React.useState(_todayIso);
  const [loading, setLoading] = React.useState(false);
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(null);

  // Load techs on mount.
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get("/users?role=technician");
        if (cancelled) return;
        const list = Array.isArray(r) ? r : (r?.users || []);
        setTechs(list);
        if (list.length && !techId) setTechId(list[0].id);
      } catch (e) {
        if (!cancelled) setError(e?.message || "failed to load techs");
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = React.useCallback(async () => {
    if (!techId || !day) return;
    setLoading(true);
    setError(null);
    try {
      const from = `${day}T00:00:00Z`;
      const to = `${day}T23:59:59Z`;
      const r = await api.get(
        `/gps/stops?user_id=${encodeURIComponent(techId)}&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`,
      );
      setData(r);
    } catch (e) {
      setError(e?.message || "failed to load stops");
    } finally {
      setLoading(false);
    }
  }, [techId, day]);

  React.useEffect(() => { load(); }, [load]);

  // ── Summary tiles ─────────────────────────────────────────────
  const stops = data?.stops || [];
  const summary = React.useMemo(() => {
    const total_stops = stops.length;
    const total_stopped_s = stops.reduce(
      (a, s) => a + (Number(s.duration_s) || 0), 0);
    const first_ping = stops.length ? stops[0].started_at : null;
    const last_ping = stops.length ? stops[stops.length - 1].ended_at : null;
    // Approximate driving = span between first stop start and last stop
    // end, minus stopped_s. If we don't have both endpoints, unknown.
    let total_driving_s = 0;
    if (first_ping && last_ping) {
      const span = Math.max(
        0, (new Date(last_ping) - new Date(first_ping)) / 1000,
      );
      total_driving_s = Math.max(0, span - total_stopped_s);
    }
    return {
      total_stops, total_stopped_s, total_driving_s,
      first_ping, last_ping,
    };
  }, [stops]);

  return (
    <SafeScrollContainer
      className="px-4 md:px-8 pt-6 space-y-4"
      data-testid="driver-activity-page"
    >
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1
            className="text-2xl font-semibold"
            style={{ color: colors.onSurface }}
            data-testid="driver-activity-title"
          >
            Driver Activity
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Server-detected stops from GPS pings. Gaps are implicit driving.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-2 h-9 px-3 rounded-lg text-sm font-semibold"
          style={{
            backgroundColor: colors.surface,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="driver-activity-refresh"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <div
        className="flex items-end gap-3 flex-wrap p-3 rounded-xl"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
      >
        <label className="flex flex-col gap-1 text-xs font-semibold"
                style={{ color: colors.muted }}>
          Technician
          <select
            value={techId}
            onChange={(e) => setTechId(e.target.value)}
            data-testid="driver-activity-tech-select"
            className="h-9 px-2 rounded-lg text-sm min-w-[220px]"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
          >
            {techs.length === 0 ? (
              <option value="" disabled>(no technicians)</option>
            ) : null}
            {techs.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name || t.email || t.id}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs font-semibold"
                style={{ color: colors.muted }}>
          Day
          <input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            data-testid="driver-activity-day-input"
            className="h-9 px-2 rounded-lg text-sm"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
          />
        </label>
      </div>

      {/* Summary tiles */}
      <div
        className="grid grid-cols-2 md:grid-cols-4 gap-3"
        data-testid="driver-activity-summary"
      >
        <SummaryTile label="Total stops"
                     value={summary.total_stops}
                     icon={<MapPin size={14} />}
                     testId="driver-activity-tile-stops" />
        <SummaryTile label="Total stopped"
                     value={_fmtHMS(summary.total_stopped_s)}
                     icon={<Clock size={14} />}
                     testId="driver-activity-tile-stopped" />
        <SummaryTile label="Total driving"
                     value={_fmtHMS(summary.total_driving_s)}
                     icon={<Clock size={14} />}
                     testId="driver-activity-tile-driving" />
        <SummaryTile label="First / last"
                     value={
                       summary.first_ping
                         ? `${(summary.first_ping || "").slice(11, 16)} → ${(summary.last_ping || "").slice(11, 16)}`
                         : "—"
                     }
                     icon={<Clock size={14} />}
                     testId="driver-activity-tile-firstlast" />
      </div>

      {error ? (
        <div
          className="rounded-lg px-3 py-2 text-sm flex items-center gap-2"
          style={{
            backgroundColor: "#FEE2E2",
            color: "#7F1D1D",
            border: `1px solid #FCA5A5`,
          }}
          data-testid="driver-activity-error"
        >
          <AlertTriangle size={16} /> {error}
        </div>
      ) : null}

      {/* Timeline */}
      <div
        className="rounded-xl p-4"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="driver-activity-timeline"
      >
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-semibold"
                style={{ color: colors.onSurface }}>
            Timeline · {data?.user_name || (techs.find(t => t.id === techId)?.name || "—")}
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            {loading ? "Loading…" : `${stops.length} stop${stops.length === 1 ? "" : "s"}`}
          </div>
        </div>

        <div
          className="relative w-full rounded-lg"
          style={{
            height: 56,
            backgroundColor: colors.surfaceSecondary,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="driver-activity-timeline-band"
        >
          {/* Hour ticks */}
          {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
            <div
              key={h}
              className="absolute top-0 bottom-0 text-[10px]"
              style={{
                left: `${(h / 24) * 100}%`,
                color: colors.muted,
                borderLeft: h === 0 || h === 24 ? "none" : `1px solid ${colors.border}`,
              }}
            >
              <span
                className="absolute"
                style={{
                  bottom: -14, left: 2,
                  transform: h === 24 ? "translateX(-100%)" : undefined,
                }}
              >
                {String(h).padStart(2, "0")}:00
              </span>
            </div>
          ))}
          {/* Stop blocks */}
          {stops.map((s) => {
            const startMin = _minutesOfDay(s.started_at);
            const endMin = _minutesOfDay(s.ended_at);
            const left = (startMin / (24 * 60)) * 100;
            const width = Math.max(0.4, ((endMin - startMin) / (24 * 60)) * 100);
            return (
              <div
                key={s.id}
                title={`${(s.started_at || "").slice(11, 19)} – ${(s.ended_at || "").slice(11, 19)} · ${_fmtHMS(s.duration_s)} · ${s.center_lat?.toFixed(4)}, ${s.center_lon?.toFixed(4)}`}
                className="absolute top-2 bottom-2 rounded"
                style={{
                  left: `${left}%`, width: `${width}%`,
                  backgroundColor: "#10B981",
                  border: "1px solid #059669",
                }}
                data-testid={`driver-activity-stop-${s.id}`}
              />
            );
          })}
        </div>

        <div className="mt-6 space-y-1">
          {stops.length === 0 && !loading ? (
            <div
              className="text-sm py-4 text-center"
              style={{ color: colors.muted }}
              data-testid="driver-activity-empty"
            >
              No stops detected on this day.
            </div>
          ) : null}
          {stops.map((s) => (
            <div
              key={`row-${s.id}`}
              className="flex items-center justify-between text-xs px-2 py-1 rounded"
              style={{ color: colors.onSurface }}
              data-testid={`driver-activity-stop-row-${s.id}`}
            >
              <div className="font-mono">
                {(s.started_at || "").slice(11, 19)} – {(s.ended_at || "").slice(11, 19)}
              </div>
              <div style={{ color: colors.muted }}>
                {_fmtHMS(s.duration_s)} · {s.center_lat?.toFixed(4)}, {s.center_lon?.toFixed(4)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </SafeScrollContainer>
  );
}


function SummaryTile({ label, value, icon, testId }) {
  return (
    <div
      className="rounded-xl px-3 py-3"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={testId}
    >
      <div className="flex items-center gap-2 text-xs"
            style={{ color: colors.muted }}>
        {icon} {label}
      </div>
      <div className="mt-1 text-xl font-semibold"
            style={{ color: colors.onSurface }}>
        {value}
      </div>
    </div>
  );
}
