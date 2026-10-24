/**
 * Landscape Time Clock Widget (web).
 *
 * TD-timeclock-tech-clock-out-flow · Feb-2026 — the widget was
 * previously writing to ``/api/timeclock/punch`` (``timeclock_punches``
 * collection) but every downstream display surface
 * (``/tech/time-clock``, ``/workforce/timesheets``, ``/admin/time-
 * entries``, ``TimecardEditModal``) reads from ``time_entries``.
 * Techs could clock in but the completed shift never surfaced on
 * their profile timecard or the admin timecard-management page.
 *
 * This widget now writes to ``/api/workforce/{clock-in,clock-out}``
 * (``time_entries`` collection) and derives its ``clocked-in?`` state
 * from the new ``GET /api/workforce/open-shift`` endpoint. Downstream
 * payroll, approvals, bulk edit, and the standard admin timeclock
 * review path all surface widget-written shifts for free.
 *
 * Visibility contract: self-guards on ``shouldShowTimeClock(user)``
 * (BE-authoritative via ``/auth/me``'s ``show_time_clock`` boolean +
 * ``effective_department`` fallback). Admin / super_admin never see
 * the widget — the per-tech widget is punch UX, not supervision.
 *
 * Known follow-up — see memory/TD-landscape-time-clock-unify-reads.md.
 * The ``/landscape/time-clock`` admin aggregation page still reads
 * from ``timeclock_punches`` so widget-sourced entries do NOT appear
 * there until that ticket lands (P2).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
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
      resolve({ lat: null, lng: null, accuracy: null, geo_denied: true });
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({
        lat: pos.coords.latitude, lng: pos.coords.longitude,
        accuracy: pos.coords.accuracy || null, geo_denied: false,
      }),
      () => resolve({ lat: null, lng: null, accuracy: null, geo_denied: true }),
      { enableHighAccuracy: true, timeout: 8000 },
    );
  });
}

function _toMs(iso) {
  if (!iso) return null;
  try {
    const t = new Date(iso).getTime();
    return Number.isFinite(t) ? t : null;
  } catch { return null; }
}

export default function LandscapingClockWidget() {
  const { user } = useAuth();
  const role = (user?.role || "").toLowerCase();
  const isAdminLike = role === "admin" || role === "super_admin";
  const isLandscaper = !isAdminLike && shouldShowTimeClock(user);

  const [openEntry, setOpenEntry] = useState(null);
  const [weekSeconds, setWeekSeconds] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const r = await api.get("/workforce/open-shift");
      setOpenEntry(r?.entry || null);
    } catch { /* silent — widget hides on error */ }
    try {
      const { start, end } = weekBounds();
      const rows = await api.get(
        `/workforce/timesheets?from=${start}T00:00:00&to=${end}T23:59:59`,
      );
      // ``/workforce/timesheets`` returns rows enriched with ``hours``
      // (regular + overtime included).  Sum into total seconds for
      // the "This week:" footer.
      const total = (rows || []).reduce(
        (s, r) => s + Math.round(((r?.hours || 0) * 3600)), 0,
      );
      setWeekSeconds(total);
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    if (!isLandscaper) return;
    refresh();
  }, [isLandscaper, refresh]);

  // Tick every second while clocked in so the running timer moves.
  useEffect(() => {
    if (!openEntry) return;
    const int = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(int);
  }, [openEntry]);

  const runningSeconds = useMemo(() => {
    const inMs = _toMs(openEntry?.clock_in_at);
    if (!inMs) return 0;
    return Math.max(0, Math.floor((Date.now() - inMs) / 1000));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openEntry, tick]);

  const clockIn = async () => {
    setBusy(true); setError(null);
    try {
      const geo = await readGeo();
      const r = await api.post("/workforce/clock-in", {
        job_id: null,
        lat: geo.lat, lng: geo.lng, accuracy: geo.accuracy,
      });
      // The POST returns the created entry — set it directly so the
      // button flips immediately without waiting on the probe round
      // trip.  Still fire ``refresh()`` to recompute the weekly
      // total.
      setOpenEntry(r || null);
      await refresh();
      if (geo.geo_denied) setError("GPS denied — shift started without location.");
    } catch (e) {
      setError(e?.message || "Clock in failed");
    } finally { setBusy(false); }
  };

  const clockOut = async () => {
    if (!openEntry?.id) return;
    setBusy(true); setError(null);
    try {
      const geo = await readGeo();
      await api.post("/workforce/clock-out", {
        entry_id: openEntry.id,
        lat: geo.lat ?? 0, lng: geo.lng ?? 0,
      });
      setOpenEntry(null);
      await refresh();
      if (geo.geo_denied) setError("GPS denied — shift closed without location.");
    } catch (e) {
      setError(e?.message || "Clock out failed");
    } finally { setBusy(false); }
  };

  if (!isLandscaper) return null;

  const clocked = !!openEntry;

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
            {weekSeconds
              ? <>This week: <b>{fmtHms(weekSeconds)}</b></>
              : "This week: —"}
            {" · "}
            <Link to="/tech/time-clock" className="underline"
                  style={{ color: colors.brand }}
                  data-testid="landscape-clock-widget-open-full">
              My timecard
            </Link>
          </div>
        </div>
      </div>
      <button
        type="button"
        onClick={clocked ? clockOut : clockIn}
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
