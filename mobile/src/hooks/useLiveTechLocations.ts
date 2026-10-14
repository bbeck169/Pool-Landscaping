/**
 * Live technician GPS pins hook — mobile parity for web 6db3c4f57
 * (`frontend/src/hooks/useLiveTechLocations.js`).
 *
 * Polls `GET /api/workforce/live-locations` every 30s while enabled.
 *   - Pauses when the app is backgrounded (`AppState` — mobile analogue
 *     of web `document.visibilitychange`), resumes on foreground.
 *   - In-flight request aborted (AbortController) on stop / unmount.
 *   - Default ON for admin / super_admin / owner / manager / dispatcher
 *     (same set as backend `require_gps_read`); OFF + never polls for
 *     everyone else (the backend 403s them).
 *   - Toggle persisted in AsyncStorage under `live_tech_overlay.<user_id>`
 *     ("1" / "0") — same key shape as web localStorage.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppState, type AppStateStatus } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";

export const POLL_INTERVAL_MS = 30_000;
export const PREF_PREFIX = "live_tech_overlay.";
const GPS_READ_ROLES = new Set(["admin", "super_admin", "owner", "manager", "dispatcher"]);

export type Staleness = "live" | "recent" | "stale";

export interface LiveTechPing {
  user_id: string;
  user_name: string;
  lat: number;
  lon: number;
  captured_at: string;
  age_seconds: number;
  staleness: Staleness;
}

/** Same role list as web `shouldDefaultEnabled` + backend `_GPS_READ_ROLES`. */
export function shouldDefaultEnabled(role?: string | null): boolean {
  return GPS_READ_ROLES.has(String(role || "").toLowerCase());
}

const COLOR_BY_STALENESS: Record<Staleness, string> = {
  live: "#22c55e", // green-500
  recent: "#eab308", // yellow-500
  stale: "#94a3b8", // slate-400
};

export function colorForStaleness(staleness?: string | null): string {
  return COLOR_BY_STALENESS[staleness as Staleness] || COLOR_BY_STALENESS.stale;
}

export function formatAge(ageSeconds?: number | null): string {
  const s = Math.max(0, Math.floor(Number(ageSeconds) || 0));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return mm ? `${h}h ${mm}m ago` : `${h}h ago`;
}

export function useLiveTechLocations() {
  const { user } = useAuth();
  const userId = user?.id || "anon";
  const canRead = shouldDefaultEnabled(user?.role);

  const [enabled, _setEnabled] = useState<boolean>(canRead);
  const [hydrated, setHydrated] = useState(false);
  const [pings, setPings] = useState<LiveTechPing[]>([]);
  const [serverTime, setServerTime] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Hydrate the persisted per-user preference (async on mobile).
  useEffect(() => {
    let alive = true;
    setHydrated(false);
    _setEnabled(canRead);
    AsyncStorage.getItem(PREF_PREFIX + userId)
      .then((raw) => {
        if (!alive) return;
        if (raw === "1") _setEnabled(true);
        else if (raw === "0") _setEnabled(false);
      })
      .catch(() => {})
      .finally(() => alive && setHydrated(true));
    return () => {
      alive = false;
    };
  }, [userId, canRead]);

  const setEnabled = useCallback(
    (v: boolean) => {
      _setEnabled(v);
      AsyncStorage.setItem(PREF_PREFIX + userId, v ? "1" : "0").catch(() => {});
    },
    [userId],
  );

  const fetchOnce = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    try {
      const r: any = await api.get("/workforce/live-locations", { signal: ctrl.signal });
      if (ctrl.signal.aborted) return;
      setPings(Array.isArray(r?.pings) ? r.pings : []);
      setServerTime(r?.server_time || null);
      setError(null);
    } catch (e: any) {
      if (ctrl.signal.aborted) return;
      // Non-fatal — previous pings stay rendered until the next tick.
      setError(e?.message || "live-locations fetch failed");
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, []);

  const active = enabled && canRead && hydrated;

  useEffect(() => {
    const stop = () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      abortRef.current?.abort();
    };
    if (!active) {
      stop();
      setPings([]);
      setServerTime(null);
      setError(null);
      setLoading(false);
      return;
    }
    const start = () => {
      if (timerRef.current) return;
      fetchOnce();
      timerRef.current = setInterval(fetchOnce, POLL_INTERVAL_MS);
    };
    const onAppState = (next: AppStateStatus) => {
      if (next === "active") start();
      else stop();
    };
    if (AppState.currentState !== "background") start();
    const sub = AppState.addEventListener("change", onAppState);
    return () => {
      stop();
      sub.remove();
    };
  }, [active, fetchOnce]);

  return useMemo(
    () => ({
      pings,
      serverTime,
      enabled: enabled && canRead,
      setEnabled,
      canRead,
      loading,
      error,
    }),
    [pings, serverTime, enabled, canRead, setEnabled, loading, error],
  );
}
