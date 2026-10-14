/**
 * Feb-2026 · ScheduleMap — Google Maps stops for the current day.
 *
 * Compact map that sits above ``<ScheduleDayDnDPanel>`` on the
 * admin Schedule page. One pin per job with resolvable coords
 * (``job.location_lat`` + ``job.location_lng`` — projected server-
 * side from ``customers.service_lat`` / ``service_lng``, see
 * ``routers/jobs.py::list_jobs``). Pin colour follows the same
 * ``techColorMap`` the schedule calendar uses so a stop's colour on
 * the map matches its card / event tile below.
 *
 * Reuses the app-wide ``<APIProvider>`` that ``AppLayout`` already
 * mounts (see ``layouts/AppLayout.jsx:264-274``) — no new library,
 * no new provider wrapping needed.
 *
 * Empty-state contract: when zero jobs in ``jobs`` resolve to
 * coords, the component returns ``null`` — the schedule page shows
 * no gray placeholder box.
 *
 * When ``REACT_APP_GOOGLE_MAPS_API_KEY`` is unset the underlying
 * ``<Map>`` renders a light-gray "Map unavailable" tile — no extra
 * work required from this component; the ``<APIProvider>`` mount
 * point handles the fallback itself.
 *
 * ─────────────────────────────────────────────────────────────
 * Feb-2026 · Batch #4 · Item 4 — map pin count bug
 *
 *   Root cause of user-reported "17 jobs but only 8 pins":
 *   multiple jobs at the same customer address were pinning to the
 *   exact same ``(lat, lng)`` and rendering as pin-on-pin (visually
 *   collapsed to one). The dedupe pass below assigns a small
 *   circular spider-offset (< 15m) to duplicate coord groups so
 *   every job is discernible even at moderate zoom.
 *
 *   Additional guardrails:
 *     • Jobs without valid coords are counted + surfaced via the
 *       ``schedule-map-missing-count`` badge in the map corner
 *       (plus a ``console.warn`` with the offending customer IDs).
 *     • ``map.fitBounds`` includes ALL renderable pins on load so
 *       nothing is clipped by the initial viewport.
 *     • Marker clustering (``@googlemaps/markerclusterer``) kicks
 *       in above the dedupe pass; cluster bubbles carry a count
 *       badge so the operator sees "these 8 pins are stacked at
 *       this address" rather than perceiving 8 as the total.
 * ─────────────────────────────────────────────────────────────
 */
import React, { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { Map, AdvancedMarker, InfoWindow, useMap } from "../../lib/maps";
import { MarkerClusterer } from "@googlemaps/markerclusterer";
import { colors } from "@/theme";
import TeardropPin from "@/components/maps/TeardropPin";
import { CustomerLink, AddressLink } from "@/components/customer";
import { PIN_COLOR_BY_DAY } from "@/pages/dispatch/dispatchColors";
// P1 Phase 3 · Feb-2026 — Live technician GPS pin overlay.
// Polls GET /api/workforce/live-locations every 30s, pauses on
// tab-hide, admin-defaulted ON (persisted in localStorage).
import {
  useLiveTechLocations,
  colorForStaleness,
  formatAge,
} from "@/hooks/useLiveTechLocations";

// Deterministic fallback color for jobs whose technician has no
// ``display_color_hex`` picked (or is unassigned) AND for stops
// with no resolvable service-day (missing / malformed
// ``scheduled_date``).
const _UNASSIGNED_COLOR = "#94A3B8"; // slate-400
const _AZ_CENTER = { lat: 33.6975, lng: -112.3708 };
// Spider-offset radius in degrees (~0.00012 lat ≈ 13m).
// Small enough that pins at the same address still cluster in the
// operator's mind, large enough that they're individually clickable
// at typical urban zoom levels.
const _SPIDER_RADIUS_DEG = 0.00012;

// Feb-2026 · ScheduleMap Tech/Day color toggle — localStorage key
// mirrors the Dispatch Board's ``dispatch.pin_color_mode`` naming
// so both surfaces share the same prefs pattern (see
// ``pages/dispatch/dispatchColors.js``).
const _PIN_COLOR_MODE_KEY = "schedule_map.pin_color_mode";
const _PIN_COLOR_MODES = /** @type {const} */ (["tech", "day"]);

// Visual-emphasis presets per active mode.  Both modes always pass
// the SAME channels to the pin (fill = tech color, stroke = day
// color); the toggle changes how heavily each channel is drawn.
//   • ``tech``: thin stroke, fully opaque fill  → tech color leads.
//   • ``day`` : thick stroke, dimmed fill        → day color leads.
const _MODE_EMPHASIS = {
  tech: { strokeWidth: 1,   fillOpacity: 1 },
  day:  { strokeWidth: 3,   fillOpacity: 0.55 },
};

function _loadPinColorMode() {
  try {
    const v = (typeof window !== "undefined")
      ? window.localStorage.getItem(_PIN_COLOR_MODE_KEY) : null;
    if (v && _PIN_COLOR_MODES.includes(v)) return v;
  } catch { /* jsdom / private-mode */ }
  return "tech";
}

function _savePinColorMode(mode) {
  try {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(_PIN_COLOR_MODE_KEY, mode);
    }
  } catch { /* jsdom / private-mode */ }
}

// Feb-2026 · ScheduleMap Tech/Day color toggle — resolve a
// stop's day-color from its ``scheduled_date``. Accepts ISO
// ``YYYY-MM-DD``, full ISO datetime, or any string ``Date`` can
// parse; returns ``null`` when the date can't be resolved so the
// caller can drop to the neutral fallback.
function _dayColorForJob(job) {
  const raw = job?.scheduled_date;
  if (!raw) return null;
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return null;
  // ``Date.getUTCDay`` avoids browser-locale drift when the date
  // is a bare ``YYYY-MM-DD`` (parsed as UTC midnight); the pin
  // color palette is keyed by three-letter lowercase day tokens
  // shared with ``pages/dispatch/dispatchColors.js``.
  const idx = d.getUTCDay(); // 0=Sun … 6=Sat
  const tok = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"][idx];
  return PIN_COLOR_BY_DAY[tok] || null;
}

function _fmtTime(job) {
  const raw = job?.scheduled_time || "";
  if (!raw) return null;
  if (/^\d{1,2}:\d{2}/.test(raw)) return raw.slice(0, 5);
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function _resolveTechName(job, techs) {
  if (!job.technician_id) return "Unassigned";
  const t = techs.find((x) => (x.id || x.user_id) === job.technician_id);
  return t?.name || t?.display_name || `Tech ${String(job.technician_id).slice(0, 6)}…`;
}


/**
 * Build a stable per-coord bucket + spread duplicates in a circle.
 *
 * Returns ``{ pins, missing }`` where:
 *   • ``pins`` is the flat list of ``{job, lat, lng, hasCoords}``
 *     with adjusted lat/lng (spider-offset applied to duplicates).
 *   • ``missing`` is the flat list of jobs whose coords could not
 *     be resolved. These are counted + logged but not rendered on
 *     the map.
 *
 * Exported for direct unit testing.
 */
export function _buildDedupedPins(jobs) {
  const missing = [];
  // Bucket by rounded coord (5 decimal places ≈ 1m); jobs sharing a
  // bucket get spider-offset. Using round-to-5 rather than exact
  // equality catches near-duplicate coords too (common when
  // geocoding maps a lot number to the same street segment).
  //
  // NB — we use a plain object dict rather than the built-in ``Map``
  // constructor because this module imports ``Map`` from
  // ``../../lib/maps`` (Google-Maps React wrapper) at the top of the
  // file, which shadows the global constructor.
  const buckets = Object.create(null);
  const clean = [];
  for (const j of jobs || []) {
    const lat = Number(j?.location_lat);
    const lng = Number(j?.location_lng);
    const hasCoords = Number.isFinite(lat) && Number.isFinite(lng)
      && !(lat === 0 && lng === 0);
    if (!hasCoords) {
      missing.push(j);
      continue;
    }
    const key = `${lat.toFixed(5)}:${lng.toFixed(5)}`;
    const bucket = buckets[key] || { key, lat, lng, members: [] };
    bucket.members.push(j);
    buckets[key] = bucket;
    clean.push({ job: j, bucketKey: key });
  }
  const pins = [];
  for (const { job, bucketKey } of clean) {
    const bucket = buckets[bucketKey];
    const size = bucket.members.length;
    if (size === 1) {
      pins.push({ job, lat: bucket.lat, lng: bucket.lng, hasCoords: true });
      continue;
    }
    // Spider-offset: N members arranged on a circle of radius
    // ``_SPIDER_RADIUS_DEG`` around the shared centroid.
    const idx = bucket.members.findIndex((m) => m.id === job.id);
    const angle = (idx / size) * 2 * Math.PI;
    const dLat = Math.sin(angle) * _SPIDER_RADIUS_DEG;
    // Slight latitude-adjusted lng scale so the spread looks circular
    // at any latitude on the map.
    const dLng = Math.cos(angle) * _SPIDER_RADIUS_DEG
      / Math.max(Math.cos(bucket.lat * Math.PI / 180), 0.2);
    pins.push({
      job,
      lat: bucket.lat + dLat,
      lng: bucket.lng + dLng,
      hasCoords: true,
      spidered: true,
    });
  }
  return { pins, missing };
}


/**
 * Inner component: uses ``useMap`` (only valid inside ``<Map>``)
 * to attach a ``MarkerClusterer`` + drive ``fitBounds`` on payload
 * change. Rendering the AdvancedMarkers themselves happens here so
 * we can hand raw marker refs to the clusterer without React
 * fighting Google Maps for DOM ownership.
 */
function _ClusteredMarkers({ pins, techColorMap, colorMode, onSelect }) {
  const map = useMap();
  const markersRef = useRef({});
  const clustererRef = useRef(null);

  // Attach the clusterer once when the map is ready.
  useEffect(() => {
    if (!map) return undefined;
    if (!clustererRef.current) {
      clustererRef.current = new MarkerClusterer({
        map,
        markers: [],
        // Numbered cluster bubbles — Google's default renderer
        // shows the count inside the bubble, which addresses the
        // Item 4 concern ("only 8 pins" perception when the true
        // count was 17 stacked at fewer addresses).
      });
    }
    return () => {
      if (clustererRef.current) {
        clustererRef.current.clearMarkers();
        clustererRef.current.setMap(null);
        clustererRef.current = null;
      }
    };
  }, [map]);

  // Re-fit the map bounds every time the pin set changes so all
  // pins are visible on initial load (and on filter / date change).
  useEffect(() => {
    if (!map || !pins.length) return;
    // Guard: some test mocks return a bare object without the
    // ``fitBounds`` / ``LatLngBounds`` globals — bail cleanly.
    const g = typeof window !== "undefined" ? window.google : null;
    if (!g?.maps?.LatLngBounds || typeof map.fitBounds !== "function") return;
    const bounds = new g.maps.LatLngBounds();
    for (const p of pins) bounds.extend({ lat: p.lat, lng: p.lng });
    map.fitBounds(bounds, 48);  // 48px padding
  }, [map, pins]);

  const emphasis = _MODE_EMPHASIS[colorMode] || _MODE_EMPHASIS.tech;

  return (
    <>
      {pins.map(({ job, lat, lng }) => {
        // Fill = assigned tech's brand color → gray fallback when
        // the stop is unassigned (or the tech has no picked color).
        const fillHex = (techColorMap && job.technician_id
          ? techColorMap.get(job.technician_id)
          : null) || _UNASSIGNED_COLOR;
        // Stroke = service-day color → gray fallback when the
        // scheduled_date is missing / unparseable.
        const strokeHex = _dayColorForJob(job) || _UNASSIGNED_COLOR;
        // Route-index label — 1-based. Undefined / null route_index
        // means the stop hasn't been slotted into a route yet; we
        // omit the label rather than showing a misleading ``01``.
        const routeIdx = job?.route_index;
        const pinLabel = Number.isFinite(routeIdx)
          ? routeIdx + 1
          : undefined;
        return (
          <AdvancedMarker
            key={job.id}
            position={{ lat, lng }}
            onClick={() => onSelect(job.id)}
            ref={(el) => {
              // ``@vis.gl/react-google-maps`` forwards refs to the
              // underlying ``AdvancedMarkerElement`` — feed it into
              // the clusterer so cluster bubbles auto-appear when
              // pins overlap at low zoom.
              const clusterer = clustererRef.current;
              const prev = markersRef.current[job.id];
              if (!clusterer) return;
              if (prev && prev !== el) {
                clusterer.removeMarker(prev);
                delete markersRef.current[job.id];
              }
              if (el) {
                markersRef.current[job.id] = el;
                clusterer.addMarker(el);
              }
            }}
          >
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onSelect(job.id); }}
              aria-label={`Job pin for ${job.customer_name || "job"}`}
              data-testid={`schedule-map-pin-${job.id}`}
              data-color-mode={colorMode}
              style={{
                background: "transparent",
                border: 0,
                padding: 0,
                cursor: "pointer",
                filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.35))",
                transform: "translateY(-24px)",
              }}
            >
              {/* Phase M1 · Feb-2026 · Sitewide custom teardrop pin.
                   Per-marker color semantics (assigned-tech color
                   via ``techColorMap`` → unassigned slate fallback)
                   are preserved verbatim; only the SHAPE changes.

                   Feb-2026 · Tech/Day color toggle — fill always
                   comes from the tech color, stroke always from
                   the service-day color. The active mode dials the
                   stroke width + fill opacity to emphasize one
                   channel visually. */}
              <TeardropPin color={fillHex}
                             stroke={strokeHex}
                             strokeWidth={emphasis.strokeWidth}
                             fillOpacity={emphasis.fillOpacity}
                             label={pinLabel}
                             testid={`schedule-map-pin-${job.id}-svg`} />
            </button>
          </AdvancedMarker>
        );
      })}
    </>
  );
}


/**
 * ``jobs`` — day's jobs list (already filtered to the focused date).
 * ``techs`` — techs list for tech-name popover lookup.
 * ``techColorMap`` — Map<techId, colorHex> shared with the schedule
 *                    calendar / grid so pin colour matches cards.
 */
export default function ScheduleMap({ jobs = [], techs = [], techColorMap }) {
  const [activeId, setActiveId] = useState(null);
  const [activeLiveTechId, setActiveLiveTechId] = useState(null);
  // Feb-2026 · Tech/Day color toggle. Lazy-init from localStorage
  // so the first paint already reflects the operator's saved
  // preference — no post-mount flash from ``tech`` to ``day``.
  const [colorMode, setColorMode] = useState(() => _loadPinColorMode());

  // P1 Phase 3 · live-tech overlay source — polls every 30s,
  // pauses on tab-hide, admin-defaulted ON.
  const {
    pings: livePings,
    enabled: liveEnabled,
    setEnabled: setLiveEnabled,
  } = useLiveTechLocations();

  const { pins, missing } = useMemo(() => _buildDedupedPins(jobs), [jobs]);

  // Log the customer IDs of jobs without map coords so admins can
  // fix the underlying customer record. Once per pin-set change.
  useEffect(() => {
    if (!missing.length) return;
    // eslint-disable-next-line no-console
    console.warn(
      `[schedule-map] ${missing.length} job(s) missing map coords:`,
      missing.map((j) => ({
        job_id: j.id,
        customer_id: j.customer_id,
        customer_name: j.customer_name,
        address: j.address,
      })),
    );
  }, [missing]);

  const active = useMemo(
    () => pins.find((p) => p.job.id === activeId) || null,
    [pins, activeId],
  );

  const initialCenter = useMemo(() => {
    if (pins.length > 0) return { lat: pins[0].lat, lng: pins[0].lng };
    return _AZ_CENTER;
  }, [pins.length > 0]); // eslint-disable-line react-hooks/exhaustive-deps

  const onSelect = useCallback((id) => {
    setActiveId((cur) => (cur === id ? null : id));
  }, []);

  // Feb-2026 · Tech/Day color toggle — click / keyboard handler.
  const _onSelectColorMode = useCallback((mode) => {
    if (!_PIN_COLOR_MODES.includes(mode)) return;
    setColorMode(mode);
    _savePinColorMode(mode);
  }, []);

  // Empty-state contract — return null so the schedule page doesn't
  // render an empty gray box. Note: even if all coords are missing,
  // we still return null (the missing-count badge only surfaces
  // when at least one pin renders).
  if (pins.length === 0) return null;

  return (
    <div
      className="rounded-xl overflow-hidden mb-3"
      style={{
        border: `1px solid ${colors.border}`,
        height: 'clamp(240px, 45vh, 480px)',
        position: "relative",
      }}
      data-testid="schedule-map-container"
    >
      {/* Feb-2026 · Tech/Day color toggle — header pill sitting on
          the top-left of the map tile. Keyboard-accessible via the
          native ``role=radiogroup`` / ``role=radio`` semantics. */}
      <div
        role="radiogroup"
        aria-label="Color pins by"
        data-testid="schedule-map-color-toggle"
        style={{
          position: "absolute", top: 8, left: 8, zIndex: 5,
          display: "inline-flex",
          background: "rgba(255,255,255,0.94)",
          borderRadius: 999,
          padding: 3,
          boxShadow: "0 1px 3px rgba(0,0,0,0.18)",
          fontSize: 11,
          fontWeight: 600,
          gap: 2,
        }}
      >
        {_PIN_COLOR_MODES.map((mode) => {
          const isActive = mode === colorMode;
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={isActive}
              tabIndex={isActive ? 0 : -1}
              data-testid={`schedule-map-color-mode-${mode}`}
              data-active={isActive ? "true" : "false"}
              onClick={() => _onSelectColorMode(mode)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  _onSelectColorMode(mode);
                } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                  e.preventDefault();
                  const next = mode === "tech" ? "day" : "tech";
                  _onSelectColorMode(next);
                }
              }}
              style={{
                border: 0,
                cursor: "pointer",
                padding: "4px 10px",
                borderRadius: 999,
                background: isActive ? colors.onSurface : "transparent",
                color: isActive ? "#FFFFFF" : colors.onSurface,
                textTransform: "capitalize",
              }}
            >
              {mode}
            </button>
          );
        })}
      </div>
      {/* P1 Phase 3 · Live-tech overlay toggle. */}
      <button
        type="button"
        role="switch"
        aria-checked={liveEnabled}
        aria-label="Show live technician locations"
        data-testid="schedule-map-live-tech-toggle"
        data-enabled={liveEnabled ? "true" : "false"}
        onClick={() => setLiveEnabled(!liveEnabled)}
        style={{
          position: "absolute", top: 8, left: 120, zIndex: 5,
          background: liveEnabled ? "#22c55e" : "rgba(255,255,255,0.94)",
          color: liveEnabled ? "#FFFFFF" : colors.onSurface,
          border: 0, cursor: "pointer",
          borderRadius: 999, padding: "4px 10px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.18)",
          fontSize: 11, fontWeight: 600,
          display: "inline-flex", alignItems: "center", gap: 6,
        }}
      >
        <span
          style={{
            display: "inline-block", width: 8, height: 8,
            borderRadius: "50%",
            background: liveEnabled ? "#FFFFFF" : "#94a3b8",
          }}
          aria-hidden="true"
        />
        {liveEnabled ? "Live techs on" : "Show live techs"}
      </button>
      <Map
        mapId="SCHEDULE_MAP"
        defaultCenter={initialCenter}
        defaultZoom={11}
        gestureHandling="cooperative"
        disableDefaultUI={false}
        clickableIcons={false}
        style={{ width: "100%", height: "100%" }}
      >
        <_ClusteredMarkers
          pins={pins}
          techColorMap={techColorMap}
          colorMode={colorMode}
          onSelect={onSelect}
        />
        {/* Live-tech markers — outside the clusterer so a tech
            standing on top of a job pin is still individually
            visible. */}
        {liveEnabled ? livePings.map((p) => (
          <AdvancedMarker
            key={`live-${p.user_id}`}
            position={{ lat: p.lat, lng: p.lon }}
            onClick={() => setActiveLiveTechId(
              activeLiveTechId === p.user_id ? null : p.user_id,
            )}
            title={`${p.user_name} · ${formatAge(p.age_seconds)}`}
          >
            <div
              data-testid={`schedule-map-live-tech-pin-${p.user_id}`}
              data-staleness={p.staleness}
              style={{
                width: 14, height: 14, borderRadius: "50%",
                background: colorForStaleness(p.staleness),
                border: "2px solid #FFFFFF",
                boxShadow: "0 0 0 1px rgba(0,0,0,0.25), "
                  + "0 2px 4px rgba(0,0,0,0.3)",
              }}
            />
          </AdvancedMarker>
        )) : null}
        {liveEnabled && activeLiveTechId ? (() => {
          const lp = livePings.find(
            (x) => x.user_id === activeLiveTechId);
          if (!lp) return null;
          return (
            <InfoWindow
              position={{ lat: lp.lat, lng: lp.lon }}
              onCloseClick={() => setActiveLiveTechId(null)}
            >
              <div
                style={{ minWidth: 180, maxWidth: 240 }}
                data-testid={`schedule-map-live-tech-info-${lp.user_id}`}
              >
                <div style={{ fontWeight: 600, fontSize: 13,
                                color: colors.onSurface }}>
                  {lp.user_name}
                </div>
                <div style={{ fontSize: 12,
                                color: colors.onSurfaceSecondary,
                                marginTop: 2 }}>
                  updated {formatAge(lp.age_seconds)}
                </div>
                <div
                  style={{ fontSize: 11, marginTop: 4,
                             display: "inline-flex",
                             alignItems: "center", gap: 4,
                             color: colorForStaleness(lp.staleness),
                             textTransform: "capitalize" }}
                  data-testid={`schedule-map-live-tech-staleness-${lp.user_id}`}
                >
                  <span style={{
                    display: "inline-block", width: 6, height: 6,
                    borderRadius: "50%",
                    background: colorForStaleness(lp.staleness),
                  }} />
                  {lp.staleness}
                </div>
              </div>
            </InfoWindow>
          );
        })() : null}
        {active ? (
          <InfoWindow
            position={{ lat: active.lat, lng: active.lng }}
            onCloseClick={() => setActiveId(null)}
          >
            <div
              style={{ minWidth: 200, maxWidth: 260 }}
              data-testid="schedule-map-infowindow"
            >
              <div
                style={{ fontWeight: 600, fontSize: 13, color: colors.onSurface }}
                data-testid={`schedule-map-info-customer-${active.job.id}`}
              >
                <CustomerLink
                  customerId={active.job.customer_id}
                  name={active.job.customer_name || active.job.title || "Job"}
                />
              </div>
              {active.job.address ? (
                <div
                  style={{ fontSize: 12, color: colors.muted, marginTop: 2 }}
                  data-testid={`schedule-map-info-address-${active.job.id}`}
                >
                  <AddressLink address={active.job.address} />
                </div>
              ) : null}
              {_fmtTime(active.job) ? (
                <div
                  style={{ fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 4 }}
                  data-testid={`schedule-map-info-time-${active.job.id}`}
                >
                  {_fmtTime(active.job)}
                </div>
              ) : null}
              <div
                style={{ fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 4 }}
                data-testid={`schedule-map-info-tech-${active.job.id}`}
              >
                Tech: <strong>{_resolveTechName(active.job, techs)}</strong>
              </div>
            </div>
          </InfoWindow>
        ) : null}
      </Map>
      {/* Feb-2026 · Item 4 — badge surfaces when at least one job on
          this schedule cannot be plotted. Absolute-positioned so it
          overlays the map without shrinking the tile height. */}
      {missing.length > 0 ? (
        <div
          style={{
            position: "absolute", top: 8, right: 8, zIndex: 5,
            padding: "4px 8px", borderRadius: 6,
            background: "rgba(0,0,0,0.72)", color: "#fff",
            fontSize: 11, fontWeight: 600,
            pointerEvents: "none",
          }}
          data-testid="schedule-map-missing-count"
          title={
            "Some jobs on today's schedule couldn't be plotted — "
            + "check the console for their customer IDs."
          }
        >
          {missing.length} job{missing.length === 1 ? "" : "s"} missing location
        </div>
      ) : null}
    </div>
  );
}
