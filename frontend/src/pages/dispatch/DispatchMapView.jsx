// Phase 17 · Feb-2026 — Google Maps view for the Dispatch Board.
//
// Wraps @vis.gl/react-google-maps <Map>, renders AdvancedMarker
// pins with color-by-mode (tech / crew / service-day), a clustered
// marker group for large sets, and an overlaid polyline when the
// caller passes an encoded ``polyline`` string. Also renders a
// distinct gray hollow layer for unrouted customers.
//
// Cooperative gesture handling is REQUIRED per Phase 17 rules —
// the map only pans when the user Ctrl/⌘-scrolls, otherwise the
// page scrolls naturally. See /app/memory/PRD.md § Phase 17.
import React from "react";
import { Map, AdvancedMarker, InfoWindow, useMap } from "../../lib/maps";
import { MarkerClusterer } from "@googlemaps/markerclusterer";
import { colors } from "@/theme";
import { colorForPin } from "@/pages/dispatch/dispatchColors";
import LiveTechPinsLayer from "@/pages/dispatch/LiveTechPinsLayer";
import DispatchColorLegend from "@/pages/dispatch/DispatchColorLegend";
import formatAddress from "@/utils/formatAddress";

const AZ_CENTER = { lat: 33.6975, lng: -112.3708 }; // Vistancia/Peoria default

function decodePolyline(encoded) {
  if (!encoded) return [];
  const points = [];
  let index = 0, lat = 0, lng = 0;
  while (index < encoded.length) {
    let b, shift = 0, result = 0;
    do { b = encoded.charCodeAt(index++) - 63; result |= (b & 0x1f) << shift; shift += 5; }
    while (b >= 0x20);
    const dlat = (result & 1) ? ~(result >> 1) : (result >> 1);
    lat += dlat;
    shift = 0; result = 0;
    do { b = encoded.charCodeAt(index++) - 63; result |= (b & 0x1f) << shift; shift += 5; }
    while (b >= 0x20);
    const dlng = (result & 1) ? ~(result >> 1) : (result >> 1);
    lng += dlng;
    points.push({ lat: lat / 1e5, lng: lng / 1e5 });
  }
  return points;
}

function PinDot({ scheduled, colorHex, onClick, testId }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testId}
      aria-label="Customer pin"
      style={{
        width: 22, height: 22, borderRadius: 999,
        background: colorHex || "#0EA5E9",
        border: scheduled ? "3px solid #FDE68A" : "2px solid #ffffff",
        boxShadow: "0 1px 3px rgba(0,0,0,0.35)",
        cursor: "pointer",
      }}
    />
  );
}

function PolylineOverlay({ encoded }) {
  const map = useMap();
  React.useEffect(() => {
    if (!map || !encoded) return undefined;
    if (typeof window === "undefined" || !window.google?.maps?.Polyline) return undefined;
    const path = decodePolyline(encoded);
    const line = new window.google.maps.Polyline({
      path, strokeColor: "#0EA5E9",
      strokeOpacity: 0.85, strokeWeight: 4,
      map,
    });
    return () => line.setMap(null);
  }, [map, encoded]);
  return null;
}

function PinsLayer({ pins, techColorById, onSelect, pinColorMode = "tech", isolatedTechId = null }) {
  const map = useMap();
  const clustererRef = React.useRef(null);
  const markersRef = React.useRef([]);

  // Feb-2026 · Phase 4.core — helper: is this pin dimmed under
  // the current isolate? Only "tech" mode drives isolate.
  const _isDimmed = React.useCallback((p) => {
    if (!isolatedTechId) return false;
    if (pinColorMode !== "tech") return false;
    return !(p.assigned_tech_ids || []).includes(isolatedTechId);
  }, [isolatedTechId, pinColorMode]);

  React.useEffect(() => {
    if (!map || typeof window === "undefined" || !window.google?.maps) return undefined;
    markersRef.current.forEach((m) => (m.map = null));
    markersRef.current = [];
    if (clustererRef.current) {
      clustererRef.current.clearMarkers();
      clustererRef.current = null;
    }
    if (!pins || pins.length === 0) return undefined;
    if (pins.length <= 30) return undefined;

    const gm = window.google.maps;
    if (!gm.marker?.AdvancedMarkerElement) return undefined;
    const newMarkers = pins.map((p) => {
      const dot = document.createElement("div");
      dot.style.width = "22px";
      dot.style.height = "22px";
      dot.style.borderRadius = "999px";
      dot.style.background = colorForPin(p, pinColorMode, techColorById);
      dot.style.border = p.is_scheduled_this_day ? "3px solid #FDE68A" : "2px solid #ffffff";
      dot.style.boxShadow = "0 1px 3px rgba(0,0,0,0.35)";
      dot.style.cursor = "pointer";
      dot.style.opacity = _isDimmed(p) ? "0.3" : "1";
      const marker = new gm.marker.AdvancedMarkerElement({
        position: { lat: p.lat, lng: p.lng },
        content: dot,
      });
      marker.addListener("gmp-click", () => onSelect(p.customer_id));
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
  }, [map, pins, techColorById, onSelect, pinColorMode, _isDimmed]);

  if (!pins || pins.length === 0) return null;
  if (pins.length > 30) return null;
  return pins.map((p) => {
    const dimmed = _isDimmed(p);
    return (
      <AdvancedMarker
        key={p.customer_id}
        position={{ lat: p.lat, lng: p.lng }}
        onClick={() => onSelect(p.customer_id)}
      >
        <div style={{ opacity: dimmed ? 0.3 : 1 }} data-dimmed={dimmed ? "true" : "false"}>
          <PinDot
            scheduled={p.is_scheduled_this_day}
            colorHex={colorForPin(p, pinColorMode, techColorById)}
            onClick={(e) => { e.stopPropagation(); onSelect(p.customer_id); }}
            testId={`dispatch-pin-${p.customer_id}`}
          />
        </div>
      </AdvancedMarker>
    );
  });
}

/** Unrouted customers — gray hollow pins, always styled the same
 *  regardless of pin-color mode so admins can spot them. */
function UnroutedPinsLayer({ pins, onSelect }) {
  if (!pins || pins.length === 0) return null;
  return pins.slice(0, 200).map((p) => (
    <AdvancedMarker
      key={`unrouted-${p.customer_id}`}
      position={{ lat: p.lat, lng: p.lng }}
      onClick={() => onSelect(p.customer_id)}
    >
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onSelect(p.customer_id); }}
        aria-label="Unrouted customer"
        data-testid={`dispatch-unrouted-pin-${p.customer_id}`}
        style={{
          width: 18, height: 18, borderRadius: 999,
          background: "transparent",
          border: "2px solid #94A3B8",
          opacity: 0.65,
          boxShadow: "0 0 0 1px #F1F5F9",
          cursor: "pointer",
        }}
      />
    </AdvancedMarker>
  ));
}

// Feb-2026 · Phase 4 · Q4 — Map focus helper. Pans+zooms the map
// to the coords of the focused stop and briefly flashes it. Runs
// against the underlying google.maps.Map returned by ``useMap()``
// so we don't need to hoist a ref up to the parent.
function FocusOnStop({ pins, focusedStopId }) {
  const map = useMap();
  React.useEffect(() => {
    if (!map || !focusedStopId) return;
    const stop = pins.find((p) => p.customer_id === focusedStopId);
    if (!stop || typeof stop.lat !== "number" || typeof stop.lng !== "number") return;
    try {
      map.panTo({ lat: stop.lat, lng: stop.lng });
      // Preserve the current zoom if it's already zoomed in; only
      // zoom-in if we're currently zoomed out.
      const z = map.getZoom?.();
      if (z !== undefined && z < 14) map.setZoom(14);
    } catch { /* SSR / stub map — ignore */ }
  }, [map, focusedStopId, pins]);
  return null;
}

export default function DispatchMapView({
  pins = [],
  unroutedPins = [],
  polyline = null,
  techColorById = {},
  techNameById = {},
  activeCustomerId = null,
  onSelectCustomer = () => {},
  mapId,
  pinColorMode = "tech",
  liveTechPositions = [],
  // ── Feb-2026 · Phase 4.core additions ─────────────────────────
  isolatedTechId = null,
  onIsolateTech = () => {},
  focusedStopId = null,
  staleThresholdMs,
}) {
  const active = React.useMemo(
    () => pins.find((p) => p.customer_id === activeCustomerId) || null,
    [pins, activeCustomerId],
  );

  const initialCenter = React.useMemo(() => {
    if (pins.length > 0) return { lat: pins[0].lat, lng: pins[0].lng };
    if (unroutedPins.length > 0) return { lat: unroutedPins[0].lat, lng: unroutedPins[0].lng };
    return AZ_CENTER;
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      className="rounded-xl overflow-hidden relative"
      style={{
        border: `1px solid ${colors.border}`,
        height: "min(72vh, 720px)",
        minHeight: 460,
      }}
      data-testid="dispatch-map-container"
    >
      {/* Feb-2026 · Phase 4 batched — Team color legend pill.
          Sticky top-right overlay. Reuses the same isolate state
          as the Tech Load strip; clicking a tech dims all other
          pins on the map. */}
      <div
        className="absolute z-10"
        style={{ top: 8, right: 8, pointerEvents: "auto" }}
      >
        <DispatchColorLegend
          pins={pins}
          pinColorMode={pinColorMode}
          techColorById={techColorById}
          techNameById={techNameById}
          isolatedKey={isolatedTechId}
          onIsolate={onIsolateTech}
        />
      </div>
      <Map
        mapId={mapId || "DEMO_MAP_ID"}
        defaultCenter={initialCenter}
        defaultZoom={11}
        gestureHandling="cooperative"
        disableDefaultUI={false}
        clickableIcons={false}
        style={{ width: "100%", height: "100%" }}
      >
        <PinsLayer
          pins={pins}
          techColorById={techColorById}
          onSelect={onSelectCustomer}
          pinColorMode={pinColorMode}
          isolatedTechId={isolatedTechId}
        />
        <UnroutedPinsLayer
          pins={unroutedPins}
          onSelect={onSelectCustomer}
        />
        {/* Phase P2 · Feb-2026 — live technician GPS markers. */}
        <LiveTechPinsLayer
          positions={liveTechPositions}
          isolatedTechId={isolatedTechId}
          staleThresholdMs={staleThresholdMs}
        />
        <FocusOnStop pins={pins} focusedStopId={focusedStopId} />
        {polyline ? <PolylineOverlay encoded={polyline} /> : null}
        {active ? (
          <InfoWindow
            position={{ lat: active.lat, lng: active.lng }}
            onCloseClick={() => onSelectCustomer(null)}
          >
            <div style={{ minWidth: 220 }} data-testid="dispatch-map-infowindow">
              <div style={{ fontWeight: 600, fontSize: 13 }}>{active.name}</div>
              <div style={{ fontSize: 12, color: colors.muted, marginTop: 2 }}>
                {formatAddress(active.address)}
              </div>
              {active.service_days?.length ? (
                <div style={{ fontSize: 11, marginTop: 6, color: colors.onSurfaceSecondary }}>
                  Service days:{" "}
                  <strong style={{ textTransform: "capitalize" }}>
                    {active.service_days.join(", ")}
                  </strong>
                </div>
              ) : null}
              {active.override_source_tech_id ? (
                <div
                  className="mt-1 text-[11px] px-1.5 py-0.5 inline-block rounded-full"
                  style={{
                    backgroundColor: "#EFF6FF", color: "#1E3A8A",
                    border: "1px solid #BFDBFE",
                  }}
                  data-testid="dispatch-map-override-badge"
                >
                  Shifted from {active.override_source_tech_id.slice(0, 6)}… (until Sat)
                </div>
              ) : null}
            </div>
          </InfoWindow>
        ) : null}
      </Map>
    </div>
  );
}
