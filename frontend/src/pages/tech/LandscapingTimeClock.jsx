/**
 * Phase 46.3 — Landscaping Time Clock (Web).
 *
 * Landscaping-only clock in/out screen. Uses browser geolocation and
 * hits the new /api/timeclock/{punch,today,summary} endpoints.
 * Backend enforces department === "landscaping" (403 otherwise); the
 * screen also shows a friendly message when the API rejects the user.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Clock, MapPin, MapPinOff, LogIn, LogOut, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";
import AdminPunchEditsPanel from "@/components/timeclock/AdminPunchEditsPanel";

const _ADMIN_ROLES = new Set(["admin", "super_admin", "owner", "manager"]);

function weekBounds(offset = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offset * 7);
  const day = d.getDay();
  const diff = (day + 6) % 7;
  const start = new Date(d);
  start.setDate(start.getDate() - diff);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  };
}

function fmtHms(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "—";
  }
}

async function readGeo() {
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) {
      resolve({ lat: null, lng: null, accuracy_m: null, geo_denied: true });
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy_m: pos.coords.accuracy || null,
        geo_denied: false,
      }),
      () => resolve({ lat: null, lng: null, accuracy_m: null, geo_denied: true }),
      { enableHighAccuracy: true, timeout: 8000 },
    );
  });
}

export default function LandscapingTimeClock() {
  const { user: _viewer } = useAuth();
  const [today, setToday] = useState(null);
  const [week, setWeek] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);

  const _isAdminViewer = _ADMIN_ROLES.has(
    String(_viewer?.role || "").toLowerCase(),
  );
  const [adminRange, setAdminRange] = useState(() => weekBounds(0));
  const [adminSummary, setAdminSummary] = useState(null);
  const [adminBusy, setAdminBusy] = useState(false);
  const [adminError, setAdminError] = useState(null);
  const [expandedTech, setExpandedTech] = useState(null);

  const load = async () => {
    setError(null);
    try {
      const t = await api.get("/timeclock/mine-today");
      setToday(t);
    } catch (e) {
      setError(e.message || "Failed to load today");
      setToday(null);
    }
    try {
      const { start, end } = weekBounds(0);
      const s = await api.get(`/timeclock/mine-summary?start=${start}&end=${end}`);
      setWeek(s);
    } catch {
      setWeek(null);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const loadAdminSummary = useCallback(async () => {
    if (!_isAdminViewer) return;
    setAdminBusy(true);
    setAdminError(null);
    try {
      const qs = `?start=${adminRange.start}&end=${adminRange.end}`;
      const data = await api.get(`/timeclock/admin-summary${qs}`);
      setAdminSummary(data);
    } catch (e) {
      setAdminError(e?.message || "Failed to load team aggregation");
      setAdminSummary(null);
    } finally {
      setAdminBusy(false);
    }
  }, [_isAdminViewer, adminRange.start, adminRange.end]);

  useEffect(() => {
    if (_isAdminViewer) loadAdminSummary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [_isAdminViewer, adminRange.start, adminRange.end]);

  // Tick every second while clocked in so the timer moves.
  useEffect(() => {
    if (!today?.clocked_in) return;
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [today?.clocked_in]);

  const openInAt = useMemo(() => {
    const punches = today?.punches || [];
    let openIn = null;
    for (const p of punches) {
      if (p.punch_type === "in") openIn = p;
      else if (p.punch_type === "out" && openIn) openIn = null;
    }
    return openIn?.timestamp || null;
  }, [today]);

  const runningSeconds = useMemo(() => {
    const base = today?.seconds || 0;
    if (!today?.clocked_in || !openInAt) return base;
    const started = new Date(openInAt).getTime();
    return base + Math.max(0, Math.floor((Date.now() - started) / 1000));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [today, openInAt, tick]);

  const doPunch = async (type) => {
    setBusy(true);
    setError(null);
    try {
      const geo = await readGeo();
      await api.post("/timeclock/punch", {
        punch_type: type,
        lat: geo.lat,
        lng: geo.lng,
        accuracy_m: geo.accuracy_m,
        source: "web",
        geo_denied: geo.geo_denied,
      });
      await load();
    } catch (e) {
      setError(e.message || "Punch failed");
    } finally {
      setBusy(false);
    }
  };

  const isBlocked = /Time Clock is available for landscaping/i.test(error || "");

  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="landscape-time-clock">
      <div className="flex items-start md:items-center flex-col md:flex-row md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            Time Clock
          </h1>
          <p className="text-sm mt-0.5" style={{ color: colors.muted }}>
            Landscaping crew — clock in / out with GPS.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1.5 rounded-md"
          style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
          data-testid="landscape-time-clock-refresh"
        >
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {isBlocked ? (
        <div
          className="rounded-2xl p-6 text-sm"
          style={{ background: "#FEF9C3", border: "1px solid #FDE68A", color: "#854D0E" }}
          data-testid="landscape-time-clock-blocked"
        >
          This screen is available for the landscaping crew only. If you should have
          access, ask an admin to set your department to <code>landscaping</code>.
        </div>
      ) : (
        <>
          <div
            className="rounded-2xl p-6 mb-4"
            style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
            data-testid="landscape-time-clock-card"
          >
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
              <Clock size={14} /> Today
            </div>
            <div className="mt-2 flex items-baseline gap-3">
              <div
                className="text-5xl font-bold tabular-nums"
                style={{ color: colors.onSurface }}
                data-testid="landscape-time-clock-timer"
              >
                {fmtHms(runningSeconds)}
              </div>
              <div
                className="text-xs font-bold px-2 py-1 rounded-full"
                style={{
                  background: today?.clocked_in ? "#DCFCE7" : colors.surfaceSecondary,
                  color: today?.clocked_in ? "#166534" : colors.muted,
                }}
                data-testid="landscape-time-clock-status"
              >
                {today?.clocked_in ? "Clocked in" : "Off the clock"}
              </div>
            </div>

            <div className="mt-5 flex gap-2 flex-wrap">
              <button
                type="button"
                disabled={busy || today?.clocked_in}
                onClick={() => doPunch("in")}
                className="inline-flex items-center gap-2 text-sm font-bold px-4 py-2.5 rounded-md"
                style={{
                  background: today?.clocked_in ? colors.surfaceSecondary : colors.brand,
                  color: today?.clocked_in ? colors.muted : "#fff",
                  border: `1px solid ${today?.clocked_in ? colors.border : colors.brand}`,
                  cursor: today?.clocked_in ? "not-allowed" : "pointer",
                }}
                data-testid="landscape-time-clock-punch-in"
              >
                <LogIn size={16} /> Clock In
              </button>
              <button
                type="button"
                disabled={busy || !today?.clocked_in}
                onClick={() => doPunch("out")}
                className="inline-flex items-center gap-2 text-sm font-bold px-4 py-2.5 rounded-md"
                style={{
                  background: !today?.clocked_in ? colors.surfaceSecondary : "#DC2626",
                  color: !today?.clocked_in ? colors.muted : "#fff",
                  border: `1px solid ${!today?.clocked_in ? colors.border : "#DC2626"}`,
                  cursor: !today?.clocked_in ? "not-allowed" : "pointer",
                }}
                data-testid="landscape-time-clock-punch-out"
              >
                <LogOut size={16} /> Clock Out
              </button>
            </div>

            {error && !isBlocked ? (
              <div
                className="mt-3 text-xs px-2 py-1.5 rounded-md"
                style={{ background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C" }}
                data-testid="landscape-time-clock-error"
              >
                {error}
              </div>
            ) : null}
          </div>

          <div
            className="rounded-2xl p-6 mb-4"
            style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
            data-testid="landscape-time-clock-week"
          >
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
                This week
              </div>
              <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
                {fmtHms(week?.total_seconds || 0)}
              </div>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {(week?.days || []).map((d) => (
                <div
                  key={d.day}
                  className="rounded-md px-2 py-1.5"
                  style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
                  data-testid={`landscape-time-clock-day-${d.day}`}
                >
                  <div className="text-[11px]" style={{ color: colors.muted }}>{d.day}</div>
                  <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                    {fmtHms(d.seconds)}
                  </div>
                </div>
              ))}
              {(week?.days || []).length === 0 && (
                <div className="text-xs col-span-full" style={{ color: colors.muted }}>
                  No punches yet this week.
                </div>
              )}
            </div>
          </div>

          <div
            className="rounded-2xl p-6"
            style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
            data-testid="landscape-time-clock-recent"
          >
            <div className="text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors.muted }}>
              Today's punches
            </div>
            {(today?.punches || []).length === 0 ? (
              <div className="text-xs" style={{ color: colors.muted }}>No punches yet today.</div>
            ) : (
              <ul className="space-y-1">
                {(today?.punches || []).map((p) => (
                  <li
                    key={p.id}
                    className="flex items-center justify-between text-sm px-2 py-1.5 rounded-md"
                    style={{ background: colors.surfaceSecondary }}
                    data-testid={`landscape-time-clock-punch-${p.id}`}
                  >
                    <span className="font-semibold" style={{ color: colors.onSurface }}>
                      {p.punch_type === "in" ? "In" : "Out"} · {fmtTime(p.timestamp)}
                    </span>
                    <span className="text-xs inline-flex items-center gap-1" style={{ color: colors.muted }}>
                      {p.geo_denied || p.lat == null
                        ? <><MapPinOff size={12} /> no GPS</>
                        : <><MapPin size={12} /> ±{Math.round(p.accuracy_m || 0)}m</>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}

      {_isAdminViewer ? (
        <div
          className="rounded-2xl p-5 md:p-6 mt-4"
          style={{ background: colors.surface,
                   border: `1px solid ${colors.border}` }}
          data-testid="landscape-time-clock-admin-aggregation"
        >
          <h2
            className="text-base md:text-lg font-bold mb-3"
            style={{ color: colors.onSurface }}
          >
            Team aggregation
          </h2>
          <div className="flex items-center gap-2 flex-wrap mb-3">
            <input
              type="date"
              value={adminRange.start}
              onChange={(e) =>
                setAdminRange((r) => ({ ...r, start: e.target.value }))
              }
              className="text-sm px-2 py-1.5 rounded-md"
              style={{ border: `1px solid ${colors.border}`,
                       background: "#FFFFFF", color: "#0F172A" }}
              data-testid="landscape-time-clock-admin-range-start"
            />
            <span className="text-xs"
                  style={{ color: colors.muted }}>→</span>
            <input
              type="date"
              value={adminRange.end}
              onChange={(e) =>
                setAdminRange((r) => ({ ...r, end: e.target.value }))
              }
              className="text-sm px-2 py-1.5 rounded-md"
              style={{ border: `1px solid ${colors.border}`,
                       background: "#FFFFFF", color: "#0F172A" }}
              data-testid="landscape-time-clock-admin-range-end"
            />
            <button
              type="button"
              onClick={loadAdminSummary}
              disabled={adminBusy}
              className="text-sm px-3 py-1.5 rounded-md font-semibold"
              style={{ background: adminBusy ? colors.surfaceSecondary
                                              : colors.brand,
                       color: adminBusy ? colors.muted : "#FFFFFF",
                       border: 0 }}
              data-testid="landscape-time-clock-admin-refresh"
            >
              {adminBusy ? "Loading..." : "Refresh"}
            </button>
            <button
              type="button"
              onClick={() => setAdminRange(weekBounds(0))}
              className="text-xs px-2 py-1.5 rounded-md"
              style={{ background: colors.surfaceSecondary,
                       border: `1px solid ${colors.border}`,
                       color: colors.onSurface }}
              data-testid="landscape-time-clock-admin-reset"
            >
              Reset to this week
            </button>
          </div>
          {adminError ? (
            <div
              className="text-xs mb-3 px-2 py-1.5 rounded-md"
              style={{ background: "#FEF2F2",
                       border: "1px solid #FECACA",
                       color: "#B91C1C" }}
              data-testid="landscape-time-clock-admin-error"
            >
              {adminError}
            </div>
          ) : null}
          <ul className="space-y-2">
            {(adminSummary?.techs || []).map((t) => (
              <li
                key={t.user_id}
                className="rounded-md px-3 py-2"
                style={{ background: colors.surfaceSecondary,
                         border: `1px solid ${colors.border}` }}
              >
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2">
                    <span
                      className="text-sm font-bold"
                      style={{ color: colors.onSurface }}
                      data-testid={`landscape-time-clock-admin-tech-name-${t.user_id}`}
                    >
                      {t.name}
                    </span>
                    <span
                      className="text-xs font-bold px-2 py-0.5 rounded-full"
                      style={{
                        background: t.status === "in"
                          ? "#DCFCE7" : colors.surfaceSecondary,
                        color: t.status === "in"
                          ? "#166534" : colors.muted,
                        border: `1px solid ${colors.border}`,
                      }}
                      data-testid={`landscape-time-clock-admin-tech-status-${t.user_id}`}
                    >
                      {t.status === "in" ? "Clocked In" : "Clocked Out"}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 flex-wrap text-xs"
                       style={{ color: colors.muted }}>
                    <span
                      data-testid={`landscape-time-clock-admin-tech-total-${t.user_id}`}
                    >
                      {Math.floor((t.total_seconds || 0) / 3600)}
                      :
                      {String(
                        Math.floor(((t.total_seconds || 0) % 3600) / 60),
                      ).padStart(2, "0")}
                    </span>
                    <span
                      data-testid={`landscape-time-clock-admin-tech-last-${t.user_id}`}
                    >
                      {t.last_punch
                        ? `${fmtTime(t.last_punch.ts)} · ${
                            typeof t.last_punch.lat === "number"
                              ? t.last_punch.lat.toFixed(2) : "?"
                          },${
                            typeof t.last_punch.lng === "number"
                              ? t.last_punch.lng.toFixed(2) : "?"
                          }`
                        : "No punches"}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setExpandedTech(
                          expandedTech === t.user_id ? null : t.user_id,
                        )
                      }
                      className="text-xs px-2 py-0.5 rounded-md"
                      style={{ background: "transparent",
                               border: `1px solid ${colors.border}`,
                               color: colors.onSurface }}
                      data-testid={`landscape-time-clock-admin-tech-expand-${t.user_id}`}
                    >
                      {expandedTech === t.user_id
                        ? "Hide History"
                        : "View History"}
                    </button>
                  </div>
                </div>
                {expandedTech === t.user_id ? (
                  <ul
                    className="mt-2 space-y-1"
                    data-testid={`landscape-time-clock-admin-tech-punches-${t.user_id}`}
                  >
                    {(t.punches || []).map((p) => (
                      <li
                        key={p.id}
                        className="text-xs"
                        style={{ color: colors.onSurface }}
                      >
                        {fmtTime(p.ts)} ·{" "}
                        {p.punch_type === "in" ? "In" : "Out"} ·{" "}
                        {typeof p.lat === "number"
                          ? p.lat.toFixed(2) : "?"}
                        ,
                        {typeof p.lng === "number"
                          ? p.lng.toFixed(2) : "?"}
                        {p.job_id ? ` · job=${p.job_id}` : ""}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
            {!adminSummary?.techs?.length && !adminBusy ? (
              <li
                className="text-xs"
                style={{ color: colors.muted }}
                data-testid="landscape-time-clock-admin-empty"
              >
                No landscape techs in this tenant.
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}

      <AdminPunchEditsPanel
        viewer={_viewer}
        teamMembers={adminSummary?.techs || []}
      />
    </div>
  );
}
