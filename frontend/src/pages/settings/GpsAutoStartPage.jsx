/**
 * Feb-2026 · P37b — GPS auto-start settings page.
 *
 * Backend contract (see ``routers/gps_auto_start.py``):
 *   GET  /api/settings/gps-auto-start   → { gps_auto_start_enabled, arrival_radius_meters }
 *   PATCH /api/settings/gps-auto-start  → same shape
 *
 * RBAC is enforced at the ``App.js`` route wrapper — this component
 * assumes the user is admin / manager / super_admin.
 */
import React, { useCallback, useEffect, useState } from "react";
import { api } from "@/api";


export default function GpsAutoStartPage() {
  const [cfg, setCfg] = useState({
    gps_auto_start_enabled: false,
    arrival_radius_meters: 75,
  });
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setErr(""); setOk("");
    try {
      const res = await api.get("/settings/gps-auto-start");
      setCfg({
        gps_auto_start_enabled: !!res?.gps_auto_start_enabled,
        arrival_radius_meters: Number(res?.arrival_radius_meters ?? 75),
      });
    } catch (e) {
      setErr(e?.message || "Failed to load GPS auto-start settings.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = useCallback(async () => {
    setErr(""); setOk(""); setBusy(true);
    try {
      const body = {
        gps_auto_start_enabled: !!cfg.gps_auto_start_enabled,
        arrival_radius_meters: Number(cfg.arrival_radius_meters),
      };
      const res = await api.patch("/settings/gps-auto-start", body);
      setCfg({
        gps_auto_start_enabled: !!res?.gps_auto_start_enabled,
        arrival_radius_meters: Number(res?.arrival_radius_meters ?? 75),
      });
      setOk("Saved.");
    } catch (e) {
      const detail = e?.body?.detail?.message || e?.body?.detail
                        || e?.message || "Save failed.";
      setErr(typeof detail === "string" ? detail : "Save failed.");
    } finally {
      setBusy(false);
    }
  }, [cfg]);

  if (loading) {
    return (
      <div className="max-w-2xl mx-auto p-6"
            data-testid="gps-auto-start-page-loading">
        Loading…
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto p-6" data-testid="gps-auto-start-page">
      <h1 className="text-2xl font-bold mb-1" style={{ color: "#0F172A" }}>
        GPS Auto-Start
      </h1>
      <p className="text-sm mb-6" style={{ color: "#64748B" }}
          data-testid="gps-auto-start-helper">
        When enabled, techs whose phone enters the arrival radius of an
        assigned job site will have their job timer auto-started. Techs
        must grant location consent in the mobile app. Timer auto-stops
        when the tech submits the service report or the job is marked
        completed.
      </p>

      {/* Enabled toggle */}
      <label className="flex items-center gap-3 mb-4 cursor-pointer">
        <input
          type="checkbox"
          checked={cfg.gps_auto_start_enabled}
          onChange={(e) => setCfg((c) => ({
            ...c, gps_auto_start_enabled: e.target.checked,
          }))}
          data-testid="gps-auto-start-enabled-toggle"
        />
        <span className="text-sm font-semibold" style={{ color: "#0F172A" }}>
          Enable GPS auto-start
        </span>
      </label>

      {/* Radius input */}
      <label className="block mb-4"
              style={{ opacity: cfg.gps_auto_start_enabled ? 1 : 0.6 }}
              data-testid="gps-auto-start-radius-wrap">
        <span className="text-xs uppercase font-semibold block mb-1"
                style={{ color: "#64748B" }}>
          Arrival radius (meters)
        </span>
        <input
          type="number"
          min={10}
          max={5000}
          value={cfg.arrival_radius_meters}
          onChange={(e) => setCfg((c) => ({
            ...c, arrival_radius_meters: e.target.value,
          }))}
          data-testid="gps-auto-start-radius-input"
          className="w-full text-sm px-3 py-2 rounded border"
          style={{ borderColor: "#E5E7EB" }}
        />
        <span className="text-xs mt-1 block" style={{ color: "#94A3B8" }}>
          10–5000 meters. Default 75m (~250ft).
        </span>
      </label>

      {err ? (
        <div className="text-sm mb-3 p-2 rounded"
              style={{ background: "rgba(220,38,38,0.06)", color: "#7F1D1D" }}
              data-testid="gps-auto-start-error">
          {err}
        </div>
      ) : null}
      {ok ? (
        <div className="text-sm mb-3 p-2 rounded"
              style={{ background: "rgba(16,185,129,0.06)", color: "#065F46" }}
              data-testid="gps-auto-start-ok">
          {ok}
        </div>
      ) : null}

      <button
        type="button"
        onClick={save}
        disabled={busy}
        data-testid="gps-auto-start-save"
        className="px-4 py-2 text-sm font-semibold rounded"
        style={{ background: "#0EA5E9", color: "#fff",
                   opacity: busy ? 0.6 : 1 }}
      >
        {busy ? "Saving…" : "Save"}
      </button>
    </div>
  );
}
