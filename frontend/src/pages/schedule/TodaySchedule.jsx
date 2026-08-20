/**
 * Phase 16C · Tech Today Schedule
 * Vertical hourly timeline for the logged-in user: jobs + shifts + breaks,
 * with driving-time chips between consecutive jobs (Google Distance Matrix).
 */
import React, { useEffect, useMemo, useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import { useJsApiLoader } from "@react-google-maps/api";
import { useAuth } from "@/auth";
import { BulkReorderModal } from "@/pages/schedule/NumberedReorder";
// Phase 16C `<WeatherWidget5Day>` removed from tech home 2026-07 per
// user request. File still exists at ``pages/aitools/`` — imported
// by the admin Dashboard.
import ServiceNotePill from "@/components/schedule/ServiceNotePill";
// Phase 27 · Feb-2026 — Global avatar swap for dense layouts.
// Compact tech avatar rendered next to the customer line so
// admins/dispatchers can spot the assigned tech at a glance
// without inflating the card height.
// Feb-2026 · Schedule polish — the per-card <TechAvatar> was
// removed from the today view; the component still ships for
// other surfaces (dispatch/portal). Import intentionally dropped
// so the file has no unused-symbol lint churn.
// Feb-2026 · Phase 1 — Tech "On my way" SMS button. Used both as
// the prominent top-level next-job CTA and as the compact inline
// affordance on each job card.
import OnMyWayButton from "@/components/schedule/OnMyWayButton";
import { MapPin, Navigation, Car, ChevronRight, ChevronLeft, RefreshCw, CalendarCheck, Square, CheckSquare, Key, StickyNote, Route as RouteIcon, RotateCcw, Star } from "lucide-react";

const GOOGLE_LIBS = ["places"];

function fmtTime(iso, tz) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: "numeric", minute: "2-digit", timeZone: tz,
    });
  } catch { return iso.slice(11, 16); }
}
function fmtDur(sec) {
  if (sec == null) return "—";
  const m = Math.round(sec / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
function fmtMi(m) {
  if (m == null) return "—";
  return `${(m / 1609.344).toFixed(1)} mi`;
}

export default function TodaySchedule() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isTech = user?.role === "technician";
  // Feb-2026 · numbered-order reorder — admin/manager can open the
  // bulk reorder modal directly from the today view.  Techs never
  // see it.
  const isAdminForReorder = ["admin", "manager", "super_admin"].includes(
    (user?.role || "").toLowerCase(),
  );
  const [reorderOpen, setReorderOpen] = useState(false);
  // Auto-clock-in state (tech only)
  const [autoToast, setAutoToast] = useState(null); // {entry_id, job_id, job_title, customer_name}
  const autoToastRef = useRef(null);
  const [pendingCancel, setPendingCancel] = useState(false);
  // Selected date — from URL query or today.
  const [selectedDate, setSelectedDate] = useState(() => {
    try {
      const p = new URLSearchParams(window.location.search);
      const d = p.get("date");
      if (d && /^\d{4}-\d{2}-\d{2}$/.test(d)) return d;
    } catch {}
    return new Date().toISOString().slice(0, 10);
  });
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [nowIso, setNowIso] = useState(new Date().toISOString());
  const [legMap, setLegMap] = useState({});  // {`from|to`: {distance,duration}}
  const { isLoaded } = useJsApiLoader({
    id: "gm-script",
    googleMapsApiKey: process.env.REACT_APP_GOOGLE_API_KEY,
    libraries: GOOGLE_LIBS,
  });

  const load = useCallback(async () => {
    setBusy(true);
    try { setData(await api.get(`/schedule/today?date=${selectedDate}`)); }
    finally { setBusy(false); }
  }, [selectedDate]);
  useEffect(() => { load(); }, [load]);
  // Sync selectedDate → URL query so refresh preserves the view.
  useEffect(() => {
    try {
      const url = new URL(window.location.href);
      const today = new Date().toISOString().slice(0, 10);
      if (selectedDate === today) url.searchParams.delete("date");
      else url.searchParams.set("date", selectedDate);
      window.history.replaceState({}, "", url.toString());
    } catch {}
  }, [selectedDate]);

  const shiftDate = (delta) => {
    const d = new Date(selectedDate + "T12:00:00");
    d.setDate(d.getDate() + delta);
    setSelectedDate(d.toISOString().slice(0, 10));
  };
  const isToday = selectedDate === new Date().toISOString().slice(0, 10);

  // "Now" indicator ticks
  useEffect(() => {
    const t = setInterval(() => setNowIso(new Date().toISOString()), 60_000);
    return () => clearInterval(t);
  }, []);

  // Phase 19 · Auto-clock-in via GPS (tech only, foreground schedule tab)
  useEffect(() => {
    if (!isTech || !navigator.geolocation) return;
    let lastCall = 0;
    let cancelled = false;
    const tryAuto = async (pos) => {
      const now = Date.now();
      if (now - lastCall < 15_000) return;  // 15s poll gate (server also throttles)
      if (autoToastRef.current || cancelled) return;
      lastCall = now;
      try {
        const r = await api.post("/workforce/auto-clock-in", {
          lat: pos.coords.latitude, lng: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        });
        if (r?.clocked_in) {
          setAutoToast(r);
          autoToastRef.current = r;
        }
      } catch (_e) { /* ignore transient errors — user can still manual */ }
    };
    const watchId = navigator.geolocation.watchPosition(
      tryAuto, () => {}, { enableHighAccuracy: true, maximumAge: 5_000, timeout: 15_000 }
    );
    return () => {
      cancelled = true;
      navigator.geolocation.clearWatch(watchId);
    };
  }, [isTech]);

  // 10-second grace window before we auto-navigate to the report.
  useEffect(() => {
    if (!autoToast) return;
    const t = setTimeout(() => {
      if (autoToastRef.current) {
        navigate(`/jobs/${autoToast.job_id}/service-report`);
        autoToastRef.current = null;
        setAutoToast(null);
      }
    }, 10_000);
    return () => clearTimeout(t);
  }, [autoToast, navigate]);

  const cancelAutoClockIn = async () => {
    if (!autoToast) return;
    setPendingCancel(true);
    try {
      await api.post(`/workforce/cancel-auto-clock-in/${autoToast.entry_id}`);
    } catch (e) { alert(e.message); }
    finally {
      autoToastRef.current = null;
      setAutoToast(null);
      setPendingCancel(false);
    }
  };

  // Hydrate route-leg distances via Google Distance Matrix (client-side)
  useEffect(() => {
    if (!isLoaded || !data?.route_legs?.length || !window.google?.maps) return;
    const uncached = data.route_legs.filter((l) => !l.cached);
    if (uncached.length === 0) {
      // Populate legMap from server cache
      const seed = {};
      data.route_legs.forEach((l) => {
        seed[`${l.from_job_id}|${l.to_job_id}`] = {
          distance_meters: l.distance_meters, duration_seconds: l.duration_seconds,
        };
      });
      setLegMap(seed);
      return;
    }
    const svc = new window.google.maps.DistanceMatrixService();
    // One request per leg keeps it simple + billable per element only.
    Promise.all(uncached.map((l) => new Promise((resolve) => {
      svc.getDistanceMatrix({
        origins: [{ lat: l.from_lat, lng: l.from_lng }],
        destinations: [{ lat: l.to_lat, lng: l.to_lng }],
        travelMode: window.google.maps.TravelMode.DRIVING,
      }, (res, status) => {
        if (status !== "OK" || !res?.rows?.[0]?.elements?.[0]) { resolve(null); return; }
        const el = res.rows[0].elements[0];
        if (el.status !== "OK") { resolve(null); return; }
        resolve({
          from_lat: l.from_lat, from_lng: l.from_lng,
          to_lat: l.to_lat, to_lng: l.to_lng,
          from_job_id: l.from_job_id, to_job_id: l.to_job_id,
          distance_meters: el.distance.value,
          duration_seconds: el.duration.value,
        });
      });
    }))).then(async (results) => {
      const ok = results.filter(Boolean);
      const cachePayload = { legs: ok.map(({ from_lat, from_lng, to_lat, to_lng, distance_meters, duration_seconds }) =>
        ({ from_lat, from_lng, to_lat, to_lng, distance_meters, duration_seconds })) };
      const merged = { ...legMap };
      // Merge server-cached first
      data.route_legs.filter((l) => l.cached).forEach((l) => {
        merged[`${l.from_job_id}|${l.to_job_id}`] = {
          distance_meters: l.distance_meters, duration_seconds: l.duration_seconds,
        };
      });
      ok.forEach((l) => {
        merged[`${l.from_job_id}|${l.to_job_id}`] = {
          distance_meters: l.distance_meters, duration_seconds: l.duration_seconds,
        };
      });
      setLegMap(merged);
      if (ok.length) { try { await api.post("/schedule/route-leg", cachePayload); } catch {} }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoaded, data]);

  // Timeline hour window: 6am–8pm default, expanded to first/last item ±1h.
  const [minH, maxH] = useMemo(() => {
    let lo = 6, hi = 20;
    if (data?.items?.length) {
      const hours = data.items.map((it) => {
        const s = it.scheduled_start || it.clock_in_at || it.start;
        if (!s) return null;
        try { return new Date(s).getHours(); } catch { return null; }
      }).filter((h) => h !== null);
      if (hours.length) {
        lo = Math.min(lo, Math.min(...hours) - 1);
        hi = Math.max(hi, Math.max(...hours) + 1);
      }
    }
    return [Math.max(0, lo), Math.min(23, hi)];
  }, [data]);

  const HOUR_ROW = 84;  // px per hour

  const yFor = (iso) => {
    if (!iso) return 0;
    try {
      const d = new Date(iso);
      const decimalHour = d.getHours() + d.getMinutes() / 60;
      return (decimalHour - minH) * HOUR_ROW;
    } catch { return 0; }
  };

  const nowY = useMemo(() => yFor(nowIso), [nowIso, minH]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: yFor intentionally omitted (mount-only / stable-ref)

  const s = data?.summary || {};
  const jobItems = useMemo(
    () => (data?.items || []).filter((it) => it.type === "job"),
    [data]
  );

  // ── Optimize Route (Phase 20A.1) ──────────────────────────────────────
  const [optimizedIds, setOptimizedIds] = useState(null);   // list of job_ids or null
  const [optimizeMeta, setOptimizeMeta] = useState(null);   // { saved_m, saved_s, total_m, total_s }
  const [optimizing, setOptimizing] = useState(false);

  const haversineM = (aLat, aLng, bLat, bLng) => {
    if (aLat == null || aLng == null || bLat == null || bLng == null) return 0;
    const R = 6371000, toRad = (d) => (d * Math.PI) / 180;
    const dLat = toRad(bLat - aLat), dLng = toRad(bLng - aLng);
    const s = Math.sin(dLat / 2) ** 2 +
              Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(s));
  };

  const originalDistanceM = useMemo(() => {
    // Baseline = jobs in server order (scheduled_start), summed via Haversine.
    let sum = 0;
    for (let i = 1; i < jobItems.length; i++) {
      const a = jobItems[i - 1], b = jobItems[i];
      sum += haversineM(a.site_lat ?? a.lat, a.site_lng ?? a.lng,
                        b.site_lat ?? b.lat, b.site_lng ?? b.lng);
    }
    return sum;
  }, [jobItems]);

  const handleOptimize = async () => {
    if (optimizing) return;
    setOptimizing(true);
    try {
      let coords = {};
      try {
        coords = await new Promise((res) => {
          if (!navigator.geolocation) return res({});
          navigator.geolocation.getCurrentPosition(
            (p) => res({ start_lat: p.coords.latitude, start_lng: p.coords.longitude }),
            () => res({}),
            { enableHighAccuracy: true, timeout: 4000 },
          );
        });
      } catch {}
      const r = await api.post("/schedule/optimize-route", {
        date: selectedDate, ...coords,
      });
      const ids = r?.ordered_job_ids || [];
      if (ids.length === 0) {
        alert("Nothing to optimize (need at least 2 jobs with GPS coordinates).");
        return;
      }
      setOptimizedIds(ids);
      const total_m = r.total_distance_m || 0;
      const total_s = r.total_duration_s || 0;
      const saved_m = Math.max(0, originalDistanceM - total_m);
      // Rough conversion: same 35km/h assumption used server-side.
      const saved_s = Math.round(saved_m / (35 * 1000 / 3600));
      setOptimizeMeta({ total_m, total_s, saved_m, saved_s, cached: !!r.cached });
    } catch (e) { alert(e.message); }
    finally { setOptimizing(false); }
  };

  const resetOrder = () => { setOptimizedIds(null); setOptimizeMeta(null); };

  const orderedJobItems = useMemo(() => {
    if (!optimizedIds || optimizedIds.length === 0) return jobItems;
    const byId = Object.fromEntries(jobItems.map((j) => [j.id, j]));
    const out = optimizedIds.map((id) => byId[id]).filter(Boolean);
    // Append any jobs missing from the optimized list (e.g., no GPS) at the end.
    const seen = new Set(optimizedIds);
    for (const j of jobItems) if (!seen.has(j.id)) out.push(j);
    return out;
  }, [jobItems, optimizedIds]);

  // Feb-2026 · Phase 1 — first non-terminal job in today's order. Powers
  // the top-level "On my way — next job" CTA. Sorted by ``route_index``
  // then ``scheduled_time`` (both baked into ``orderedJobItems``).
  const nextOpenJob = useMemo(() => {
    const done = new Set(["completed", "canceled", "cancelled", "skipped"]);
    return orderedJobItems.find(
      (j) => !done.has(String(j.status || "").toLowerCase()),
    ) || null;
  }, [orderedJobItems]);

  // View mode: "list" (default) | "timeline". Persist per-user.
  const [viewMode, setViewMode] = useState(() => {
    try { return localStorage.getItem("schedule_view_mode") || "list"; }
    catch { return "list"; }
  });
  const setMode = (m) => {
    setViewMode(m);
    try { localStorage.setItem("schedule_view_mode", m); } catch {}
  };

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto" data-testid="today-schedule-page">
      {/* Feb-2026 · numbered-order reorder — admin-only pill at
          the very top of the today view opens the bulk modal.
          Techs never see this pill; they see the reordered route
          only (via ``orderedJobItems``). */}
      {isAdminForReorder && orderedJobItems.length >= 2 ? (
        <div className="flex justify-end mb-3">
          <button
            onClick={() => setReorderOpen(true)}
            className="inline-flex items-center gap-1 px-3 h-8 rounded-full text-xs font-bold shadow-sm"
            style={{ background: "#7C3AED", color: "#fff" }}
            data-testid="today-open-reorder"
          >
            Reorder…
          </button>
        </div>
      ) : null}

      {reorderOpen && isAdminForReorder ? (
        <BulkReorderModal
          jobs={orderedJobItems.filter(
            (j) => !["completed", "canceled", "cancelled", "skipped",
                     "could_not_service"].includes(
              String(j.status || "").toLowerCase()),
          )}
          date={new Date().toISOString().slice(0, 10)}
          onClose={() => setReorderOpen(false)}
          onSaved={() => { setReorderOpen(false); load?.(); }}
        />
      ) : null}
      {autoToast && (
        <div className="fixed top-4 right-4 z-50 rounded-xl shadow-xl p-4 max-w-sm"
             style={{ background: "#0F172A", color: "#fff" }}
             data-testid="auto-clockin-toast">
          <div className="text-xs uppercase font-bold tracking-wider opacity-80">
            ▶ Arrived — clocking in now
          </div>
          <div className="text-lg font-bold mt-1">
            {autoToast.customer_name || autoToast.job_title}
          </div>
          <div className="text-xs opacity-80 mt-1">
            {autoToast.distance_m != null ? `${Math.round(autoToast.distance_m)}m from site · ` : ""}
            Opening service report in 10s…
          </div>
          <div className="flex gap-2 mt-3">
            <button onClick={cancelAutoClockIn} disabled={pendingCancel}
                    className="px-3 py-1 rounded text-xs font-bold"
                    style={{ background: "#fff", color: "#0F172A" }}
                    data-testid="auto-clockin-cancel">
              {pendingCancel ? "Cancelling…" : "Cancel"}
            </button>
            <button onClick={() => {
                      autoToastRef.current = null;
                      navigate(`/jobs/${autoToast.job_id}/service-report`);
                      setAutoToast(null);
                    }}
                    className="px-3 py-1 rounded text-xs font-bold"
                    style={{ background: colors.brand, color: "#fff" }}
                    data-testid="auto-clockin-open-now">
              Open now →
            </button>
          </div>
        </div>
      )}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>Today's Schedule</h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            {data?.date ? new Date(data.date + "T12:00:00").toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" }) : "…"} · {data?.tz}
          </p>
        </div>
        <div className="flex gap-2">
          <div className="rounded-xl flex items-center overflow-hidden"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="schedule-view-toggle">
            {["list", "timeline"].map((m) => (
              <button key={m} onClick={() => setMode(m)}
                      className="px-3 py-2 text-xs font-bold uppercase tracking-wide"
                      style={{
                        backgroundColor: viewMode === m ? colors.brand : "transparent",
                        color: viewMode === m ? "#fff" : colors.onSurfaceSecondary,
                      }}
                      data-testid={`schedule-view-${m}`}>
                {m}
              </button>
            ))}
          </div>
          <button onClick={load}
                  className="px-3 py-2 rounded-xl text-sm font-semibold flex items-center gap-1"
                  style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface,
                           border: `1px solid ${colors.border}` }}
                  data-testid="schedule-refresh">
            <RefreshCw size={14}/> Refresh
          </button>
          {jobItems.length >= 2 && (
            <button onClick={handleOptimize} disabled={optimizing}
                    className="px-3 py-2 rounded-xl text-sm font-bold flex items-center gap-1 disabled:opacity-60 transition-all"
                    style={{ background: brandGradientCss, color: "#fff",
                             transform: optimizing ? "scale(0.98)" : "scale(1)" }}
                    data-testid="schedule-optimize-route">
              <RouteIcon size={14}/> {optimizing ? "Optimizing…" : "Optimize Route"}
            </button>
          )}
          {optimizedIds && (
            <button onClick={resetOrder}
                    className="px-3 py-2 rounded-xl text-sm font-semibold flex items-center gap-1"
                    style={{ backgroundColor: colors.surface, color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                    data-testid="schedule-reset-order">
              <RotateCcw size={14}/> Reset order
            </button>
          )}
        </div>
      </div>

      {/* Date picker — prev / date / next / Today */}
      <div className="flex items-center gap-2 mb-4 flex-wrap" data-testid="schedule-date-picker">
        <button onClick={() => shiftDate(-1)}
                className="p-2 rounded-lg flex items-center justify-center"
                style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface,
                         color: colors.onSurface }}
                data-testid="schedule-date-prev" aria-label="Previous day">
          <ChevronLeft size={16}/>
        </button>
        <label className="flex-1 min-w-[220px] px-3 py-2 rounded-lg flex items-center justify-center gap-2 cursor-pointer"
               style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface }}>
          <CalendarCheck size={14} style={{ color: colors.brand }}/>
          <span className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            {isToday ? "Today · " : ""}
            {new Date(selectedDate + "T12:00:00").toLocaleDateString([], {
              weekday: "short", month: "short", day: "numeric", year: "numeric",
            })}
          </span>
          <input type="date" value={selectedDate}
                 onChange={(e) => setSelectedDate(e.target.value)}
                 className="ml-2 text-xs"
                 style={{ backgroundColor: "transparent", color: colors.muted, cursor: "pointer" }}
                 data-testid="schedule-date-input"/>
        </label>
        <button onClick={() => shiftDate(1)}
                className="p-2 rounded-lg flex items-center justify-center"
                style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface,
                         color: colors.onSurface }}
                data-testid="schedule-date-next" aria-label="Next day">
          <ChevronRight size={16}/>
        </button>
        {!isToday && (
          <button onClick={() => setSelectedDate(new Date().toISOString().slice(0, 10))}
                  className="px-3 py-2 rounded-lg text-xs font-bold uppercase tracking-wide"
                  style={{ backgroundColor: colors.brand, color: "#fff" }}
                  data-testid="schedule-date-today">
            Today
          </button>
        )}
      </div>

      {/* Optimized-route savings chip */}
      {optimizeMeta && (
        <div className="mb-4 rounded-xl px-4 py-3 flex items-center gap-3 flex-wrap animate-in fade-in"
             style={{ backgroundColor: "#ECFDF5", border: "1px solid #6EE7B7", color: "#065F46" }}
             data-testid="schedule-optimize-chip">
          <RouteIcon size={16}/>
          <span className="text-sm font-bold">
            Saved {(optimizeMeta.saved_m / 1609.344).toFixed(1)} mi ·{" "}
            {Math.max(1, Math.round(optimizeMeta.saved_s / 60))} min
          </span>
          <span className="text-xs opacity-80">
            New total: {(optimizeMeta.total_m / 1609.344).toFixed(1)} mi ·{" "}
            {Math.max(1, Math.round(optimizeMeta.total_s / 60))} min
            {optimizeMeta.cached ? " · cached" : ""}
          </span>
        </div>
      )}

      {/* Phase 16C 5-day forecast — removed from tech home 2026-07 per
          user request. The `<WeatherWidget5Day>` component still lives
          at `/pages/aitools/WeatherWidget5Day.jsx` and is imported by
          the admin Dashboard in case anyone re-enables it here later.
          The current-conditions card + small mini-forecast strip
          (rendered elsewhere via `<WeatherWidget>`) stay in place. */}

      {/* Summary bar */}
      <div className="rounded-2xl p-4 mb-6 flex items-center gap-6 flex-wrap"
           style={{ background: brandGradientCss, color: "#fff" }}
           data-testid="schedule-summary">
        <Stat label="Jobs" value={s.job_count ?? 0} testId="stat-jobs"/>
        <Stat label="Scheduled" value={`${s.scheduled_hours ?? 0}h`} testId="stat-scheduled"/>
        <Stat label="Clocked in" value={s.clocked_in ? "Yes" : "No"} testId="stat-clocked"/>
        <Stat label="Miles today" value={`${s.miles_logged_today ?? 0}`} testId="stat-miles"/>
        <Stat label="Hours logged" value={`${s.hours_logged_today ?? 0}h`} testId="stat-hours"/>
      </div>

      {busy && !data && <div style={{ color: colors.muted }} data-testid="schedule-loading">Loading…</div>}

      {data && data.items.length === 0 && (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="schedule-empty">
          <div className="text-lg font-semibold mb-2" style={{ color: colors.onSurface }}>Nothing on the books today.</div>
          <div className="text-sm mb-4" style={{ color: colors.muted }}>
            Enjoy the breather — or head over to Jobs to pick something up.
          </div>
          <button onClick={() => navigate("/jobs")}
                  className="px-4 py-2 rounded-xl text-white font-bold text-sm"
                  style={{ background: brandGradientCss }}
                  data-testid="schedule-go-to-jobs">
            View all jobs
          </button>
        </div>
      )}

      {/* Feb-2026 · Phase 1 — top-level "On my way — next job" CTA.
          Rendered above the list view. Visible only when there's an
          open job in today's queue and the caller's role can send
          (technician / manager / admin / super_admin). */}
      {data && nextOpenJob && (
        <div className="flex justify-center mb-4" data-testid="on-my-way-next-wrap">
          <OnMyWayButton
            jobId={nextOpenJob.id}
            customerFirstName={
              (nextOpenJob.customer_name || "").split(" ")[0] || ""
            }
            variant="primary"
            testId="on-my-way-next-btn"
          />
        </div>
      )}

      {/* List view — default */}
      {data && data.items.length > 0 && viewMode === "list" && (
        <ScheduleCardList jobs={orderedJobItems} tz={data.tz}
                          isTech={isTech}
                          onOpen={(id) => navigate(`/jobs/${id}`)}
                          onClockIn={async (job) => {
                            // Try to grab GPS (best-effort); still clock-in without it.
                            const geo = await new Promise((res) => {
                              if (!navigator.geolocation) return res({});
                              navigator.geolocation.getCurrentPosition(
                                (p) => res({ lat: p.coords.latitude, lng: p.coords.longitude,
                                             accuracy: p.coords.accuracy }),
                                () => res({}),
                                { enableHighAccuracy: true, timeout: 5000 },
                              );
                            });
                            try {
                              await api.post("/workforce/clock-in", { job_id: job.id, ...geo });
                            } catch (e) {
                              // If already clocked in on this job, still open the report.
                              if (!/open shift/i.test(e.message || "")) {
                                alert(e.message);
                                return;
                              }
                            }
                            navigate(`/jobs/${job.id}/service-report`);
                          }}/>
      )}

      {data && data.items.length > 0 && viewMode === "timeline" && (
        <div className="relative" data-testid="schedule-timeline"
             style={{ height: (maxH - minH + 1) * HOUR_ROW,
                      backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}`,
                      borderRadius: 20, padding: 12 }}>
          {/* Hour gridlines + labels */}
          {Array.from({ length: (maxH - minH + 1) }).map((_, i) => {
            const hr = minH + i;
            return (
              <React.Fragment key={hr}>
                <div style={{ position: "absolute", left: 60, right: 8,
                              top: i * HOUR_ROW, borderTop: `1px dashed ${colors.border}` }}/>
                <div style={{ position: "absolute", left: 8, top: i * HOUR_ROW - 6,
                              fontSize: 11, color: colors.muted, fontWeight: 600 }}>
                  {String(((hr + 11) % 12) + 1)} {hr < 12 ? "AM" : "PM"}
                </div>
              </React.Fragment>
            );
          })}

          {/* Now line */}
          {nowY >= 0 && nowY <= (maxH - minH + 1) * HOUR_ROW && (
            <div data-testid="schedule-now-line"
                 style={{ position: "absolute", left: 60, right: 8, top: nowY, height: 2,
                          backgroundColor: colors.error, zIndex: 5 }}>
              <div style={{ position: "absolute", left: -6, top: -4, width: 10, height: 10,
                            borderRadius: 999, backgroundColor: colors.error }}/>
              <div style={{ position: "absolute", right: 0, top: -20, fontSize: 10,
                            fontWeight: 700, color: colors.error }}>NOW</div>
            </div>
          )}

          {/* Items */}
          {data.items.map((it, i) => (
            <TimelineItem
              key={i} item={it} idx={i} yFor={yFor}
              tz={data.tz}
              onOpen={() => it.type === "job" && it.id && navigate(`/jobs/${it.id}`)}
            />
          ))}

          {/* Route legs — render on the left column between consecutive jobs */}
          {data.route_legs.map((l, idx) => {
            const fromItem = data.items.find((it) => it.type === "job" && it.id === l.from_job_id);
            const toItem = data.items.find((it) => it.type === "job" && it.id === l.to_job_id);
            if (!fromItem || !toItem) return null;
            const yStart = yFor(fromItem.scheduled_end || fromItem.scheduled_start);
            const yEnd = yFor(toItem.scheduled_start);
            const leg = legMap[`${l.from_job_id}|${l.to_job_id}`] || {};
            return (
              <div key={idx}
                   style={{ position: "absolute", left: 60, right: 8,
                            top: yStart + 4, height: Math.max(20, yEnd - yStart - 8) }}
                   className="flex items-center gap-2 pointer-events-none"
                   data-testid={`route-leg-${l.from_job_id}-${l.to_job_id}`}>
                <div style={{ borderLeft: `2px dashed ${colors.brandSecondary}`, height: "100%",
                              marginLeft: 12 }}/>
                <span className="text-xs font-semibold flex items-center gap-1 px-2 py-0.5 rounded-full pointer-events-auto"
                      style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
                  <Car size={12}/>
                  {leg.duration_seconds != null
                    ? `${fmtDur(leg.duration_seconds)} · ${fmtMi(leg.distance_meters)}`
                    : "…"}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, testId }) {
  return (
    <div data-testid={testId}>
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-xs opacity-90">{label}</div>
    </div>
  );
}

function TimelineItem({ item, idx, yFor, tz, onOpen }) {
  const startIso = item.scheduled_start || item.clock_in_at || item.start;
  const endIso   = item.scheduled_end   || item.clock_out_at || item.end;
  const y = yFor(startIso);
  const yEnd = endIso ? yFor(endIso) : y + 60;
  const height = Math.max(48, yEnd - y);
  const left = item.type === "job" ? 84 : (item.type === "shift" ? 20 : 40);
  const right = item.type === "job" ? 8 : 40;

  if (item.type === "job") {
    return (
      <div onClick={onOpen}
           className="rounded-xl p-3 cursor-pointer overflow-hidden"
           style={{
             position: "absolute", top: y, left, right, height,
             backgroundColor: colors.surface,
             border: `1px solid ${colors.border}`,
             boxShadow: `0 1px 3px rgba(0,0,0,0.05)`,
           }}
           data-testid={`schedule-job-${item.id}`}>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-bold" style={{ color: colors.brand }}>
            {fmtTime(startIso, tz)}{endIso ? ` – ${fmtTime(endIso, tz)}` : ""}
          </span>
          <StatusPill status={item.status}/>
        </div>
        <div className="font-bold text-sm" style={{ color: colors.onSurface }}>{item.title}</div>
        <div className="text-xs" style={{ color: colors.muted }}>
          {item.customer_name || "—"}
        </div>
        {item.address && (
          <div className="flex items-center gap-1 text-xs mt-1" style={{ color: colors.onSurfaceSecondary }}>
            <MapPin size={11}/> <span className="truncate">{item.address}</span>
          </div>
        )}
        {item.lat && item.lng && (
          <a href={`https://www.google.com/maps/dir/?api=1&destination=${item.lat},${item.lng}`}
             target="_blank" rel="noreferrer"
             onClick={(e) => e.stopPropagation()}
             className="inline-flex items-center gap-1 mt-2 text-xs font-semibold"
             style={{ color: colors.brand }}
             data-testid={`schedule-job-directions-${item.id}`}>
            <Navigation size={11}/> Directions
          </a>
        )}
      </div>
    );
  }

  if (item.type === "shift") {
    return (
      <div className="rounded-xl px-2 py-1"
           style={{
             position: "absolute", top: y, left: 62, width: 18,
             height: Math.max(24, height),
             backgroundColor: item.out_of_geofence ? "#FEE2E2" : "#DCFCE7",
             border: `1px solid ${item.out_of_geofence ? colors.error : colors.success}`,
           }}
           title={item.out_of_geofence ? "Clocked out of geofence" : "Shift"}
           data-testid={`schedule-shift-${item.entry_id}`}/>
    );
  }

  // Break
  return (
    <div style={{ position: "absolute", top: y, left: 45, width: 12,
                  height: Math.max(18, height),
                  backgroundColor: "#FEF3C7",
                  border: `1px solid #92400E`,
                  borderRadius: 4 }}
         title="Break"
         data-testid={`schedule-break-${item.entry_id}-${idx}`}/>
  );
}

function StatusPill({ status }) {
  const map = {
    pending: { bg: colors.surfaceSecondary, fg: colors.muted },
    active: { bg: "#DCFCE7", fg: colors.success },
    in_progress: { bg: "#DCFCE7", fg: colors.success },
    completed: { bg: colors.brandTertiary, fg: colors.onBrandTertiary },
    cancelled: { bg: "#FEE2E2", fg: colors.error },
  };
  const c = map[status] || map.pending;
  return (
    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
          style={{ backgroundColor: c.bg, color: c.fg }}>
      {status || "—"}
    </span>
  );
}

/* ────────────────────────────────────────────────────────────────────
   Card List view — the new default per user reference screenshot.
   Vertical stack of job cards: checkbox · service type (red) · customer ·
   full address · status pill · BH duration · chevron.
   ──────────────────────────────────────────────────────────────────── */
function billableHours(startIso, endIso) {
  if (!startIso || !endIso) return 0;
  try {
    const s = new Date(startIso).getTime();
    const e = new Date(endIso).getTime();
    return Math.max(0, (e - s) / 3600_000);
  } catch { return 0; }
}

function cardStatusTone(status) {
  const s = (status || "").toLowerCase();
  if (["completed", "closed", "done"].includes(s))
    return { bg: "#DCFCE7", fg: "#166534", label: s === "closed" ? "Closed" : "Completed" };
  if (["active", "in_progress"].includes(s))
    return { bg: "#FEF3C7", fg: "#92400E", label: "In Progress" };
  if (s === "cancelled")
    return { bg: "#FEE2E2", fg: "#991B1B", label: "Cancelled" };
  return { bg: "#DBEAFE", fg: "#1E40AF", label: "Scheduled" };
}

function ScheduleCardList({ jobs, tz, isTech, onOpen, onClockIn }) {
  const [checked, setChecked] = useState(() => new Set());
  const [expanded, setExpanded] = useState(() => new Set());
  const toggle = (id) => {
    const s = new Set(checked);
    if (s.has(id)) s.delete(id); else s.add(id);
    setChecked(s);
  };
  const toggleExpand = (id) => {
    const s = new Set(expanded);
    if (s.has(id)) s.delete(id); else s.add(id);
    setExpanded(s);
  };
  const combinedNotes = (j) =>
    [j.job_notes, j.access_notes, j.customer_notes].filter(Boolean).join("\n\n");
  if (!jobs.length) return null;
  return (
    <div className="rounded-2xl overflow-hidden"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid="schedule-card-list">
      {jobs.map((j, i) => {
        const bh = billableHours(j.scheduled_start, j.scheduled_end);
        const tone = cardStatusTone(j.status);
        const isChecked = checked.has(j.id);
        const isExpanded = expanded.has(j.id);
        const notesFull = combinedNotes(j);
        const notesPreview = notesFull.length > 100 ? notesFull.slice(0, 100) + "…" : notesFull;
        const cityLine = [j.city, j.state, j.zip].filter(Boolean).join(", ");
        return (
          <div key={j.id || i}
               style={{ borderBottom: i < jobs.length - 1 ? `1px solid ${colors.border}` : "none" }}
               data-testid={`schedule-card-${j.id}`}>
            <div className="flex items-start gap-3 p-4 hover:brightness-[0.98] cursor-pointer"
                 onClick={() => onOpen(j.id)}>
              {/* Checkbox */}
              <button onClick={(e) => { e.stopPropagation(); toggle(j.id); }}
                      className="mt-1 flex-shrink-0"
                      style={{ color: isChecked ? colors.brand : colors.muted }}
                      data-testid={`schedule-card-check-${j.id}`}
                      aria-label={isChecked ? "Uncheck" : "Check"}>
                {isChecked ? <CheckSquare size={20}/> : <Square size={20}/>}
              </button>

              {/* Body */}
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2 mb-1">
                  <div className="text-sm font-extrabold uppercase tracking-wide flex items-center gap-1.5"
                       style={{ color: "#DC2626" }}
                       data-testid={`schedule-card-service-${j.id}`}>
                    {/* Feb-2026 · Schedule polish — the per-card
                        <TechAvatar> that used to render the tech's
                        initials next to the service label was
                        removed; the today view is already
                        tech-scoped, so the per-row avatar was
                        redundant clutter. */}
                    <span>{j.service_type || j.title || "Service"}</span>
                  </div>
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide flex-shrink-0"
                        style={{ backgroundColor: tone.bg, color: tone.fg }}
                        data-testid={`schedule-card-status-${j.id}`}>
                    {tone.label}
                  </span>
                </div>
                <div className="text-base font-bold flex items-center gap-1.5 flex-wrap" style={{ color: colors.onSurface }}
                     data-testid={`schedule-card-customer-${j.id}`}>
                  <span>{j.customer_name || "—"}</span>
                  {j.customer_is_vip ? (
                    <span
                      className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider"
                      style={{
                        backgroundColor: "#FEF3C7",
                        color: "#92400E",
                        border: "1px solid #F59E0B",
                      }}
                      data-testid={`job-vip-badge-${j.id}`}
                      data-vip="true"
                      title="VIP customer"
                    >
                      <Star size={9} fill="#F59E0B" color="#F59E0B" /> VIP
                    </span>
                  ) : null}
                </div>
                <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}
                     data-testid={`schedule-card-address-${j.id}`}>
                  {j.address || "—"}
                </div>
                {cityLine && (
                  <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
                    {cityLine}
                  </div>
                )}

                {/* Gate code + notes preview (Phase 16C follow-up) */}
                {(j.gate_code || notesFull || j.service_note) && (
                  <div className="mt-2 flex items-start gap-2 flex-wrap">
                    {/* Feb-2026 Note-pill — specialty-specific instruction
                        surfaced from customer.service_notes.{pool,landscape}
                        based on this job's service_type. */}
                    <ServiceNotePill
                      note={j.service_note}
                      serviceType={j.service_type}
                      jobId={j.id}
                    />
                    {j.gate_code && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          try { navigator.clipboard.writeText(j.gate_code); } catch {}
                        }}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-bold cursor-copy"
                        style={{ backgroundColor: "#FEF3C7", color: "#92400E",
                                 fontFamily: "ui-monospace, SFMono-Regular, monospace",
                                 border: "1px solid #FDE68A" }}
                        title="Click to copy"
                        data-testid={`schedule-card-gate-${j.id}`}>
                        <Key size={11}/> {j.gate_code}
                      </button>
                    )}
                    {j.gate_code && (
                      <span data-testid={`job-gate-code-${j.id}`} className="sr-only">
                        {j.gate_code}
                      </span>
                    )}
                    {notesFull && (
                      <button onClick={(e) => { e.stopPropagation(); toggleExpand(j.id); }}
                              className="inline-flex items-start gap-1 text-xs text-left"
                              style={{ color: colors.onSurfaceSecondary }}
                              data-testid={`schedule-card-notes-${j.id}`}>
                        <StickyNote size={11} className="mt-0.5 flex-shrink-0"
                                    style={{ color: colors.muted }}/>
                        <span data-testid={`job-notes-preview-${j.id}`}>
                          <span className="font-semibold">Notes: </span>
                          {isExpanded ? notesFull : notesPreview}
                          {notesFull.length > 100 && (
                            <span className="ml-1 font-semibold" style={{ color: colors.brand }}>
                              {isExpanded ? "less" : "more"}
                            </span>
                          )}
                        </span>
                      </button>
                    )}
                  </div>
                )}

                <div className="flex items-center justify-between mt-2">
                  <div className="flex items-center gap-1 text-xs" style={{ color: colors.muted }}>
                    <CalendarCheck size={13}/>
                    <span>{j.scheduled_start
                      ? new Date(j.scheduled_start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: tz })
                      : "No start time"}</span>
                  </div>
                  <div className="text-sm font-bold" style={{ color: colors.onSurface }}
                       data-testid={`schedule-card-bh-${j.id}`}>
                    {bh.toFixed(2)} BH
                  </div>
                </div>

                {/* Phase 18B follow-up — Tech quick actions */}
                {isTech && (j.status || "").toLowerCase() !== "completed" && (
                  <div className="flex gap-2 mt-3 flex-wrap">
                    {/* Feb-2026 · Phase 1 — compact per-job "On my way"
                        button. Same handler + toast surface as the
                        top-level primary CTA above the list view. */}
                    <OnMyWayButton
                      jobId={j.id}
                      customerFirstName={(j.customer_name || "").split(" ")[0] || ""}
                      variant="compact"
                      testId={`on-my-way-btn-${j.id}`}
                    />
                    <button
                      onClick={(e) => { e.stopPropagation(); onClockIn && onClockIn(j); }}
                      className="px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1"
                      style={{ background: "#DC2626", color: "#fff" }}
                      data-testid={`schedule-card-clockin-${j.id}`}>
                      ▶ Clock In & Start Report
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        window.location.assign(`/jobs/${j.id}/service-report`);
                      }}
                      className="px-3 py-1.5 rounded-lg text-xs font-bold"
                      style={{ backgroundColor: colors.surfaceSecondary,
                               color: colors.onSurface,
                               border: `1px solid ${colors.border}` }}
                      data-testid={`schedule-card-open-report-${j.id}`}>
                      Open Report
                    </button>
                  </div>
                )}
              </div>

              {/* Chevron */}
              <ChevronRight size={20} style={{ color: "#DC2626", flexShrink: 0, marginTop: 4 }}/>
            </div>
          </div>
        );
      })}
    </div>
  );
}

