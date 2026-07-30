/**
 * Phase G5c · Feb-2026 — Animated Route Replay panel.
 *
 * Sits below the existing RouteMapPanel (G3) on
 * /admin/reports/driver-activity and plays back the driver's day on a
 * Google Map:
 *   • an animated marker walks along the ping trail chronologically
 *   • a polyline behind it grows as playback progresses
 *   • stops render as circles; the "current" stop is highlighted
 *   • Play/Pause, speed picker (1/2/5/10/30/60x), and a scrub bar
 *
 * Empty-state:  no pings                → compact "no data" card
 * Single-ping:  1 ping only             → static marker, no controls
 */
import React from "react";
import { Map, useMap, AdvancedMarker } from "@vis.gl/react-google-maps";
import { Play, Pause, RotateCcw, MapPin, Route, Clock } from "lucide-react";
import { colors } from "@/theme";
import useGpsRoute from "@/hooks/useGpsRoute";

const _SPEED_CHOICES = [1, 2, 5, 10, 30, 60];
const _IDLE_GAP_S = 5 * 60;         // gaps larger than 5 min are compressed
const _IDLE_COMPRESSED_S = 1;       // to 1 wall-second of animation

function _fmtHMS(sec) {
  const s = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(h)}:${pad(m)}:${pad(ss)}`;
}

function _fmtLocalTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit",
                                       second: "2-digit" });
  } catch { return iso; }
}

// Distance (metres) between two lat/lon points (haversine).
function _distM(lat1, lon1, lat2, lon2) {
  const R = 6371000, toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1), dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
      Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.asin(Math.min(1, Math.sqrt(a)));
}

// ── Build a "virtual" playback timeline that compresses idle gaps
//    (>5 min between consecutive pings → collapsed to 1s).
function buildPlaybackTimeline(pings) {
  const nodes = [];
  if (!Array.isArray(pings) || pings.length === 0) return { nodes, total: 0 };
  let cursor = 0;
  const first = new Date(pings[0].captured_at).getTime();
  nodes.push({
    lat: pings[0].lat, lon: pings[0].lon,
    real_at: pings[0].captured_at, real_ms: first,
    playback_s: cursor,
  });
  for (let i = 1; i < pings.length; i += 1) {
    const cur = pings[i], prev = pings[i - 1];
    const realDeltaS = Math.max(
      0, (new Date(cur.captured_at).getTime()
          - new Date(prev.captured_at).getTime()) / 1000);
    const compressed = realDeltaS > _IDLE_GAP_S
      ? _IDLE_COMPRESSED_S
      : realDeltaS;
    cursor += compressed;
    nodes.push({
      lat: cur.lat, lon: cur.lon,
      real_at: cur.captured_at,
      real_ms: new Date(cur.captured_at).getTime(),
      playback_s: cursor,
    });
  }
  return { nodes, total: cursor };
}

// Linear interpolate the marker position at ``playback_s``.
function interpolate(nodes, playbackS) {
  if (!nodes.length) return null;
  if (playbackS <= 0) return { lat: nodes[0].lat, lon: nodes[0].lon,
                                real_at: nodes[0].real_at, index: 0 };
  if (playbackS >= nodes[nodes.length - 1].playback_s) {
    const last = nodes[nodes.length - 1];
    return { lat: last.lat, lon: last.lon, real_at: last.real_at,
              index: nodes.length - 1 };
  }
  // Binary search for the segment.
  let lo = 0, hi = nodes.length - 1;
  while (lo + 1 < hi) {
    const mid = (lo + hi) >>> 1;
    if (nodes[mid].playback_s <= playbackS) lo = mid;
    else hi = mid;
  }
  const a = nodes[lo], b = nodes[hi];
  const span = Math.max(1e-6, b.playback_s - a.playback_s);
  const t = (playbackS - a.playback_s) / span;
  return {
    lat: a.lat + (b.lat - a.lat) * t,
    lon: a.lon + (b.lon - a.lon) * t,
    real_at: a.real_at,
    index: lo,
  };
}

// ── Trail polyline (grows with playback) ────────────────────────────
function TrailPolyline({ pathLatLng, done }) {
  const map = useMap();
  const lineRef = React.useRef(null);
  React.useEffect(() => {
    if (!map || typeof window === "undefined") return undefined;
    const gm = window.google?.maps;
    if (!gm) return undefined;
    if (!lineRef.current) {
      lineRef.current = new gm.Polyline({
        map, geodesic: true,
        strokeColor: done ? "#065F46" : "#0EA5E9",
        strokeOpacity: 0.85, strokeWeight: 3,
        clickable: false, zIndex: 5,
      });
    }
    lineRef.current.setOptions({
      path: pathLatLng.map(([lat, lng]) => ({ lat, lng })),
      strokeColor: done ? "#065F46" : "#0EA5E9",
    });
    return undefined;
  }, [map, pathLatLng, done]);
  React.useEffect(() => () => {
    if (lineRef.current) { lineRef.current.setMap(null);
                            lineRef.current = null; }
  }, []);
  return null;
}

// ── Stop overlays (colored by "is current" flag) ────────────────────
function StopOverlays({ stops, currentStopId }) {
  const map = useMap();
  const circlesRef = React.useRef([]);
  React.useEffect(() => {
    if (!map || typeof window === "undefined") return undefined;
    const gm = window.google?.maps;
    if (!gm) return undefined;
    circlesRef.current.forEach((c) => c.setMap(null));
    circlesRef.current = [];
    (stops || []).forEach((s) => {
      if (typeof s.center_lat !== "number") return;
      const active = s.id === currentStopId;
      circlesRef.current.push(new gm.Circle({
        map,
        center: { lat: s.center_lat, lng: s.center_lon },
        radius: Math.max(15, s.radius_m || 25),
        fillColor: active ? "#DB2777" : "#F59E0B",
        fillOpacity: active ? 0.5 : 0.25,
        strokeColor: active ? "#DB2777" : "#F59E0B",
        strokeWeight: active ? 3 : 1,
        clickable: false, zIndex: 3,
      }));
    });
    return undefined;
  }, [map, stops, currentStopId]);
  React.useEffect(() => () => {
    circlesRef.current.forEach((c) => c.setMap(null));
    circlesRef.current = [];
  }, []);
  return null;
}

// ── Main panel ──────────────────────────────────────────────────────
export default function RouteReplayPanel({ techId, day }) {
  const { route, loading, error } = useGpsRoute({ techId, day });
  const mapsKey = process.env.REACT_APP_GOOGLE_MAPS_API_KEY
                  || process.env.REACT_APP_GOOGLE_API_KEY || "";

  const timeline = React.useMemo(
    () => buildPlaybackTimeline(route?.pings || []), [route]);
  const nodes = timeline.nodes;
  const totalPlaybackS = timeline.total;

  const [speed, setSpeed] = React.useState(5);
  const [playing, setPlaying] = React.useState(false);
  const [playbackS, setPlaybackS] = React.useState(0);
  const rafRef = React.useRef(null);
  const lastTsRef = React.useRef(null);

  // Reset playback when the route changes.
  React.useEffect(() => {
    setPlaybackS(0); setPlaying(false); lastTsRef.current = null;
  }, [techId, day, nodes.length]);

  // rAF loop.
  React.useEffect(() => {
    if (!playing || totalPlaybackS === 0) return undefined;
    const tick = (ts) => {
      if (lastTsRef.current == null) lastTsRef.current = ts;
      const dtMs = ts - lastTsRef.current;
      lastTsRef.current = ts;
      setPlaybackS((prev) => {
        const next = prev + (dtMs / 1000) * speed;
        if (next >= totalPlaybackS) {
          setPlaying(false);
          return totalPlaybackS;
        }
        return next;
      });
      rafRef.current = window.requestAnimationFrame(tick);
    };
    rafRef.current = window.requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) window.cancelAnimationFrame(rafRef.current);
      lastTsRef.current = null;
    };
  }, [playing, speed, totalPlaybackS]);

  const marker = React.useMemo(
    () => interpolate(nodes, playbackS), [nodes, playbackS]);

  const trailPath = React.useMemo(() => {
    if (!nodes.length || !marker) return [];
    const path = nodes.slice(0, marker.index + 1)
                       .map((n) => [n.lat, n.lon]);
    path.push([marker.lat, marker.lon]);
    return path;
  }, [nodes, marker]);

  const currentStop = React.useMemo(() => {
    if (!marker || !route?.stops?.length) return null;
    for (const s of route.stops) {
      if (typeof s.center_lat !== "number") continue;
      const d = _distM(marker.lat, marker.lon,
                        s.center_lat, s.center_lon);
      if (d <= Math.max(20, s.radius_m || 25)) return s;
    }
    return null;
  }, [marker, route]);

  const center = React.useMemo(() => {
    if (!nodes.length) return { lat: 33.6975, lng: -112.3708 };
    const midIdx = Math.floor(nodes.length / 2);
    return { lat: nodes[midIdx].lat, lng: nodes[midIdx].lon };
  }, [nodes]);

  const zoomForSpan = React.useMemo(() => {
    if (nodes.length < 2) return 14;
    const lats = nodes.map((n) => n.lat), lons = nodes.map((n) => n.lon);
    const span = Math.max(
      Math.max(...lats) - Math.min(...lats),
      Math.max(...lons) - Math.min(...lons));
    if (span > 0.5) return 9;
    if (span > 0.2) return 10;
    if (span > 0.08) return 11;
    if (span > 0.03) return 12;
    if (span > 0.01) return 13;
    return 14;
  }, [nodes]);

  const done = totalPlaybackS > 0 && playbackS >= totalPlaybackS;
  const hasMaps = Boolean(mapsKey);

  // ── Empty / edge states ─────────────────────────────────────────
  if (!techId || !day) return null;
  if (loading) {
    return (
      <div className="mt-3 rounded-xl p-4"
           style={{ background: colors.surface,
                    border: `1px solid ${colors.border}` }}
           data-testid="route-replay-loading">
        <div className="text-sm" style={{ color: colors.muted }}>
          Loading replay…
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="mt-3 rounded-xl p-4"
           style={{ background: colors.surface,
                    border: `1px solid ${colors.border}` }}
           data-testid="route-replay-error">
        <div className="text-sm" style={{ color: colors.muted }}>
          Replay unavailable: {error}
        </div>
      </div>
    );
  }
  if (!nodes.length) {
    return (
      <section className="mt-3 rounded-xl p-6 flex items-center gap-3"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="route-replay-empty">
        <div className="rounded-full p-2"
             style={{ background: "#F1F5F9", color: "#64748B" }}>
          <Route size={20} />
        </div>
        <div>
          <div className="text-sm font-semibold"
                style={{ color: colors.onSurface }}
                data-testid="route-replay-empty-title">
            No pings for this day
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Route Replay activates once GPS pings arrive for the
            selected technician + date.
          </div>
        </div>
      </section>
    );
  }
  if (nodes.length === 1) {
    return (
      <section className="mt-3 rounded-xl p-6"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid="route-replay-single-ping">
        <div className="flex items-center gap-3">
          <MapPin size={18} style={{ color: colors.muted }} />
          <div>
            <div className="text-sm font-semibold"
                  style={{ color: colors.onSurface }}>
              Only one ping in this window
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              Nothing to animate — captured at {" "}
              {_fmtLocalTime(nodes[0].real_at)}
              {" · "}
              {nodes[0].lat.toFixed(5)}, {nodes[0].lon.toFixed(5)}
            </div>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="mt-3 rounded-xl p-4 space-y-3"
             style={{ background: colors.surface,
                      border: `1px solid ${colors.border}` }}
             data-testid="route-replay-panel">
      <header className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold"
               style={{ color: colors.onSurface }}
               data-testid="route-replay-title">
            Route Replay
          </h3>
          <div className="text-xs" style={{ color: colors.muted }}>
            {nodes.length} pings · {_fmtHMS(route?.playback_duration_s || 0)}
            {" of real elapsed time · animation compresses idle gaps"}
          </div>
        </div>
        <div className="text-xs" style={{ color: colors.muted }}
             data-testid="route-replay-time-display">
          <Clock size={12} className="inline mr-1" />
          {marker ? _fmtLocalTime(marker.real_at) : "—"}
        </div>
      </header>

      {hasMaps ? (
        <div className="rounded-lg overflow-hidden"
             style={{ height: "min(50vh, 480px)", minHeight: 320,
                      border: `1px solid ${colors.border}` }}
             data-testid="route-replay-map">
          <Map
            mapId="DEMO_MAP_ID"
            defaultCenter={center}
            defaultZoom={zoomForSpan}
            gestureHandling="cooperative"
            clickableIcons={false}
            style={{ width: "100%", height: "100%" }}
          >
            <TrailPolyline pathLatLng={trailPath} done={done} />
            <StopOverlays stops={route?.stops || []}
                           currentStopId={currentStop?.id} />
            {marker && (
              <AdvancedMarker position={{ lat: marker.lat,
                                           lng: marker.lon }}
                              zIndex={10}
                              data-testid="route-replay-marker">
                <div style={{
                  width: 22, height: 22, borderRadius: 11,
                  background: done ? "#065F46" : "#0EA5E9",
                  border: "3px solid #FFFFFF",
                  boxShadow: "0 2px 6px rgba(0,0,0,0.35)",
                }} />
              </AdvancedMarker>
            )}
          </Map>
        </div>
      ) : (
        <div className="rounded-lg p-6 text-sm"
             style={{ background: "#F8FAFC", color: colors.muted }}
             data-testid="route-replay-no-maps">
          Google Maps key missing — map preview disabled. Playback
          controls are still functional.
        </div>
      )}

      {/* Controls row */}
      <div className="flex items-center gap-3 flex-wrap"
           data-testid="route-replay-controls">
        {!done ? (
          <button type="button"
            onClick={() => setPlaying((p) => !p)}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded font-semibold text-white"
            style={{ background: playing ? "#DC2626" : "#0EA5E9" }}
            data-testid="route-replay-play">
            {playing ? <Pause size={14} /> : <Play size={14} />}
            {playing ? "Pause" : "Play"}
          </button>
        ) : (
          <button type="button"
            onClick={() => { setPlaybackS(0); setPlaying(true); }}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded font-semibold text-white"
            style={{ background: "#0EA5E9" }}
            data-testid="route-replay-again">
            <RotateCcw size={14} /> Play again
          </button>
        )}
        <label className="text-xs flex items-center gap-1"
               style={{ color: colors.muted }}>
          Speed
          <select value={speed}
            onChange={(e) => setSpeed(parseInt(e.target.value, 10))}
            className="ml-1 px-2 py-1 rounded text-sm"
            style={{ background: colors.surface,
                     color: colors.onSurface,
                     border: `1px solid ${colors.border}` }}
            data-testid="route-replay-speed">
            {_SPEED_CHOICES.map((s) => (
              <option key={s} value={s}>{s}x</option>
            ))}
          </select>
        </label>
        <div className="flex-1 flex items-center gap-2 min-w-[200px]">
          <input type="range" min={0} max={Math.max(1, totalPlaybackS)}
            step="0.1" value={playbackS}
            onChange={(e) => {
              setPlaybackS(parseFloat(e.target.value));
              setPlaying(false);
            }}
            className="flex-1"
            data-testid="route-replay-scrub" />
          <span className="text-xs font-mono w-20 text-right"
                style={{ color: colors.muted }}
                data-testid="route-replay-elapsed">
            {_fmtHMS(playbackS)} / {_fmtHMS(totalPlaybackS)}
          </span>
        </div>
      </div>

      {/* Legend: current stop */}
      <div className="text-xs flex items-center gap-3 flex-wrap"
           style={{ color: colors.muted }}
           data-testid="route-replay-legend">
        {done ? (
          <span data-testid="route-replay-done">
            Replay complete · {nodes.length} pings, {" "}
            {(route?.stops || []).length} stops visited.
          </span>
        ) : currentStop ? (
          <span data-testid="route-replay-current-stop">
            <MapPin size={12} className="inline mr-1"
                    style={{ color: "#DB2777" }} />
            At stop: {currentStop.attributed_customer_name
                       || currentStop.address?.formatted
                       || `${currentStop.center_lat?.toFixed(4)}, ${currentStop.center_lon?.toFixed(4)}`}
            {" · "}{Math.max(0,
                     nodes.length - (marker?.index || 0))} pings remaining
          </span>
        ) : (
          <span data-testid="route-replay-in-transit">
            {marker ? "Driving…" : "Ready to play"}
            {" · "}
            {Math.max(0, nodes.length - (marker?.index || 0))} pings remaining
          </span>
        )}
      </div>
    </section>
  );
}
