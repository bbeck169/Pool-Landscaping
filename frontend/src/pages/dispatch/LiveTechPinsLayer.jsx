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
// Feb-2026 · Phase 4.core additions:
//   • ``staleThresholdMs`` (default 15 min · 900 000 ms) — pins
//     older than this fade to 35% + get a "Last seen HH:MM ago"
//     hint in the InfoWindow. The stale threshold is deliberately
//     LARGER than the backend's 300 s freshness window because the
//     backend already drops pings > 5 min, so anything we see is
//     fresh; the 15-min guard is a UI-level warning for cases
//     where the backend window is bumped or a network hiccup
//     temporarily fed us cached data.
//   • ``isolatedTechId`` — when set, every OTHER tech renders at
//     35% opacity so admins can trace a single tech's route on a
//     crowded board.
import React from "react";
import { AdvancedMarker, InfoWindow } from "../../lib/maps";
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

function TechDot({ position, active, dimmed, stale, onClick }) {
  const color = tintFor(position.staleness_s);
  const label = firstName(position.user_name);
  const opacity = dimmed ? 0.35 : (stale ? 0.5 : 1);
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Technician ${position.user_name}`}
      data-testid={`dispatch-live-tech-${position.user_id}`}
      data-stale={stale ? "true" : "false"}
      data-dimmed={dimmed ? "true" : "false"}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        transform: "translateY(-4px)",
        opacity,
        filter: stale ? "grayscale(60%)" : "none",
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

const STALE_MS_DEFAULT = 15 * 60 * 1000;

function _fmtAgo(ms) {
  if (!Number.isFinite(ms) || ms < 0) return "just now";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m ago`;
}

export default function LiveTechPinsLayer({
  positions = [],
  isolatedTechId = null,
  staleThresholdMs = STALE_MS_DEFAULT,
}) {
  const [activeId, setActiveId] = React.useState(null);
  const active = React.useMemo(
    () => positions.find((p) => p.user_id === activeId) || null,
    [positions, activeId],
  );

  if (!positions || positions.length === 0) return null;

  return (
    <>
      {positions.map((p) => {
        const stalenessMs = (p.staleness_s || 0) * 1000;
        const stale = stalenessMs >= staleThresholdMs;
        const dimmed = isolatedTechId && p.user_id !== isolatedTechId;
        return (
          <AdvancedMarker
            key={`live-tech-${p.user_id}`}
            position={{ lat: p.lat, lng: p.lon }}
            onClick={() => setActiveId(p.user_id)}
          >
            <TechDot
              position={p}
              active={activeId === p.user_id}
              dimmed={dimmed}
              stale={stale}
              onClick={(e) => {
                e.stopPropagation();
                setActiveId(p.user_id);
              }}
            />
          </AdvancedMarker>
        );
      })}
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
            <div style={{ fontSize: 12, color: colors.muted, marginTop: 2 }}
                 data-testid={`dispatch-live-tech-lastseen-${active.user_id}`}>
              Last seen {_fmtAgo((active.staleness_s || 0) * 1000)}
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
