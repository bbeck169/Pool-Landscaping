// Phase P2 · Feb-2026 — Live technician markers on the Dispatch Board map.
//
// Renders one AdvancedMarker per live position: colored dot + first-name
// label. Clicking opens an InfoWindow with the full name, staleness in
// seconds, and reported accuracy in meters.
//
// Marker color-by-staleness:
//   • green  (fresh)      staleness_s < 120
//   • yellow (getting old) staleness_s < 300
//   • gray   (stale)       staleness_s >= 300  — defensive; backend
//     currently filters anything older than 300 s, but if the window
//     changes we still render sanely.
//
// The backend guarantees positions are already tenant-scoped and 5-min
// fresh — we do NOT re-filter here.
import React from "react";
import { AdvancedMarker, InfoWindow } from "@/lib/maps";
import { colors } from "@/theme";

function tintFor(staleness) {
  if (staleness < 120) return "#10B981"; // emerald-500
  if (staleness < 300) return "#F59E0B"; // amber-500
  return "#94A3B8";                       // slate-400 (stale fallback)
}

function firstName(full) {
  if (!full) return "";
  const s = String(full).trim();
  return s.split(/\s+/)[0] || "";
}

function TechDot({ position, active, onClick }) {
  const color = tintFor(position.staleness_s);
  const label = firstName(position.user_name);
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Technician ${position.user_name}`}
      data-testid={`dispatch-live-tech-${position.user_id}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        transform: "translateY(-4px)",
      }}
    >
      <span
        style={{
          width: 18,
          height: 18,
          borderRadius: 999,
          background: color,
          border: active ? "3px solid #ffffff" : "2px solid #ffffff",
          boxShadow: "0 2px 6px rgba(0,0,0,0.35)",
        }}
      />
      {label ? (
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: colors.onSurface,
            background: "rgba(255,255,255,0.92)",
            padding: "2px 6px",
            borderRadius: 6,
            border: `1px solid ${colors.border}`,
            boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
            whiteSpace: "nowrap",
          }}
        >
          {label}
        </span>
      ) : null}
    </button>
  );
}

export default function LiveTechPinsLayer({ positions = [] }) {
  const [activeId, setActiveId] = React.useState(null);
  const active = React.useMemo(
    () => positions.find((p) => p.user_id === activeId) || null,
    [positions, activeId],
  );

  if (!positions || positions.length === 0) return null;

  return (
    <>
      {positions.map((p) => (
        <AdvancedMarker
          key={`live-tech-${p.user_id}`}
          position={{ lat: p.lat, lng: p.lon }}
          onClick={() => setActiveId(p.user_id)}
        >
          <TechDot
            position={p}
            active={activeId === p.user_id}
            onClick={(e) => {
              e.stopPropagation();
              setActiveId(p.user_id);
            }}
          />
        </AdvancedMarker>
      ))}
      {active ? (
        <InfoWindow
          position={{ lat: active.lat, lng: active.lon }}
          onCloseClick={() => setActiveId(null)}
        >
          <div
            style={{ minWidth: 200 }}
            data-testid={`dispatch-live-tech-info-${active.user_id}`}
          >
            <div style={{ fontWeight: 600, fontSize: 13 }}>
              {active.user_name || "Technician"}
            </div>
            <div style={{ fontSize: 12, color: colors.muted, marginTop: 2 }}>
              Captured {Math.max(0, active.staleness_s)} seconds ago
            </div>
            {typeof active.accuracy_m === "number" ? (
              <div style={{ fontSize: 11, color: colors.muted, marginTop: 2 }}>
                Accuracy: ±{Math.round(active.accuracy_m)} m
              </div>
            ) : null}
            {/* G3 · Feb-2026 — address enrichment, cache-first. */}
            <div style={{ fontSize: 11, marginTop: 6, color: colors.onSurface }}
                 data-testid={`dispatch-live-tech-addr-${active.user_id}`}>
              {active.address?.formatted ? (
                <span>{active.address.formatted}</span>
              ) : active.address_status === "no_token" ? (
                <span style={{ color: "#92400E" }}
                      data-testid={`dispatch-live-tech-addr-notoken-${active.user_id}`}>
                  Address unavailable — set MAPBOX_ACCESS_TOKEN
                </span>
              ) : (
                <span style={{ color: colors.muted, fontStyle: "italic" }}
                      data-testid={`dispatch-live-tech-addr-fallback-${active.user_id}`}>
                  {active.lat?.toFixed(5)}, {active.lon?.toFixed(5)}
                </span>
              )}
            </div>
          </div>
        </InfoWindow>
      ) : null}
    </>
  );
}
