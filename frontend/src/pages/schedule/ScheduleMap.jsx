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
 */
import React, { useMemo, useState, useCallback } from "react";
import { Map, AdvancedMarker, InfoWindow } from "../../lib/maps";
import { colors } from "@/theme";

// Deterministic fallback color for jobs whose technician has no
// ``display_color_hex`` picked (or is unassigned).
const _UNASSIGNED_COLOR = "#94A3B8"; // slate-400
const _AZ_CENTER = { lat: 33.6975, lng: -112.3708 };

function _fmtTime(job) {
  const raw = job?.scheduled_time || "";
  if (!raw) return null;
  // Accept either bare "HH:MM" or full ISO. Return null on parse
  // failure — pill just hides the time row when unknown.
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
 * ``jobs`` — day's jobs list (already filtered to the focused date).
 * ``techs`` — techs list for tech-name popover lookup.
 * ``techColorMap`` — Map<techId, colorHex> shared with the schedule
 *                    calendar / grid so pin colour matches cards.
 */
export default function ScheduleMap({ jobs = [], techs = [], techColorMap }) {
  const [activeId, setActiveId] = useState(null);

  const pins = useMemo(() => {
    const out = [];
    for (const j of jobs || []) {
      const lat = Number(j?.location_lat);
      const lng = Number(j?.location_lng);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
      // Guard against 0/0 placeholder coords that occasionally slip
      // through legacy geocode failures — treat as "no coords".
      if (lat === 0 && lng === 0) continue;
      out.push({ job: j, lat, lng });
    }
    return out;
  }, [jobs]);

  const active = useMemo(
    () => pins.find((p) => p.job.id === activeId) || null,
    [pins, activeId],
  );

  // Auto-fit: seed initial center + zoom off the first pin.
  const initialCenter = useMemo(() => {
    if (pins.length > 0) return { lat: pins[0].lat, lng: pins[0].lng };
    return _AZ_CENTER;
  }, [pins.length > 0]); // eslint-disable-line react-hooks/exhaustive-deps

  const onSelect = useCallback((id) => {
    setActiveId((cur) => (cur === id ? null : id));
  }, []);

  // Empty-state contract — return null so the schedule page doesn't
  // render an empty gray box.
  if (pins.length === 0) return null;

  return (
    <div
      className="rounded-xl overflow-hidden mb-3"
      style={{
        border: `1px solid ${colors.border}`,
        height: 240,
      }}
      data-testid="schedule-map-container"
    >
      <Map
        mapId="SCHEDULE_MAP"
        defaultCenter={initialCenter}
        defaultZoom={11}
        gestureHandling="cooperative"
        disableDefaultUI={false}
        clickableIcons={false}
        style={{ width: "100%", height: "100%" }}
      >
        {pins.map(({ job, lat, lng }) => {
          const colorHex = (techColorMap && job.technician_id
            ? techColorMap.get(job.technician_id)
            : null) || _UNASSIGNED_COLOR;
          return (
            <AdvancedMarker
              key={job.id}
              position={{ lat, lng }}
              onClick={() => onSelect(job.id)}
            >
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onSelect(job.id); }}
                aria-label={`Job pin for ${job.customer_name || "job"}`}
                data-testid={`schedule-map-pin-${job.id}`}
                style={{
                  width: 20, height: 20, borderRadius: 999,
                  background: colorHex,
                  border: "2px solid #ffffff",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.35)",
                  cursor: "pointer",
                }}
              />
            </AdvancedMarker>
          );
        })}
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
                {active.job.customer_name || active.job.title || "Job"}
              </div>
              {active.job.address ? (
                <div
                  style={{ fontSize: 12, color: colors.muted, marginTop: 2 }}
                  data-testid={`schedule-map-info-address-${active.job.id}`}
                >
                  {active.job.address}
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
    </div>
  );
}
