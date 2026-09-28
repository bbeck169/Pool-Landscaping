/**
 * FLEET-A · Feb-2026 — Admin fleet dispatch board.
 *
 * Route: /admin/fleet (AdminOnly).  Nav: Operations → Fleet Board.
 *
 * Layout:
 *   - Left: tech list with last-ping-age chip + ETA card.
 *   - Right: <MapView/> with tech dots + job destination pins.
 *
 * The board polls ``GET /api/fleet/board`` every 30s. There is no
 * websocket for FLEET-A; polling is sufficient for the initial
 * dispatch use case. Empty state routes admins to
 * ``/admin/settings/fleet-membership``.
 *
 * NB: route ``/admin/dispatch`` is already occupied by the
 * pre-existing DispatchBoard (from `pages/dispatch/DispatchPages`)
 * so this page lives at ``/admin/fleet`` instead. Called out in
 * the design-forks section of the FLEET-A commit report.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Users, MapPin, Battery, Clock, RefreshCw, AlertTriangle } from "lucide-react";

import MapView, { DOT_COLORS } from "@/components/MapView";
import { api } from "@/api";
import { colors } from "@/theme";

const POLL_INTERVAL_MS = 30_000;

function pingAgeColor(seconds) {
  if (seconds == null) return "gray";
  if (seconds <= 2 * 60) return "green";
  if (seconds <= 10 * 60) return "yellow";
  return "red";
}

function pingAgeLabel(seconds) {
  if (seconds == null) return "no pings yet";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 60 * 60) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

function initials(name) {
  if (!name) return "?";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((n) => n[0]?.toUpperCase() || "")
    .join("");
}

export default function DispatchBoard() {
  const [data, setData] = useState(null);
  const [loadedAt, setLoadedAt] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const intervalRef = useRef(null);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await api.get("/fleet/board");
      setData(res);
      setLoadedAt(new Date());
    } catch (e) {
      toast.error(`Fleet board load failed: ${e?.message || e}`);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
    intervalRef.current = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [load]);

  const techs = data?.techs || [];
  const isEmpty = data !== null && techs.length === 0;

  const mapLayers = useMemo(() => {
    const techPoints = techs
      .filter((t) => t.location?.lat != null && t.location?.lng != null)
      .map((t) => ({
        id: `tech-${t.tech_user_id}`,
        lat: t.location.lat,
        lng: t.location.lng,
        color: pingAgeColor(t.last_ping_age_s),
        pinLabel: initials(t.tech_name),
        label: t.tech_name,
        subtitle: t.current_job
          ? `→ ${t.current_job.customer_name || t.current_job.title || "next job"}`
          : "no active job",
      }));
    const jobPoints = techs
      .filter(
        (t) => t.current_job?.lat != null && t.current_job?.lng != null
      )
      .map((t) => ({
        id: `job-${t.current_job.id}`,
        lat: t.current_job.lat,
        lng: t.current_job.lng,
        color: "blue",
        label: t.current_job.customer_name || t.current_job.title || "Job",
        subtitle: t.current_job.address || "",
      }));
    return [
      { key: "techs", points: techPoints },
      { key: "jobs", points: jobPoints },
    ];
  }, [techs]);

  return (
    <div
      className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
      data-testid="admin-fleet-dispatch-board"
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1
            className="text-2xl md:text-3xl font-bold flex items-center gap-2"
            style={{ color: colors.onSurface }}
            data-testid="admin-fleet-dispatch-title"
          >
            <MapPin size={22} /> Fleet Dispatch Board
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Live locations, ETAs, and manual check-ins for every in-fleet
            technician. Polls every 30 seconds.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className="text-xs"
            style={{ color: colors.muted }}
            data-testid="admin-fleet-dispatch-last-refresh"
          >
            {loadedAt
              ? `refreshed ${loadedAt.toLocaleTimeString()}`
              : "loading…"}
          </span>
          <button
            type="button"
            data-testid="admin-fleet-dispatch-refresh"
            onClick={load}
            disabled={refreshing}
            className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1.5"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurfaceSecondary,
              border: `1px solid ${colors.border}`,
              opacity: refreshing ? 0.6 : 1,
            }}
          >
            <RefreshCw
              size={12}
              className={refreshing ? "animate-spin" : ""}
            />{" "}
            Refresh
          </button>
        </div>
      </div>

      {isEmpty ? (
        <div
          data-testid="admin-fleet-dispatch-empty"
          className="rounded-2xl p-8 text-center"
          style={{
            backgroundColor: colors.surface,
            border: `1px dashed ${colors.border}`,
            color: colors.muted,
          }}
        >
          <Users size={28} style={{ margin: "0 auto 8px", opacity: 0.6 }} />
          <div className="text-sm mb-3">
            No techs in the fleet.
          </div>
          <button
            type="button"
            onClick={() => navigate("/admin/settings/fleet-membership")}
            data-testid="admin-fleet-dispatch-membership-link"
            className="text-xs font-semibold px-3 py-2 rounded-lg inline-flex items-center gap-1"
            style={{
              background: colors.brand,
              color: "#fff",
            }}
          >
            Enable techs from Settings → Fleet Membership
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-12 gap-4">
          {/* Left — tech list */}
          <div className="col-span-12 md:col-span-4 space-y-3">
            {(techs || []).map((t) => (
              <TechCard key={t.tech_user_id} tech={t} />
            ))}
          </div>

          {/* Right — map */}
          <div className="col-span-12 md:col-span-8">
            <MapView
              center={
                (techs[0]?.location?.lat && techs[0]?.location?.lng)
                  ? [techs[0].location.lat, techs[0].location.lng]
                  : undefined
              }
              zoom={12}
              height={620}
              layers={mapLayers}
              testid="admin-fleet-dispatch-map"
            />
          </div>
        </div>
      )}
    </div>
  );
}

function TechCard({ tech }) {
  const age = tech.last_ping_age_s;
  const color = pingAgeColor(age);
  const dotColor = DOT_COLORS[color] || DOT_COLORS.gray;
  return (
    <div
      className="rounded-2xl p-3"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={`fleet-tech-card-${tech.tech_user_id}`}
    >
      <div className="flex items-center gap-3">
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold text-white"
          style={{ background: dotColor }}
          data-testid={`fleet-tech-avatar-${tech.tech_user_id}`}
        >
          {initials(tech.tech_name)}
        </div>
        <div className="flex-1 min-w-0">
          <div
            className="text-sm font-semibold truncate"
            style={{ color: colors.onSurface }}
          >
            {tech.tech_name}
          </div>
          <div
            className="text-xs flex items-center gap-2"
            style={{ color: colors.muted }}
          >
            <Clock size={11} /> {pingAgeLabel(age)}
            {tech.battery_pct != null ? (
              <>
                <span>·</span>
                <Battery size={11} /> {Math.round(tech.battery_pct)}%
              </>
            ) : null}
          </div>
        </div>
      </div>

      {tech.current_job ? (
        <div className="mt-2 pt-2" style={{ borderTop: `1px solid ${colors.divider}` }}>
          <div className="text-xs" style={{ color: colors.muted }}>
            Current job:
          </div>
          <Link
            to={`/jobs/${tech.current_job.id}`}
            className="text-sm font-semibold hover:underline"
            style={{ color: colors.brand }}
            data-testid={`fleet-tech-job-link-${tech.tech_user_id}`}
          >
            {tech.current_job.customer_name || tech.current_job.title || "Job"}
          </Link>
          <div className="text-xs" style={{ color: colors.muted }}>
            {tech.current_job.address || "no address on file"}
          </div>
        </div>
      ) : null}

      {tech.eta ? (
        <div
          className="mt-2 pt-2 flex items-center gap-2"
          style={{ borderTop: `1px solid ${colors.divider}` }}
          data-testid={`fleet-tech-eta-${tech.tech_user_id}`}
        >
          <span
            className="text-xs font-semibold"
            style={{ color: colors.onSurfaceSecondary }}
          >
            ETA: {Math.max(1, Math.round(tech.eta.duration_s / 60))} min
          </span>
          <span
            className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
            style={{
              background:
                tech.eta.provider === "google" ? "#DBEAFE"
                  : tech.eta.provider === "osrm" ? "#DCFCE7"
                  : "#FEF3C7",
              color:
                tech.eta.provider === "google" ? "#1E3A8A"
                  : tech.eta.provider === "osrm" ? "#166534"
                  : "#92400E",
            }}
            data-testid={`fleet-tech-eta-provider-${tech.tech_user_id}`}
          >
            {tech.eta.provider}
          </span>
        </div>
      ) : tech.current_job ? (
        <div
          className="mt-2 pt-2 text-xs flex items-center gap-2"
          style={{
            borderTop: `1px solid ${colors.divider}`,
            color: "#B45309",
          }}
          data-testid={`fleet-tech-eta-unavailable-${tech.tech_user_id}`}
        >
          <AlertTriangle size={12} />
          ETA unavailable — job or tech lacks coordinates.
        </div>
      ) : null}
    </div>
  );
}
