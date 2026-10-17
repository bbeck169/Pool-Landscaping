/**
 * Phase 49.3 — Landscape Time Clock Widget (web).
 *
 * Compact clock in/out banner rendered at the top of the main landing
 * page for users with `department === "landscaping"`. Renders nothing
 * for everyone else — no placeholder text, no "you're not landscaping"
 * message.
 *
 * Wires the same `/api/timeclock/{punch,mine-today,mine-summary}`
 * endpoints as the full LandscapingTimeClock page. Tap the primary
 * button to toggle in/out; geolocation is best-effort, permission
 * denial falls through with `geo_denied: true` + a yellow warning.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Clock, LogIn, LogOut, MapPinOff } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";
import { shouldShowTimeClock } from "@/lib/timeClockVisibility";

function weekBounds() {
  const d = new Date();
  const day = d.getDay();
  const diff = (day + 6) % 7;
  const start = new Date(d); start.setDate(start.getDate() - diff);
  const end = new Date(start); end.setDate(end.getDate() + 6);
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  };
}

function fmtHms(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  return `${hh}h ${String(mm).padStart(2, "0")}m`;
}

async function readGeo() {
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) {
      resolve({ lat: null, lng: null, accuracy_m: null, geo_denied: true });
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({
        lat: pos.coords.latitude, lng: pos.coords.longitude,
        accuracy_m: pos.coords.accuracy || null, geo_denied: false,
      }),
      () => resolve({ lat: null, lng: null, accuracy_m: null, geo_denied: true }),
      { enableHighAccuracy: true, timeout: 8000 },
    );
  });
}

export default function LandscapingClockWidget() {
  const { user } = useAuth();
  // TD-64 · Feb-2026 — single-source-of-truth visibility via the
  // shared helper.  The helper reads BE-authoritative
  // ``show_time_clock`` when present, else resolves
  // ``effective_department`` / ``department`` against
  // ``LANDSCAPE_DEPTS``.  Admins / super_admins never clock in on
  // this widget so they are explicitly short-circuited (admin
  // supervision happens on ``/landscape/time-clock`` instead).
  const role = (user?.role || "").toLowerCase();
  const isAdminLike = role === "admin" || role === "super_admin";
  const isLandscaper = !isAdminLike && shouldShowTimeClock(user);
  const [today, setToday] = useState(null);
  const [week, setWeek] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  // Phase 50.H — landscape techs may attach a shift to a specific job.
  const [assignedJobs, setAssignedJobs] = useState([]);
  const [selectedJobId, setSelectedJobId] = useState("");

  useEffect(() => {
    if (!isLandscaper) return;
    let alive = true;
    (async () => {
      try {
        const t = await api.get("/timeclock/mine-today");
        if (alive) setToday(t);
      } catch { /* silent — widget hides on error */ }
      try {
        const { start, end } = weekBounds();
        const s = await api.get(`/timeclock/mine-summary?start=${start}&end=${end}`);
        if (alive) setWeek(s);
      } catch { /* silent */ }
      // Phase 50.H — load today's assigned jobs for the dropdown.
      try {
        const j = await api.get("/timeclock/mine-jobs-today");
        if (alive) setAssignedJobs(j?.items || []);
      } catch { /* silent — widget still works with "General work" only */ }
    })();
    return () => { alive = false; };
  }, [isLandscaper]);

  useEffect(() => {
    if (!today?.clocked_in) return;
    const int = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(int);
  }, [today?.clocked_in]);

  const openInAt = useMemo(() => {
    let last = null;
    for (const p of today?.punches || []) {
      if (p.punch_type === "in") last = p;
      else if (p.punch_type === "out" && last) last = null;
    }
    return last?.timestamp || null;
  }, [today]);

  const runningSeconds = useMemo(() => {
    const base = today?.seconds || 0;
    if (!today?.clocked_in || !openInAt) return base;
    return base + Math.max(0, Math.floor((Date.now() - new Date(openInAt).getTime()) / 1000));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [today, openInAt, tick]);

  const doPunch = async () => {
    setBusy(true); setError(null);
    try {
      const geo = await readGeo();
      const punch_type = today?.clocked_in ? "out" : "in";
      await api.post("/timeclock/punch", {
        punch_type,
        lat: geo.lat, lng: geo.lng, accuracy_m: geo.accuracy_m,
        source: "web", geo_denied: geo.geo_denied,
        // Phase 50.H — attach the picked job (blank string ⇒ null).
        job_id: punch_type === "in" ? (selectedJobId || null) : null,
      });
      const [t, w] = await Promise.all([
        api.get("/timeclock/mine-today"),
        (async () => {
          const { start, end } = weekBounds();
          try { return await api.get(`/timeclock/mine-summary?start=${start}&end=${end}`); }
          catch { return null; }
        })(),
      ]);
      setToday(t); if (w) setWeek(w);
      if (geo.geo_denied) setError("GPS denied — punch recorded without location.");
    } catch (e) {
      setError(e.message || "Punch failed");
    } finally { setBusy(false); }
  };

  if (!isLandscaper) return null;

  const clocked = !!today?.clocked_in;

  return (
    <div
      className="rounded-2xl p-4 mb-4 flex items-center gap-4 flex-wrap"
      style={{
        background: clocked ? "linear-gradient(135deg, #DCFCE7 0%, #ECFDF5 100%)" : colors.surface,
        border: `1px solid ${clocked ? "#86EFAC" : colors.border}`,
      }}
      data-testid="landscape-clock-widget"
    >
      <div className="flex items-center gap-3 flex-1 min-w-[240px]">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center"
          style={{ background: clocked ? "#16A34A" : colors.brandTertiary,
                   color: clocked ? "#fff" : colors.onBrandTertiary }}
        >
          <Clock size={20} />
        </div>
        <div>
          <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
            {clocked ? "On the clock" : "Off the clock"}
          </div>
          <div className="text-2xl font-bold tabular-nums" style={{ color: colors.onSurface }}
               data-testid="landscape-clock-widget-timer">
            {fmtHms(runningSeconds)}
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            {week?.total_seconds
              ? <>This week: <b>{fmtHms(week.total_seconds)}</b></>
              : "This week: —"}
            {" · "}
            <Link to="/landscape/time-clock" className="underline"
                  style={{ color: colors.brand }}
                  data-testid="landscape-clock-widget-open-full">
              Full view
            </Link>
          </div>
        </div>
      </div>
      <button
        type="button"
        onClick={doPunch}
        disabled={busy}
        className="inline-flex items-center gap-2 text-sm font-bold px-5 py-3 rounded-md"
        style={{
          background: clocked ? "#DC2626" : colors.brand,
          color: "#fff",
          border: 0,
          cursor: busy ? "wait" : "pointer",
        }}
        data-testid={clocked ? "landscape-clock-widget-out" : "landscape-clock-widget-in"}
      >
        {clocked ? <LogOut size={16} /> : <LogIn size={16} />}
        {clocked ? "Clock Out" : "Clock In"}
      </button>
      {!clocked && assignedJobs.length > 0 ? (
        <div className="w-full flex items-center gap-2 flex-wrap"
             data-testid="landscape-clock-widget-job-picker">
          <label className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: colors.muted }}>
            Attach to
          </label>
          <select
            value={selectedJobId}
            onChange={(e) => setSelectedJobId(e.target.value)}
            disabled={busy}
            className="text-sm px-2 py-1.5 rounded-md flex-1 min-w-[220px]"
            style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
            data-testid="landscape-clock-widget-job-select"
          >
            <option value="">General work (no job)</option>
            {assignedJobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.customer_name || j.title || "Unnamed job"}
                {j.scheduled_start ? ` @ ${String(j.scheduled_start).slice(11, 16)}` : ""}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {error ? (
        <div
          className="w-full text-xs px-2 py-1.5 rounded-md inline-flex items-center gap-1"
          style={{ background: "#FEF9C3", border: "1px solid #FDE68A", color: "#854D0E" }}
          data-testid="landscape-clock-widget-warning"
        >
          <MapPinOff size={12} /> {error}
        </div>
      ) : null}
    </div>
  );
}
