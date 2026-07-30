import React from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { RefreshCw, MapPin, Clock, AlertTriangle, Layers, Link as LinkIcon } from "lucide-react";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";
import { toast } from "sonner";
import StopAttributionModal from "@/pages/admin/StopAttributionModal";
// Phase G5c · Feb-2026 — Animated route replay.
import RouteReplayPanel from "@/pages/admin/RouteReplayPanel";
import useGpsRoute from "@/hooks/useGpsRoute";

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
  // G5b · Feb-2026 — attribution modal state.
  const [attrStop, setAttrStop] = React.useState(null);
  // G5b addendum #2 · Feb-2026 — customer/address search filters
  // (debounced 400ms so we don't refetch on every keystroke).
  const [qCustomer, setQCustomer] = React.useState("");
  const [qAddress, setQAddress] = React.useState("");
  const [qCustomerDebounced, setQCustomerDebounced] = React.useState("");
  const [qAddressDebounced, setQAddressDebounced] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => setQCustomerDebounced(qCustomer.trim()), 400);
    return () => clearTimeout(t);
  }, [qCustomer]);
  React.useEffect(() => {
    const t = setTimeout(() => setQAddressDebounced(qAddress.trim()), 400);
    return () => clearTimeout(t);
  }, [qAddress]);

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
      const qs = new URLSearchParams({
        user_id: techId, from, to,
      });
      if (qCustomerDebounced) qs.set("q_customer", qCustomerDebounced);
      if (qAddressDebounced)  qs.set("q_address",  qAddressDebounced);
      const r = await api.get(`/gps/stops?${qs.toString()}`);
      setData(r);
    } catch (e) {
      setError(e?.message || "failed to load stops");
    } finally {
      setLoading(false);
    }
  }, [techId, day, qCustomerDebounced, qAddressDebounced]);

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

        {/* G5b addendum #2 · Feb-2026 — filter stops by customer / address */}
        <label className="flex flex-col gap-1 text-xs font-semibold"
                style={{ color: colors.muted }}>
          Customer
          <input
            type="text"
            value={qCustomer}
            placeholder="Search customer…"
            onChange={(e) => setQCustomer(e.target.value)}
            data-testid="driver-activity-q-customer"
            className="h-9 px-2 rounded-lg text-sm"
            style={{ backgroundColor: colors.surface,
                     color: colors.onSurface,
                     border: `1px solid ${colors.border}`, minWidth: 160 }}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold"
                style={{ color: colors.muted }}>
          Address
          <input
            type="text"
            value={qAddress}
            placeholder="Search address…"
            onChange={(e) => setQAddress(e.target.value)}
            data-testid="driver-activity-q-address"
            className="h-9 px-2 rounded-lg text-sm"
            style={{ backgroundColor: colors.surface,
                     color: colors.onSurface,
                     border: `1px solid ${colors.border}`, minWidth: 160 }}
          />
        </label>
        {(qCustomer || qAddress) && (
          <button type="button"
            onClick={() => { setQCustomer(""); setQAddress(""); }}
            className="self-end h-9 px-2 rounded-lg text-xs"
            style={{ border: `1px solid ${colors.border}`,
                     color: colors.muted }}
            data-testid="driver-activity-q-clear">
            Clear filters
          </button>
        )}
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
              <div className="flex-1 mx-3 truncate"
                   data-testid={`driver-activity-stop-addr-${s.id}`}
                   title={s.address?.formatted || ""}>
                {s.address?.formatted ? (
                  <span style={{ color: colors.onSurface }}>
                    {s.address.formatted}
                  </span>
                ) : (
                  <span style={{ color: colors.muted, fontStyle: "italic" }}
                        data-testid={`driver-activity-stop-addr-fallback-${s.id}`}>
                    Address unavailable · {s.center_lat?.toFixed(4)}, {s.center_lon?.toFixed(4)}
                  </span>
                )}
                {/* G5b addendum · Feb-2026 — attributed customer name */}
                {s.attributed_customer_name ? (
                  <span
                    className="ml-2 text-[11px]"
                    style={{ color: colors.muted }}
                    data-testid={`driver-activity-stop-customer-${s.id}`}
                  >
                    · {s.attributed_customer_name}
                  </span>
                ) : null}
              </div>
              {/* G5b · Feb-2026 — attribution badge + change action */}
              <div className="flex items-center gap-2 mr-2"
                   data-testid={`driver-activity-stop-attribution-${s.id}`}>
                {s.attribution_status === "auto_linked"
                    || s.attribution_status === "manual_linked" ? (
                  <span
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px]"
                    style={{
                      background: s.attribution_status === "manual_linked"
                        ? "#DBEAFE" : "#DCFCE7",
                      color: s.attribution_status === "manual_linked"
                        ? "#1E40AF" : "#065F46",
                    }}
                    data-testid={`driver-activity-stop-job-${s.id}`}
                    title={s.attributed_job_name || ""}
                  >
                    <LinkIcon size={10} />
                    {s.attributed_job_name || "Linked"}
                  </span>
                ) : s.attribution_status === "no_match" ? (
                  <span className="text-[10px]"
                        style={{ color: colors.muted }}
                        data-testid={`driver-activity-stop-nomatch-${s.id}`}>
                    unlinked
                  </span>
                ) : s.attribution_status === "unlinked" ? (
                  <span className="text-[10px]"
                        style={{ color: colors.muted }}
                        data-testid={`driver-activity-stop-manual-unlinked-${s.id}`}>
                    unlinked (manual)
                  </span>
                ) : (
                  <Clock size={10} style={{ color: colors.muted }}
                    data-testid={`driver-activity-stop-pending-${s.id}`} />
                )}
                <button type="button"
                  onClick={() => setAttrStop(s)}
                  className="text-[10px] text-sky-600 hover:underline"
                  data-testid={`driver-activity-stop-change-${s.id}`}>
                  Change
                </button>
              </div>
              <div style={{ color: colors.muted }}>
                {_fmtHMS(s.duration_s)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* G3 · Feb-2026 — Route Map panel with 3 toggleable layers. */}
      <RouteMapPanel techId={techId} day={day} onRefreshStops={load} />
      {/* G5c · Feb-2026 — Animated Route Replay (below the static map). */}
      <RouteReplayPanel techId={techId} day={day} />
      {/* G5b · Feb-2026 — attribution override modal. */}
      {attrStop && (
        <StopAttributionModal stop={attrStop}
          onClose={() => setAttrStop(null)}
          onSaved={() => { setAttrStop(null); load(); }} />
      )}
    </SafeScrollContainer>
  );
}


// ══════════════════════════════════════════════════════════════════
// G3 · Route Map panel — polyline / stops-only / ping-trail toggles
// ══════════════════════════════════════════════════════════════════

function RouteMapPanel({ techId, day, onRefreshStops }) {
  // G5c · Feb-2026 — share the /gps/route fetch with RouteReplayPanel.
  const { route, loading, error, invalidate } = useGpsRoute({ techId, day });
  const [showPolyline, setShowPolyline] = React.useState(true);
  const [showStops, setShowStops] = React.useState(true);
  const [showPings, setShowPings] = React.useState(false);
  const [backfillOpen, setBackfillOpen] = React.useState(false);
  const [backfillBusy, setBackfillBusy] = React.useState(false);
  const [backfillResult, setBackfillResult] = React.useState(null);
  // G4 · CSV export dialog state.
  const [exportOpen, setExportOpen] = React.useState(false);
  const [exportScope, setExportScope] = React.useState("tech");
  const [exportKind, setExportKind] = React.useState("stops");

  const bounds = React.useMemo(() => {
    const lats = []; const lons = [];
    for (const s of route?.stops || []) {
      if (typeof s.center_lat === "number") lats.push(s.center_lat);
      if (typeof s.center_lon === "number") lons.push(s.center_lon);
    }
    for (const p of route?.pings || []) {
      if (typeof p.lat === "number") lats.push(p.lat);
      if (typeof p.lon === "number") lons.push(p.lon);
    }
    if (!lats.length) return null;
    const min_lat = Math.min(...lats); const max_lat = Math.max(...lats);
    const min_lon = Math.min(...lons); const max_lon = Math.max(...lons);
    // Pad 5% either side.
    const pad_lat = Math.max(0.0005, (max_lat - min_lat) * 0.1);
    const pad_lon = Math.max(0.0005, (max_lon - min_lon) * 0.1);
    return {
      min_lat: min_lat - pad_lat, max_lat: max_lat + pad_lat,
      min_lon: min_lon - pad_lon, max_lon: max_lon + pad_lon,
    };
  }, [route]);

  const project = React.useCallback((lat, lon) => {
    if (!bounds) return { x: 0, y: 0 };
    const w = 800, h = 360;
    const x = ((lon - bounds.min_lon) /
                Math.max(1e-9, (bounds.max_lon - bounds.min_lon))) * w;
    const y = h - ((lat - bounds.min_lat) /
                    Math.max(1e-9, (bounds.max_lat - bounds.min_lat))) * h;
    return { x, y };
  }, [bounds]);

  const runBackfill = async () => {
    setBackfillBusy(true);
    try {
      const r = await api.post(
        "/admin/gps/reverse-geocode/backfill",
        { dry_run: false, scope: "stops", max_calls: 100 });
      setBackfillResult(r);
      if (r?.status === "no_token") {
        toast.info("Mapbox token missing — nothing processed.");
      } else {
        toast.success(
          `Backfill done · resolved=${r?.resolved ?? 0}, errors=${r?.errors ?? 0}`);
        invalidate();
        onRefreshStops?.();
      }
    } catch (e) {
      toast.error("Backfill failed", { description: e?.message });
    } finally {
      setBackfillBusy(false);
    }
  };

  const stops = route?.stops || [];
  const pings = route?.pings || [];
  const tokenSet = !!route?.mapbox_token_configured;

  return (
    <div
      className="rounded-xl p-4"
      style={{ backgroundColor: colors.surface,
                border: `1px solid ${colors.border}` }}
      data-testid="driver-activity-route-map"
    >
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <div className="text-sm font-semibold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
          <Layers size={14} /> Route Map
        </div>
        <div className="flex items-center gap-3 text-xs"
              style={{ color: colors.onSurface }}
              data-testid="route-map-legend">
          <label className="inline-flex items-center gap-1"
                  data-testid="route-map-toggle-polyline-wrap">
            <input type="checkbox" checked={showPolyline}
                    onChange={(e) => setShowPolyline(e.target.checked)}
                    data-testid="route-map-toggle-polyline" />
            <span style={{ color: "#0284C7" }}>Polyline</span>
          </label>
          <label className="inline-flex items-center gap-1"
                  data-testid="route-map-toggle-stops-wrap">
            <input type="checkbox" checked={showStops}
                    onChange={(e) => setShowStops(e.target.checked)}
                    data-testid="route-map-toggle-stops" />
            <span style={{ color: "#10B981" }}>Stops-only</span>
          </label>
          <label className="inline-flex items-center gap-1"
                  data-testid="route-map-toggle-pings-wrap">
            <input type="checkbox" checked={showPings}
                    onChange={(e) => setShowPings(e.target.checked)}
                    data-testid="route-map-toggle-pings" />
            <span style={{ color: "#F59E0B" }}>Ping trail</span>
          </label>
          <button type="button" onClick={() => setBackfillOpen(true)}
                    className="ml-2 inline-flex items-center gap-1 h-7 px-2 rounded text-xs font-semibold"
                    style={{
                      backgroundColor: colors.surface,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}`,
                    }}
                    data-testid="route-map-backfill-btn">
            Backfill addresses
          </button>
          {/* G4 · Feb-2026 — CSV export dialog trigger. */}
          <button type="button" onClick={() => setExportOpen(true)}
                    className="inline-flex items-center gap-1 h-7 px-2 rounded text-xs font-semibold"
                    style={{
                      backgroundColor: colors.surface,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}`,
                    }}
                    data-testid="route-map-export-btn">
            Export CSV
          </button>
        </div>
      </div>

      {!tokenSet && (
        <div className="mb-3 rounded-lg px-3 py-2 text-xs flex items-center gap-2"
             style={{ backgroundColor: "#FEF3C7", color: "#92400E",
                       border: "1px solid #FDE68A" }}
             data-testid="route-map-no-token-banner">
          <AlertTriangle size={14} />
          <span>
            <strong>MAPBOX_ACCESS_TOKEN not set.</strong>{" "}
            Reverse-geocoding disabled — stops show coordinates only.
          </span>
        </div>
      )}

      {loading ? (
        <div className="text-sm" style={{ color: colors.muted }}
             data-testid="route-map-loading">Loading route…</div>
      ) : error ? (
        <div className="text-sm" style={{ color: "#7F1D1D" }}
             data-testid="route-map-error">{error}</div>
      ) : !bounds ? (
        <div className="text-sm py-8 text-center"
             style={{ color: colors.muted }}
             data-testid="route-map-empty">
          No stops or pings for this day yet.
        </div>
      ) : (
        <svg viewBox="0 0 800 360"
             className="w-full rounded-lg"
             style={{ backgroundColor: "#F4F4F5",
                       border: `1px solid ${colors.border}` }}
             data-testid="route-map-svg">
          {/* Ping trail — small amber dots */}
          {showPings && pings.map((p, i) => {
            const { x, y } = project(p.lat, p.lon);
            return (
              <circle key={`png-${i}`} cx={x} cy={y} r={1.5}
                      fill="#F59E0B" opacity={0.75}
                      data-testid={`route-map-ping-${i}`} />
            );
          })}
          {/* Polyline — connect stops in chronological order */}
          {showPolyline && stops.length >= 2 && (
            <polyline
              fill="none" stroke="#0284C7" strokeWidth={2.5}
              points={stops.map((s) => {
                const { x, y } = project(s.center_lat, s.center_lon);
                return `${x.toFixed(1)},${y.toFixed(1)}`;
              }).join(" ")}
              data-testid="route-map-polyline"
            />
          )}
          {/* Stops-only — emerald pins */}
          {showStops && stops.map((s, i) => {
            const { x, y } = project(s.center_lat, s.center_lon);
            return (
              <g key={s.id || `s-${i}`}
                 data-testid={`route-map-stop-${s.id || i}`}>
                <circle cx={x} cy={y} r={7}
                        fill="#10B981" stroke="#065F46"
                        strokeWidth={1.5} />
                <text x={x + 10} y={y + 4} fontSize={10}
                      fill="#065F46">
                  {i + 1}
                </text>
              </g>
            );
          })}
        </svg>
      )}

      {backfillOpen && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
             data-testid="route-map-backfill-modal"
             onClick={() => setBackfillOpen(false)}>          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6"
               onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-2">
              Backfill stop addresses
            </h3>
            <p className="text-xs text-zinc-500 mb-4">
              Runs reverse-geocoding on up to 100 stops that currently
              have no address. Cached results are free; new lookups
              call Mapbox. Skipped entirely if MAPBOX_ACCESS_TOKEN is
              unset.
            </p>
            {backfillResult && (
              <pre className="text-[11px] bg-zinc-50 border border-zinc-200 rounded p-2 mb-3 overflow-x-auto">
                {JSON.stringify(backfillResult, null, 2)}
              </pre>
            )}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setBackfillOpen(false)}
                       className="px-3 py-1.5 rounded border border-zinc-200 text-sm">
                Close
              </button>
              <button type="button" onClick={runBackfill}
                       disabled={backfillBusy}
                       className="px-3 py-1.5 rounded bg-sky-600 text-white text-sm disabled:opacity-50"
                       data-testid="route-map-backfill-submit">
                {backfillBusy ? "Running…" : "Run backfill"}
              </button>
            </div>
          </div>
        </div>
      )}
      {exportOpen && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
             data-testid="route-map-export-modal"
             onClick={() => setExportOpen(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6"
               onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-3">Export CSV</h3>
            <div className="text-xs text-zinc-500 mb-3">
              Range: {day} · single-day export.
            </div>
            <div className="mb-3">
              <div className="text-xs text-zinc-600 mb-1">Scope</div>
              <label className="text-sm inline-flex items-center gap-1 mr-4">
                <input type="radio" name="scope" value="tech"
                        checked={exportScope === "tech"}
                        onChange={() => setExportScope("tech")}
                        data-testid="export-scope-tech" />
                This tech only
              </label>
              <label className="text-sm inline-flex items-center gap-1">
                <input type="radio" name="scope" value="all"
                        checked={exportScope === "all"}
                        onChange={() => setExportScope("all")}
                        data-testid="export-scope-all" />
                All techs
              </label>
            </div>
            <div className="mb-4">
              <div className="text-xs text-zinc-600 mb-1">Kind</div>
              <label className="text-sm inline-flex items-center gap-1 mr-4">
                <input type="radio" name="kind" value="stops"
                        checked={exportKind === "stops"}
                        onChange={() => setExportKind("stops")}
                        data-testid="export-kind-stops" />
                Stops
              </label>
              <label className="text-sm inline-flex items-center gap-1">
                <input type="radio" name="kind" value="pings"
                        checked={exportKind === "pings"}
                        onChange={() => setExportKind("pings")}
                        data-testid="export-kind-pings" />
                Raw pings
              </label>
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setExportOpen(false)}
                       className="px-3 py-1.5 rounded border border-zinc-200 text-sm">
                Cancel
              </button>
              <a
                href={(() => {
                  const from = `${day}T00:00:00Z`;
                  const to = `${day}T23:59:59Z`;
                  const kindPath = exportKind === "pings"
                                     ? "pings.csv" : "activity.csv";
                  const base = process.env.REACT_APP_BACKEND_URL || "";
                  const uid = exportScope === "tech"
                                ? `&user_id=${encodeURIComponent(techId || "")}`
                                : "";
                  return `${base}/api/admin/gps/export/${kindPath}`
                       + `?from=${encodeURIComponent(from)}`
                       + `&to=${encodeURIComponent(to)}${uid}`;
                })()}
                target="_blank" rel="noopener noreferrer"
                onClick={() => setExportOpen(false)}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 text-white text-sm no-underline"
                data-testid="export-download-btn">
                Download
              </a>
            </div>
          </div>
        </div>
      )}

    </div>
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
