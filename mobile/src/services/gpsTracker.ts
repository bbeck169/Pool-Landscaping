/**
 * G1 · GPS Tracker Service
 *
 * Wraps expo-location for foreground + background GPS pings while a
 * technician is clocked in.  Buffers pings in AsyncStorage (max 60).
 * Flushes every 20 pings, every 2 min, on foreground return, or on
 * explicit call (clock-out).  On 409 → stops tracking + clears buffer.
 * On 413 → split batch in half and retry.
 */
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { AppState, AppStateStatus, Platform } from "react-native";
import { getAuthToken } from "@/src/api";

/* ── Constants ─────────────────────────────────────────────────────── */

const QUEUE_KEY = "gps_ping_queue_g1";
const MAX_BATCH = 60;
const FLUSH_THRESHOLD = 20;
const FLUSH_INTERVAL_MS = 2 * 60 * 1000; // 2 minutes
const BG_TASK_NAME = "gps-background-tracker";
const BASE = process.env.EXPO_PUBLIC_BACKEND_URL;

/* ── Types ─────────────────────────────────────────────────────────── */

export interface GpsConfig {
  enabled: boolean;
  ping_interval_foreground_s: number;
  ping_interval_background_s: number;
}

interface PingPayload {
  lat: number;
  lon: number;
  accuracy_m: number;
  heading?: number;
  speed_mps?: number;
  source: "foreground" | "background";
  captured_at: string;
}

/* ── Module state ──────────────────────────────────────────────────── */

let _tracking = false;
let _watchSub: Location.LocationSubscription | null = null;
let _flushTimerId: ReturnType<typeof setInterval> | null = null;
let _appStateListener: { remove(): void } | null = null;
let _onStoppedCb: (() => void) | null = null;
let _cachedToken: string = "";

/* ── Public API ────────────────────────────────────────────────────── */

/** Whether the tracker is actively collecting pings. */
export function isTracking(): boolean {
  return _tracking;
}

/** Register a callback invoked when tracking stops (e.g. 409). */
export function onTrackingStopped(cb: () => void) {
  _onStoppedCb = cb;
}

/** Fetch tenant GPS config from the backend. */
export async function fetchGpsConfig(): Promise<GpsConfig> {
  try {
    const headers = await authHeaders();
    const res = await fetch(`${BASE}/api/gps/config`, { headers });
    if (!res.ok)
      return { enabled: false, ping_interval_foreground_s: 60, ping_interval_background_s: 300 };
    return await res.json();
  } catch {
    return { enabled: false, ping_interval_foreground_s: 60, ping_interval_background_s: 300 };
  }
}

/**
 * Start foreground (+ best-effort background) GPS tracking.
 * Returns true if started, false if permission denied or config disabled.
 */
export async function startTracking(userToken?: string): Promise<boolean> {
  if (_tracking) return true;

  if (userToken) _cachedToken = userToken;
  else _cachedToken = await getAuthToken();

  // 1. Fetch config
  const config = await fetchGpsConfig();
  if (!config.enabled) return false;

  // 2. Request foreground permission
  const { status: fgStatus } = await Location.requestForegroundPermissionsAsync();
  if (fgStatus !== "granted") return false;

  _tracking = true;

  // 3. Foreground watch
  const intervalMs = Math.max((config.ping_interval_foreground_s || 60) * 1000, 5000);
  _watchSub = await Location.watchPositionAsync(
    { accuracy: Location.Accuracy.Balanced, timeInterval: intervalMs, distanceInterval: 0 },
    (loc) => {
      const ping: PingPayload = {
        lat: loc.coords.latitude,
        lon: loc.coords.longitude,
        accuracy_m: loc.coords.accuracy ?? 0,
        heading: loc.coords.heading ?? undefined,
        speed_mps: loc.coords.speed ?? undefined,
        source: "foreground",
        captured_at: new Date(loc.timestamp).toISOString(),
      };
      enqueue(ping);
    },
  );

  // 4. Background permission + task (best-effort, no crash on denial)
  try {
    if (Platform.OS !== "web") {
      const { status: bgStatus } = await Location.requestBackgroundPermissionsAsync();
      if (bgStatus === "granted") {
        const bgIntervalS = config.ping_interval_background_s || 300;
        await Location.startLocationUpdatesAsync(BG_TASK_NAME, {
          accuracy: Location.Accuracy.Balanced,
          timeInterval: bgIntervalS * 1000,
          deferredUpdatesInterval: bgIntervalS * 1000,
          showsBackgroundLocationIndicator: true,
          foregroundService: {
            notificationTitle: "Location tracking active",
            notificationBody: "Recording location during your shift",
          },
        });
      }
    }
  } catch {
    // Background not available — foreground-only is fine
  }

  // 5. Flush timer (every 2 min)
  _flushTimerId = setInterval(() => {
    flushBufferedPings().catch(() => {});
  }, FLUSH_INTERVAL_MS);

  // 6. Flush on app foreground return
  _appStateListener = AppState.addEventListener("change", _handleAppState);

  return true;
}

/** Stop tracking, unregister watch + background task. Does NOT flush. */
export async function stopTracking(): Promise<void> {
  _tracking = false;

  if (_watchSub) {
    _watchSub.remove();
    _watchSub = null;
  }
  if (_flushTimerId) {
    clearInterval(_flushTimerId);
    _flushTimerId = null;
  }
  if (_appStateListener) {
    _appStateListener.remove();
    _appStateListener = null;
  }

  // Best-effort unregister background task
  try {
    if (Platform.OS !== "web") {
      const registered = await TaskManager.isTaskRegisteredAsync(BG_TASK_NAME);
      if (registered) {
        await Location.stopLocationUpdatesAsync(BG_TASK_NAME);
      }
    }
  } catch {
    // ignore
  }
}

/**
 * Flush the ping buffer to POST /api/gps/pings.
 * On 409 → stop tracking + clear buffer.  On 413 → split and retry.
 */
export async function flushBufferedPings(): Promise<{ inserted: number; dedup_count: number } | null> {
  const raw = await AsyncStorage.getItem(QUEUE_KEY);
  if (!raw) return null;

  let arr: PingPayload[];
  try {
    arr = JSON.parse(raw);
  } catch {
    await AsyncStorage.removeItem(QUEUE_KEY);
    return null;
  }
  if (!arr.length) return null;

  const headers = await authHeaders();
  let totalInserted = 0;
  let totalDedup = 0;

  // Send in batches of MAX_BATCH
  const remaining = [...arr];

  while (remaining.length > 0) {
    const batch = remaining.splice(0, MAX_BATCH);
    const result = await _sendBatch(batch, headers);

    if (result.stopped) {
      // 409 — clear everything and stop
      await AsyncStorage.removeItem(QUEUE_KEY);
      await stopTracking();
      _onStoppedCb?.();
      return { inserted: totalInserted, dedup_count: totalDedup };
    }
    if (result.ok) {
      totalInserted += result.inserted;
      totalDedup += result.dedup_count;
    } else {
      // Network error — put batch back
      remaining.unshift(...batch);
      break;
    }
  }

  await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(remaining));
  return { inserted: totalInserted, dedup_count: totalDedup };
}

/* ── Internals ─────────────────────────────────────────────────────── */

async function authHeaders(): Promise<Record<string, string>> {
  if (!_cachedToken) _cachedToken = await getAuthToken();
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (_cachedToken) h["Authorization"] = `Bearer ${_cachedToken}`;
  return h;
}

async function enqueue(ping: PingPayload) {
  const raw = await AsyncStorage.getItem(QUEUE_KEY);
  const arr: PingPayload[] = raw ? JSON.parse(raw) : [];
  arr.push(ping);
  await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(arr));

  // Auto-flush at threshold
  if (arr.length >= FLUSH_THRESHOLD) {
    flushBufferedPings().catch(() => {});
  }
}

interface SendResult {
  ok: boolean;
  stopped: boolean;
  inserted: number;
  dedup_count: number;
}

async function _sendBatch(
  batch: PingPayload[],
  headers: Record<string, string>,
): Promise<SendResult> {
  try {
    const res = await fetch(`${BASE}/api/gps/pings`, {
      method: "POST",
      headers,
      body: JSON.stringify({ pings: batch }),
    });

    if (res.status === 409) {
      return { ok: false, stopped: true, inserted: 0, dedup_count: 0 };
    }

    if (res.status === 413) {
      // Split in half and retry
      if (batch.length <= 1)
        return { ok: false, stopped: false, inserted: 0, dedup_count: 0 };

      const mid = Math.ceil(batch.length / 2);
      const a = await _sendBatch(batch.slice(0, mid), headers);
      if (a.stopped) return a;
      const b = await _sendBatch(batch.slice(mid), headers);
      if (b.stopped) return b;

      return {
        ok: a.ok && b.ok,
        stopped: false,
        inserted: a.inserted + b.inserted,
        dedup_count: a.dedup_count + b.dedup_count,
      };
    }

    if (res.ok) {
      const body = await res.json();
      return {
        ok: true,
        stopped: false,
        inserted: body.inserted ?? 0,
        dedup_count: body.dedup_count ?? 0,
      };
    }

    return { ok: false, stopped: false, inserted: 0, dedup_count: 0 };
  } catch {
    return { ok: false, stopped: false, inserted: 0, dedup_count: 0 };
  }
}

function _handleAppState(state: AppStateStatus) {
  if (state === "active" && _tracking) {
    flushBufferedPings().catch(() => {});
  }
}

/* ── Background task definition ────────────────────────────────────── */

TaskManager.defineTask(BG_TASK_NAME, async ({ data, error }: any) => {
  if (error || !data) return;
  const locations: Location.LocationObject[] = (data as any).locations ?? [];
  for (const loc of locations) {
    const ping: PingPayload = {
      lat: loc.coords.latitude,
      lon: loc.coords.longitude,
      accuracy_m: loc.coords.accuracy ?? 0,
      source: "background",
      captured_at: new Date(loc.timestamp).toISOString(),
      heading: loc.coords.heading ?? undefined,
      speed_mps: loc.coords.speed ?? undefined,
    };
    await enqueue(ping);
  }
});
