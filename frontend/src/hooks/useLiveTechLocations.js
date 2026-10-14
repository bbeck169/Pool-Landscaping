/**
 * P1 Phase 3 · Feb-2026 — Live technician GPS pins hook.
 *
 * Polls ``GET /api/workforce/live-locations`` every 30s so the
 * Schedule page's live-tech overlay can render fresh pins.
 * Pauses polling when the browser tab is hidden
 * (``document.visibilityState !== "visible"``) — avoids ticking
 * through a backgrounded tab and burning the operator's quota
 * on empty refreshes.
 *
 * Admin UX contract
 * -----------------
 *   * Default ON for ``admin`` / ``super_admin`` / ``manager`` /
 *     ``dispatcher`` / ``owner`` (``shouldDefaultEnabled``).
 *   * Default OFF for every other role — techs can't read
 *     cross-tech locations anyway (the BE 403s them).
 *   * Toggle preference persists in ``localStorage`` keyed by
 *     ``live_tech_overlay.<user_id>`` so each operator keeps
 *     their own choice.
 *
 * Returns
 * -------
 *   { pings, serverTime, enabled, setEnabled, loading, error }
 *
 *   * ``pings`` — array matching the BE contract (user_id,
 *     user_name, lat, lon, captured_at, age_seconds, staleness).
 *   * ``serverTime`` — ISO string from the latest response, used
 *     by consumers to render "updated Xm ago" without local
 *     drift.
 *   * ``enabled`` + ``setEnabled`` — toggle state.
 *   * ``loading`` + ``error`` — standard async flags.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api";
import { useAuth } from "@/auth";


const POLL_INTERVAL_MS = 30_000;
const DEFAULT_ENABLED_ROLES = new Set([
  "admin", "super_admin", "owner", "manager", "dispatcher",
]);
const _LS_PREFIX = "live_tech_overlay.";


export function shouldDefaultEnabled(role) {
  return DEFAULT_ENABLED_ROLES.has((role || "").toLowerCase());
}


function _loadPref(userId, roleDefault) {
  if (typeof window === "undefined") return roleDefault;
  try {
    const raw = window.localStorage.getItem(_LS_PREFIX + userId);
    if (raw === "1") return true;
    if (raw === "0") return false;
  } catch { /* jsdom / private-mode */ }
  return roleDefault;
}


function _savePref(userId, value) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      _LS_PREFIX + userId, value ? "1" : "0",
    );
  } catch { /* jsdom / private-mode */ }
}


export function useLiveTechLocations() {
  const auth = useAuth() || {};
  const { user } = auth;
  const userId = user?.id || "anon";
  const roleDefault = shouldDefaultEnabled(user?.role);

  const [enabled, _setEnabled] = useState(
    () => _loadPref(userId, roleDefault),
  );
  const [pings, setPings] = useState([]);
  const [serverTime, setServerTime] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const abortRef = useRef(null);
  const timerRef = useRef(null);

  const setEnabled = useCallback((v) => {
    _setEnabled(v);
    _savePref(userId, v);
  }, [userId]);

  const _fetch = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    try {
      const r = await api.get("/workforce/live-locations",
                              { signal: ctrl.signal });
      if (ctrl.signal.aborted) return;
      setPings(Array.isArray(r?.pings) ? r.pings : []);
      setServerTime(r?.server_time || null);
      setError(null);
    } catch (e) {
      if (ctrl.signal.aborted) return;
      // Non-fatal — the overlay just stops updating until the
      // next tick; the previous pings stay rendered.
      setError(e?.message || "live-locations fetch failed");
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, []);

  // Boot the poller when enabled + the tab is visible.  Pauses
  // automatically on hide, resumes on show.
  useEffect(() => {
    if (!enabled) {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      if (abortRef.current) abortRef.current.abort();
      setPings([]);
      setServerTime(null);
      setError(null);
      setLoading(false);
      return;
    }

    const start = () => {
      if (timerRef.current) return;
      _fetch();
      timerRef.current = setInterval(_fetch, POLL_INTERVAL_MS);
    };
    const stop = () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      if (abortRef.current) abortRef.current.abort();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") start();
      else stop();
    };

    if (typeof document !== "undefined") {
      if (document.visibilityState === "visible") start();
      document.addEventListener("visibilitychange", onVisibility);
    } else {
      start();
    }

    return () => {
      stop();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
    };
  }, [enabled, _fetch]);

  return useMemo(() => ({
    pings, serverTime, enabled, setEnabled, loading, error,
  }), [pings, serverTime, enabled, setEnabled, loading, error]);
}


// ─── Pure helpers exposed for vitest ─────────────────────────────

const _COLOR_BY_STALENESS = {
  live:   "#22c55e",   // green-500
  recent: "#eab308",   // yellow-500
  stale:  "#94a3b8",   // slate-400
};


export function colorForStaleness(staleness) {
  return _COLOR_BY_STALENESS[staleness] || _COLOR_BY_STALENESS.stale;
}


export function formatAge(ageSeconds) {
  const s = Math.max(0, Number(ageSeconds) || 0);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return mm ? `${h}h ${mm}m ago` : `${h}h ago`;
}
