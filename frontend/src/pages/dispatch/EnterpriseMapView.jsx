// EMV · Feb-2026 — Enterprise Map View.
//
// 7-day (default) bird's-eye map of every technician's routes for
// the current tenant. Pulls from ``GET /api/dispatch/enterprise-view``
// (read-only, span-capped, HD-A soft-delete aware).
//
// Reuses:
//   * ``@/lib/maps``            — provider-aware Map + AdvancedMarker.
//   * ``@googlemaps/markerclusterer`` — client-side pin clustering.
//   * ``@/components/maps/TeardropPin`` — sitewide teardrop pin SVG.
//   * ``@/theme.colors``        — border / muted / onSurface tokens.
//   * ``sonner``                — toast surface for fetch errors.
//
// Guardrails (contract locks):
//   * READ-ONLY — no writes trigger from this page.
//   * Deterministic fallback color for missing tech
//     ``display_color_hex`` is computed server-side; UI trusts the
//     ``color_source`` chip verbatim.
//   * Missing-coords banner only renders when the API returns > 0.
//   * Truncation banner renders when ``truncated=true``.
import React from "react";
import { format, addDays, parseISO } from "date-fns";
import { toast } from "sonner";
import { MarkerClusterer } from "@googlemaps/markerclusterer";
import { renderToStaticMarkup } from "react-dom/server";

import { api } from "@/api";
import { colors } from "@/theme";
import { Map, AdvancedMarker, useMap } from "@/lib/maps";
import TeardropPin from "@/components/maps/TeardropPin";

const AZ_CENTER = { lat: 33.6975, lng: -112.3708 }; // Vistancia default.
const DEFAULT_MAP_ID = "DEMO_MAP_ID";

function _todayIso() {
  return format(new Date(), "yyyy-MM-dd");
}

function _defaultEndIso(startIso) {
  try { return format(addDays(parseISO(startIso), 6), "yyyy-MM-dd"); }
  catch { return startIso; }
}

/**
 * Fetch wrapper. Surfaces 400 (bad range), 403 (RBAC), 500 (server) as
 * inline error state + toast so a dispatcher immediately sees "what
 * went wrong" without opening devtools.
 */
async function _fetchEnterpriseView({ startDate, endDate }) {
  const params = {};
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  return api.get("/dispatch/enterprise-view", params);
}

/** Client-side clusterer wrapper. Renders leaves as ``TeardropPin``
 * DOM nodes so cluster-view colors match the unclustered pins. */
function PinsLayer({ jobs, techColorById, onSelectJob, techVisibility }) {
  const map = useMap();
  const clustererRef = React.useRef(null);
  const markersRef = React.useRef([]);

  const visibleJobs = React.useMemo(
    () => jobs.filter((j) => {
      if (!j.has_coordinates) return false;
      const tid = j.technician_id;
      if (tid == null) return true;
      return techVisibility[tid] !== false;
    }),
    [jobs, techVisibility],
  );

  React.useEffect(() => {
    if (!map || typeof window === "undefined" || !window.google?.maps) return undefined;
    markersRef.current.forEach((m) => (m.map = null));
    markersRef.current = [];
    if (clustererRef.current) {
      clustererRef.current.clearMarkers();
      clustererRef.current = null;
    }
    if (visibleJobs.length === 0) return undefined;
    const gm = window.google.maps;
    if (!gm.marker?.AdvancedMarkerElement) return undefined;
    const newMarkers = visibleJobs.map((j) => {
      const wrap = document.createElement("div");
      wrap.style.cursor = "pointer";
      wrap.style.transform = "translateY(-24px)";
      wrap.setAttribute("data-emv-pin-job-id", j.id);
      wrap.setAttribute("data-testid", `emv-pin-${j.id}`);
      const color = techColorById[j.technician_id] || "#0EA5E9";
      wrap.innerHTML = renderToStaticMarkup(
        <TeardropPin
          color={color}
          testid={`emv-pin-${j.id}-svg`}
          label={
            typeof j.route_index === "number" && j.route_index >= 0
              ? j.route_index + 1
              : undefined
          }
        />,
      );
      const marker = new gm.marker.AdvancedMarkerElement({
        position: { lat: j.lat, lng: j.lng },
        content: wrap,
      });
      marker.addListener("gmp-click", () => onSelectJob(j));
      return marker;
    });
    markersRef.current = newMarkers;
    clustererRef.current = new MarkerClusterer({ map, markers: newMarkers });
    return () => {
      markersRef.current.forEach((m) => (m.map = null));
      markersRef.current = [];
      if (clustererRef.current) {
        clustererRef.current.clearMarkers();
        clustererRef.current = null;
      }
    };
  }, [map, visibleJobs, techColorById, onSelectJob]);

  // Non-clustered mode for very small lists — mirrors the DispatchMapView pattern.
  if (visibleJobs.length === 0 || visibleJobs.length > 30) return null;
  return visibleJobs.map((j) => (
    <AdvancedMarker
      key={j.id}
      position={{ lat: j.lat, lng: j.lng }}
      onClick={() => onSelectJob(j)}
    >
      <div style={{ transform: "translateY(-24px)" }}
             data-testid={`emv-pin-${j.id}`}>
        <TeardropPin
          color={techColorById[j.technician_id] || "#0EA5E9"}
          testid={`emv-pin-${j.id}-svg`}
          label={
            typeof j.route_index === "number" && j.route_index >= 0
              ? j.route_index + 1
              : undefined
          }
        />
      </div>
    </AdvancedMarker>
  ));
}

/** Encoded-polyline-free per-(tech, day) segment overlay. Draws a
 * connecting line through each tech's ordered stops for each day so
 * a dispatcher can eyeball crossovers + gaps. */
function RoutePolylines({ jobs, techColorById, techVisibility }) {
  const map = useMap();
  const linesRef = React.useRef([]);

  React.useEffect(() => {
    if (!map || typeof window === "undefined" || !window.google?.maps?.Polyline) return undefined;
    linesRef.current.forEach((l) => l.setMap(null));
    linesRef.current = [];

    const groups = new Map();
    jobs.forEach((j) => {
      if (!j.has_coordinates || !j.technician_id) return;
      if (techVisibility[j.technician_id] === false) return;
      const key = `${j.technician_id}|${j.scheduled_date}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(j);
    });

    const newLines = [];
    groups.forEach((group, key) => {
      if (group.length < 2) return;
      const [techId] = key.split("|");
      const ordered = [...group].sort((a, b) => {
        const ra = a.route_index ?? Number.MAX_SAFE_INTEGER;
        const rb = b.route_index ?? Number.MAX_SAFE_INTEGER;
        return ra - rb;
      });
      const path = ordered.map((j) => ({ lat: j.lat, lng: j.lng }));
      const line = new window.google.maps.Polyline({
        path,
        strokeColor: techColorById[techId] || "#0EA5E9",
        strokeOpacity: 0.75,
        strokeWeight: 3,
        map,
      });
      newLines.push(line);
    });
    linesRef.current = newLines;

    return () => {
      linesRef.current.forEach((l) => l.setMap(null));
      linesRef.current = [];
    };
  }, [map, jobs, techColorById, techVisibility]);

  return null;
}

function TechRow({ tech, checked, onToggle }) {
  return (
    <label
      className="flex items-center gap-3 px-3 py-2 rounded-md cursor-pointer transition-colors"
      style={{ borderBottom: `1px solid ${colors.border}` }}
      data-testid={`emv-sidebar-tech-row-${tech.id}`}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        data-testid={`emv-sidebar-tech-toggle-${tech.id}`}
        style={{ accentColor: tech.display_color_hex }}
      />
      <span
        aria-hidden
        style={{
          width: 12, height: 12, borderRadius: 999,
          background: tech.display_color_hex,
          border: `1px solid ${colors.border}`,
          flexShrink: 0,
        }}
        data-testid={`emv-sidebar-tech-swatch-${tech.id}`}
      />
      <span className="flex-1 text-sm" style={{ color: colors.onSurface }}>
        {tech.name}
      </span>
      <span
        className="text-xs"
        style={{ color: colors.muted }}
        data-testid={`emv-sidebar-tech-count-${tech.id}`}
      >
        {tech.job_count} {tech.job_count === 1 ? "job" : "jobs"}
      </span>
      {tech.color_source === "hash_fallback" ? (
        <span
          className="ml-1 text-[10px] px-1 py-0.5 rounded"
          title="Auto-assigned fallback color (no display_color_hex on tech row)"
          style={{
            background: "#FEF3C7", color: "#92400E",
            border: "1px solid #FDE68A",
          }}
          data-testid={`emv-sidebar-tech-fallback-${tech.id}`}
        >
          fallback
        </span>
      ) : null}
    </label>
  );
}

export default function EnterpriseMapView() {
  const [startDate, setStartDate] = React.useState(_todayIso);
  const [endDate, setEndDate] = React.useState(() => _defaultEndIso(_todayIso()));
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);
  const [data, setData] = React.useState(null);
  const [techVisibility, setTechVisibility] = React.useState({});
  const [selectedJob, setSelectedJob] = React.useState(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await _fetchEnterpriseView({ startDate, endDate });
      setData(res);
      // Default every tech to visible.
      setTechVisibility((prev) => {
        const next = { ...prev };
        (res.technicians || []).forEach((t) => {
          if (next[t.id] === undefined) next[t.id] = true;
        });
        return next;
      });
      setSelectedJob(null);
    } catch (e) {
      const status = e?.status || e?.response?.status;
      const detail = e?.data?.detail || e?.response?.data?.detail || e?.message || "Failed to load enterprise map";
      const msg = typeof detail === "string" ? detail : "Failed to load enterprise map";
      setError({ status, message: msg });
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [startDate, endDate]);

  React.useEffect(() => { load(); }, [load]);

  const techColorById = React.useMemo(() => {
    const map = {};
    (data?.technicians || []).forEach((t) => { map[t.id] = t.display_color_hex; });
    return map;
  }, [data]);

  const initialCenter = React.useMemo(() => {
    const first = (data?.jobs || []).find((j) => j.has_coordinates);
    if (first) return { lat: first.lat, lng: first.lng };
    return AZ_CENTER;
  }, [data]);

  const toggleTech = (tid) => {
    setTechVisibility((prev) => ({ ...prev, [tid]: !(prev[tid] !== false) }));
  };

  const bulkToggle = (visible) => {
    const next = {};
    (data?.technicians || []).forEach((t) => { next[t.id] = visible; });
    setTechVisibility(next);
  };

  return (
    <div
      className="flex flex-col gap-3 p-4"
      style={{ minHeight: "calc(100vh - 64px)" }}
      data-testid="emv-page"
    >
      {/* Header */}
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <h1
            className="text-2xl font-semibold tracking-tight"
            style={{ color: colors.onSurface }}
            data-testid="emv-title"
          >
            Enterprise Map View
          </h1>
          <p className="text-sm" style={{ color: colors.muted }}
             data-testid="emv-subtitle">
            All techs · All routes · 7-day bird's-eye
          </p>
        </div>
        <div className="flex items-end gap-2 ml-auto">
          <div className="flex flex-col">
            <label
              htmlFor="emv-start-date"
              className="text-xs mb-1"
              style={{ color: colors.muted }}
            >
              Start date
            </label>
            <input
              id="emv-start-date"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="text-sm px-2 py-1 rounded-md"
              style={{
                border: `1px solid ${colors.border}`,
                background: colors.surface,
                color: colors.onSurface,
              }}
              data-testid="emv-input-start-date"
            />
          </div>
          <div className="flex flex-col">
            <label
              htmlFor="emv-end-date"
              className="text-xs mb-1"
              style={{ color: colors.muted }}
            >
              End date
            </label>
            <input
              id="emv-end-date"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="text-sm px-2 py-1 rounded-md"
              style={{
                border: `1px solid ${colors.border}`,
                background: colors.surface,
                color: colors.onSurface,
              }}
              data-testid="emv-input-end-date"
            />
          </div>
          <button
            type="button"
            onClick={load}
            className="text-sm px-3 py-1.5 rounded-md font-medium"
            style={{
              background: colors.brand || "#0EA5E9",
              color: "#FFFFFF",
              border: `1px solid ${colors.border}`,
            }}
            data-testid="emv-refresh-button"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Loading skeleton */}
      {loading ? (
        <div
          className="rounded-lg p-6 text-sm"
          style={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            color: colors.muted,
          }}
          data-testid="emv-loading"
        >
          Loading enterprise map…
        </div>
      ) : null}

      {/* Error state */}
      {!loading && error ? (
        <div
          className="rounded-lg p-4 text-sm"
          style={{
            background: "#FEF2F2",
            border: "1px solid #FCA5A5",
            color: "#991B1B",
          }}
          role="alert"
          data-testid="emv-error"
        >
          <strong>Failed to load ({error.status || "network"})</strong>
          <div className="mt-1">{error.message}</div>
          <button
            type="button"
            onClick={load}
            className="mt-2 text-xs underline"
            data-testid="emv-error-retry"
          >
            Retry
          </button>
        </div>
      ) : null}

      {/* Banners */}
      {!loading && !error && data ? (
        <>
          {data.truncated ? (
            <div
              className="rounded-md px-3 py-2 text-xs"
              style={{
                background: "#FEF3C7", color: "#92400E",
                border: "1px solid #FDE68A",
              }}
              role="status"
              data-testid="emv-truncated-banner"
            >
              Result truncated to {data.cap} jobs
              (of {data.total_jobs_matched} matched). Narrow the date
              window for a full view.
            </div>
          ) : null}
          {(data.missing_coordinates_count || 0) > 0 ? (
            <div
              className="rounded-md px-3 py-2 text-xs"
              style={{
                background: "#EFF6FF", color: "#1E3A8A",
                border: "1px solid #BFDBFE",
              }}
              role="status"
              data-testid="emv-missing-coords-banner"
            >
              {data.missing_coordinates_count}{" "}
              {data.missing_coordinates_count === 1 ? "job is" : "jobs are"}{" "}
              missing coordinates and won&apos;t render on the map.
              Geocode via Dispatch → Board → &quot;Backfill coords&quot;.
            </div>
          ) : null}
        </>
      ) : null}

      {/* Main grid */}
      {!loading && !error && data ? (
        <div
          className="grid gap-3"
          style={{
            gridTemplateColumns: "minmax(240px, 320px) 1fr",
            minHeight: 520,
          }}
          data-testid="emv-layout"
        >
          {/* Sidebar */}
          <aside
            className="rounded-lg overflow-hidden flex flex-col"
            style={{
              background: colors.surface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="emv-sidebar"
          >
            <div
              className="flex items-center justify-between px-3 py-2 text-xs uppercase tracking-wide"
              style={{
                color: colors.muted,
                borderBottom: `1px solid ${colors.border}`,
              }}
            >
              <span>Technicians ({(data.technicians || []).length})</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => bulkToggle(true)}
                  className="underline"
                  data-testid="emv-sidebar-show-all"
                >
                  All
                </button>
                <button
                  type="button"
                  onClick={() => bulkToggle(false)}
                  className="underline"
                  data-testid="emv-sidebar-hide-all"
                >
                  None
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-auto" data-testid="emv-sidebar-list">
              {(data.technicians || []).length === 0 ? (
                <div
                  className="p-4 text-sm"
                  style={{ color: colors.muted }}
                  data-testid="emv-sidebar-empty"
                >
                  No technicians have jobs in this window.
                </div>
              ) : (
                (data.technicians || []).map((t) => (
                  <TechRow
                    key={t.id}
                    tech={t}
                    checked={techVisibility[t.id] !== false}
                    onToggle={() => toggleTech(t.id)}
                  />
                ))
              )}
            </div>
            <div
              className="px-3 py-2 text-xs"
              style={{
                color: colors.muted,
                borderTop: `1px solid ${colors.border}`,
              }}
              data-testid="emv-sidebar-totals"
            >
              {data.jobs.length} jobs · {data.days_in_range}-day window
            </div>
          </aside>

          {/* Map + optional details */}
          <div className="flex flex-col gap-2">
            <div
              className="rounded-lg overflow-hidden relative"
              style={{
                border: `1px solid ${colors.border}`,
                height: "min(72vh, 720px)",
                minHeight: 460,
              }}
              data-testid="emv-map-container"
            >
              <Map
                mapId={DEFAULT_MAP_ID}
                defaultCenter={initialCenter}
                defaultZoom={11}
                gestureHandling="cooperative"
                disableDefaultUI={false}
                clickableIcons={false}
                style={{ width: "100%", height: "100%" }}
              >
                <PinsLayer
                  jobs={data.jobs || []}
                  techColorById={techColorById}
                  onSelectJob={setSelectedJob}
                  techVisibility={techVisibility}
                />
                <RoutePolylines
                  jobs={data.jobs || []}
                  techColorById={techColorById}
                  techVisibility={techVisibility}
                />
              </Map>
            </div>

            {selectedJob ? (
              <div
                className="rounded-lg px-3 py-2 text-sm"
                style={{
                  background: colors.surface,
                  border: `1px solid ${colors.border}`,
                  color: colors.onSurface,
                }}
                data-testid="emv-selected-job-card"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    aria-hidden
                    style={{
                      width: 10, height: 10, borderRadius: 999,
                      background:
                        techColorById[selectedJob.technician_id] || "#0EA5E9",
                    }}
                  />
                  <strong data-testid="emv-selected-job-title">
                    {selectedJob.title || selectedJob.customer_name || "(no title)"}
                  </strong>
                  <span
                    className="text-xs"
                    style={{ color: colors.muted }}
                    data-testid="emv-selected-job-date"
                  >
                    {selectedJob.scheduled_date}
                    {typeof selectedJob.route_index === "number"
                      ? ` · Stop #${selectedJob.route_index + 1}`
                      : ""}
                  </span>
                  <button
                    type="button"
                    onClick={() => setSelectedJob(null)}
                    className="ml-auto text-xs underline"
                    data-testid="emv-selected-job-close"
                  >
                    Close
                  </button>
                </div>
                <div style={{ color: colors.muted }}
                       data-testid="emv-selected-job-address">
                  {selectedJob.address || "(no address on file)"}
                </div>
                {selectedJob.service_type ? (
                  <div className="text-xs mt-1"
                         style={{ color: colors.muted }}>
                    {selectedJob.service_type}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
