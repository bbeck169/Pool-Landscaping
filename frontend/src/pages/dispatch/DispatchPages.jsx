/**
 * Phase 26 Wave A · Dispatch admin pages (auto-dispatcher + weather).
 * Exports: DispatchBoard (default), WeatherReschedule.
 */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, Zap, Cloud, Settings as SettingsIcon, Users, Play,
  RefreshCw, ArrowRight, CheckCircle2, XCircle, CloudRain,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Gate } from "@/hooks/usePermissions";

/* ═════════ DISPATCH BOARD ═════════════════════════════════════════════ */
export default function DispatchBoard() {
  const nav = useNavigate();
  const [jobs, setJobs] = useState([]);
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busyJob, setBusyJob] = useState(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setMsg("");
    try {
      const today = new Date().toISOString().slice(0, 10);
      const [jRes, sRes] = await Promise.all([
        api.get("/jobs?limit=500"),
        api.get("/dispatch/settings"),
      ]);
      const arr = Array.isArray(jRes) ? jRes
                    : (jRes.items || jRes.data || []);
      setJobs(arr.filter((j) =>
        !j.technician_id && !j.assigned_to
        && (j.scheduled_date || "").slice(0, 10) >= today));
      setSettings(sRes);
    } catch (e) { setMsg(e.message || "Failed"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const assignOne = async (jobId) => {
    setBusyJob(jobId); setMsg("");
    try {
      const r = await api.post("/dispatch/auto-assign",
                                 { job_id: jobId });
      setMsg(`Assigned to ${r.tech_name} (cost ${Math.round(r.insertion_cost_meters)}m)`);
      await load();
    } catch (e) { setMsg(e.message || "Failed"); }
    finally { setBusyJob(null); }
  };
  const assignAll = async () => {
    setBulkBusy(true); setMsg("");
    let ok = 0, fail = 0;
    for (const j of jobs) {
      try { await api.post("/dispatch/auto-assign", { job_id: j.id }); ok++; }
      catch { fail++; }
    }
    setMsg(`Bulk done: ${ok} assigned · ${fail} failed`);
    setBulkBusy(false);
    await load();
  };
  const toggleAuto = async () => {
    const nxt = !settings.auto_assign_on_create;
    const r = await api.put("/dispatch/settings",
                              { auto_assign_on_create: nxt });
    setSettings(r);
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="dispatch-board">
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <button onClick={() => nav("/")} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="dispatch-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-[200px]">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Zap size={22} style={{ color: colors.brand }} />
            Route auto-dispatcher
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Auto-assigns new jobs to the tech with the lowest route
            insertion cost.
          </p>
        </div>
        <button onClick={() => nav("/admin/dispatch/weather")}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="dispatch-weather-link">
          <Cloud size={14} /> Weather
        </button>
        <button onClick={load}
                className="p-2 rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="dispatch-refresh">
          <RefreshCw size={14} />
        </button>
      </div>

      {settings ? (
        <div className="rounded-2xl p-4 mb-4 flex items-center gap-3 flex-wrap"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
             data-testid="dispatch-settings-bar">
          <SettingsIcon size={16} style={{ color: colors.brand }} />
          <span className="text-sm font-bold"
                style={{ color: colors.onSurface }}>
            Auto-assign new jobs on create
          </span>
          <button onClick={toggleAuto}
                  className="px-3 py-1 text-xs font-bold rounded-full"
                  style={{ backgroundColor:
                             settings.auto_assign_on_create
                               ? "#05966915" : "#6B728015",
                           color: settings.auto_assign_on_create
                                   ? "#059669" : "#6B7280" }}
                  data-testid="dispatch-autoassign-toggle">
            {settings.auto_assign_on_create ? "ON" : "OFF"}
          </button>
          <span className="text-xs ml-auto"
                style={{ color: colors.muted }}>
            Weather mode: <b>{settings.weather_reschedule_mode}</b>
            {" · "} Rain {settings.rain_threshold_pct}%
            {" · "} Wind {settings.wind_threshold_mph} mph
          </span>
        </div>
      ) : null}

      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-lg font-bold flex items-center gap-2"
            style={{ color: colors.onSurface }}>
          <Users size={16} /> Unassigned jobs · {jobs.length}
        </h2>
        <Gate perm="Jobs" action="write">
          <button onClick={assignAll}
                disabled={bulkBusy || jobs.length === 0}
                className="ml-auto px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.brand, color: "#fff",
                         opacity: (bulkBusy || jobs.length === 0) ? 0.5 : 1 }}
                data-testid="dispatch-assignall-btn">
            <Play size={12} /> {bulkBusy ? "Assigning…" : "Auto-assign all"}
          </button>
        </Gate>
      </div>

      {msg ? (
        <div className="rounded-xl p-3 mb-3 text-sm"
             style={{ backgroundColor: "#F0FDF4", color: "#166534",
                      border: "1px solid #86EFAC" }}
             data-testid="dispatch-msg">
          {msg}
        </div>
      ) : null}

      {loading ? (
        <div className="p-8 text-center text-sm"
             style={{ color: colors.muted }}>Loading…</div>
      ) : jobs.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          <CheckCircle2 size={36} style={{ color: "#059669",
                                              margin: "0 auto 8px" }} />
          <div className="font-bold" style={{ color: colors.onSurface }}>
            All jobs assigned.
          </div>
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "#F1F5F9" }}>
              <tr>
                <th className="p-2 text-left">Date</th>
                <th className="p-2 text-left">Customer</th>
                <th className="p-2 text-left">Type</th>
                <th className="p-2 text-left">Address</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}
                    style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`dispatch-job-row-${j.id}`}>
                  <td className="p-2 text-xs font-mono"
                      style={{ color: colors.muted }}>
                    {(j.scheduled_date || "").slice(0, 10)}
                  </td>
                  <td className="p-2 font-bold"
                      style={{ color: colors.onSurface }}>
                    {j.customer_name}
                  </td>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    {j.service_type || j.job_type || "—"}
                  </td>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    {j.address}
                  </td>
                  <td className="p-2 text-right">
                    <button onClick={() => assignOne(j.id)}
                            disabled={busyJob === j.id}
                            className="px-3 py-1 text-xs font-bold rounded-lg flex items-center gap-1 ml-auto"
                            style={{ backgroundColor: colors.brand,
                                     color: "#fff",
                                     opacity: busyJob === j.id ? 0.6 : 1 }}
                            data-testid={`dispatch-assign-${j.id}`}>
                      <Zap size={10} />
                      {busyJob === j.id ? "…" : "Auto-assign"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ═════════ WEATHER RESCHEDULE ═════════════════════════════════════════ */
export function WeatherReschedule() {
  const nav = useNavigate();
  const [events, setEvents] = useState([]);
  const [settings, setSettings] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    const [e, s] = await Promise.all([
      api.get("/dispatch/weather-events"),
      api.get("/dispatch/settings"),
    ]);
    setEvents(e.items || []);
    setSettings(s);
  }, []);
  useEffect(() => { load(); }, [load]);

  const scan = async () => {
    setScanning(true); setMsg("");
    try {
      const r = await api.post("/dispatch/weather-scan", {});
      setMsg(`Scanned ${r.scanned} outdoor jobs · ${r.affected} affected in ${r.mode} mode`);
      await load();
    } catch (e) { setMsg(e.message); }
    finally { setScanning(false); }
  };
  const decide = async (id, action, override) => {
    await api.post(`/dispatch/weather-events/${id}/${action}`,
                     override ? { override_date: override } : {});
    await load();
  };
  const setMode = async (mode) => {
    const r = await api.put("/dispatch/settings",
                              { weather_reschedule_mode: mode });
    setSettings(r);
  };
  const setThreshold = async (field, value) => {
    const r = await api.put("/dispatch/settings", { [field]: Number(value) });
    setSettings(r);
  };

  const statusPill = (s) => {
    const c = { proposed: ["#F59E0B", "Proposed"],
                 accepted: ["#059669", "Accepted"],
                 rejected: ["#6B7280", "Rejected"],
                 auto_applied: ["#0EA5E9", "Auto-applied"] }[s]
                || ["#6B7280", s];
    return (
      <span className="inline-block px-2 py-0.5 rounded-full text-[10px] font-bold"
            style={{ backgroundColor: `${c[0]}15`, color: c[0] }}
            data-testid={`weather-status-${s}`}>
        {c[1]}
      </span>
    );
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6"
         data-testid="weather-reschedule">
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <button onClick={() => nav("/admin/dispatch")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}
                data-testid="weather-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-[200px]">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <CloudRain size={22} style={{ color: colors.brand }} />
            Weather-triggered reschedule
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Scans outdoor jobs and moves (or proposes to move) them out of
            rain and high wind windows.
          </p>
        </div>
        <Gate perm="Jobs" action="write">
          <button onClick={scan} disabled={scanning}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="weather-scan-btn">
            <RefreshCw size={14} /> {scanning ? "Scanning…" : "Run scan"}
          </button>
        </Gate>
      </div>

      {settings ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
          <div className="rounded-2xl p-4"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}>
            <div className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>Mode</div>
            <div className="mt-2 flex gap-2">
              {["manual", "auto"].map((m) => (
                <button key={m} onClick={() => setMode(m)}
                        className="px-3 py-1 text-xs font-bold rounded-full"
                        style={{ backgroundColor:
                                   settings.weather_reschedule_mode === m
                                     ? colors.brand : colors.background,
                                 color:
                                   settings.weather_reschedule_mode === m
                                     ? "#fff" : colors.onSurface,
                                 border: `1px solid ${colors.border}` }}
                        data-testid={`weather-mode-${m}`}>
                  {m}
                </button>
              ))}
            </div>
          </div>
          <label className="rounded-2xl p-4 block"
                 style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
            <div className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>Rain threshold %</div>
            <input type="number" min={0} max={100}
                   defaultValue={settings.rain_threshold_pct}
                   onBlur={(e) => setThreshold("rain_threshold_pct",
                                                 e.target.value)}
                   className="mt-2 w-full p-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid="weather-rain-input" />
          </label>
          <label className="rounded-2xl p-4 block"
                 style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
            <div className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>Wind threshold mph</div>
            <input type="number" min={0} max={80}
                   defaultValue={settings.wind_threshold_mph}
                   onBlur={(e) => setThreshold("wind_threshold_mph",
                                                 e.target.value)}
                   className="mt-2 w-full p-2 rounded-lg text-sm"
                   style={{ backgroundColor: colors.background,
                            border: `1px solid ${colors.border}` }}
                   data-testid="weather-wind-input" />
          </label>
        </div>
      ) : null}

      {msg ? (
        <div className="rounded-xl p-3 mb-3 text-sm"
             style={{ backgroundColor: "#F0FDF4", color: "#166534",
                      border: "1px solid #86EFAC" }}
             data-testid="weather-msg">
          {msg}
        </div>
      ) : null}

      {events.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          No weather events yet. Click <b>Run scan</b> to check for rain
          conflicts.
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "#F1F5F9" }}>
              <tr>
                <th className="p-2 text-left">When</th>
                <th className="p-2 text-left">Job</th>
                <th className="p-2 text-left">Original</th>
                <th className="p-2 text-left"></th>
                <th className="p-2 text-left">Proposed</th>
                <th className="p-2 text-right">Rain %</th>
                <th className="p-2 text-right">Wind mph</th>
                <th className="p-2 text-left">Status</th>
                <th className="p-2 text-right"></th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}
                    style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`weather-event-row-${e.id}`}>
                  <td className="p-2 text-xs" style={{ color: colors.muted }}>
                    {(e.ts || "").slice(0, 16).replace("T", " ")}
                  </td>
                  <td className="p-2 font-mono text-xs"
                      style={{ color: colors.onSurface }}>
                    {(e.job_id || "").slice(0, 8)}
                  </td>
                  <td className="p-2 text-xs"
                      style={{ color: colors.onSurface }}>
                    {e.original_date}
                  </td>
                  <td className="p-2">
                    <ArrowRight size={12} style={{ color: colors.muted }} />
                  </td>
                  <td className="p-2 text-xs font-bold"
                      style={{ color: colors.brand }}>
                    {e.actual_date || e.proposed_date}
                  </td>
                  <td className="p-2 text-right text-xs"
                      style={{ color: colors.muted }}>
                    {e.rain_prob_pct}%
                  </td>
                  <td className="p-2 text-right text-xs"
                      style={{ color: colors.muted }}>
                    {e.wind_mph}
                  </td>
                  <td className="p-2">{statusPill(e.status)}</td>
                  <td className="p-2 flex gap-1 justify-end">
                    {e.status === "proposed" ? (
                      <>
                        <button onClick={() => decide(e.id, "accept")}
                                className="p-1 rounded"
                                style={{ backgroundColor: "#05966915",
                                         color: "#059669" }}
                                data-testid={`weather-accept-${e.id}`}>
                          <CheckCircle2 size={12} />
                        </button>
                        <button onClick={() => decide(e.id, "reject")}
                                className="p-1 rounded"
                                style={{ backgroundColor: "#DC262615",
                                         color: "#DC2626" }}
                                data-testid={`weather-reject-${e.id}`}>
                          <XCircle size={12} />
                        </button>
                      </>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
