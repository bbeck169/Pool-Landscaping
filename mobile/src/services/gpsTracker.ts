/**
 * G1 · GPS Tracker Service
 *
 * Wraps expo-location for foreground GPS pings while a technician is clocked in.
 * Buffers pings in AsyncStorage (max 60) and flushes via POST /api/gps/pings.
 * On 409 (disabled or not clocked in) → stops tracking and discards buffer.
 */
import * as Location from "expo-location";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { getAuthToken } from "@/src/api";

const QUEUE_KEY = "gps_ping_queue_g1";
const MAX_BATCH = 60;
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
  accuracy_m?: number;
  heading?: number;
  speed_mps?: number;
  source: string;
  captured_at: string;
}

/* ── Module state ──────────────────────────────────────────────────── */

let _tracking = false;
let _intervalId: ReturnType<typeof setInterval> | null = null;
let _onStoppedCb: (() => void) | null = null;

/* ── Public API ────────────────────────────────────────────────────── */

export function isTracking(): boolean {
  return _tracking;
}

/** Register a callback invoked when tracking stops (e.g. 409 from server). */
export function onTrackingStopped(cb: () => void) {
  _onStoppedCb = cb;
}

/** Fetch tenant GPS settings from backend. */
export async function fetchGpsConfig(): Promise<GpsConfig> {
  try {
    const headers = await authHeaders();
    const res = await fetch(`${BASE}/api/gps/config`, { headers });
    if (!res.ok)
      return {
        enabled: false,
        ping_interval_foreground_s: 60,
        ping_interval_background_s: 300,
      };
    return await res.json();
  } catch {
    return {
      enabled: false,
      ping_interval_foreground_s: 60,
      ping_interval_background_s: 300,
    };
  }
}

/**
 * Start foreground GPS tracking.
 * Returns true if tracking started, false if permission denied or GPS disabled.
 */
export async function startTracking(): Promise<boolean> {
  if (_tracking) return true;

  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== "granted") return false;

  const config = await fetchGpsConfig();
  if (!config.enabled) return false;

  _tracking = true;
  const intervalMs = Math.max((config.ping_interval_foreground_s || 60) * 1000, 5000);

  // Capture first ping immediately
  capturePing();

  _intervalId = setInterval(capturePing, intervalMs);
  return true;
}

/** Stop tracking and clear interval. Does NOT flush — call flushPings() separately. */
export function stopTracking() {
  _tracking = false;
  if (_intervalId) {
    clearInterval(_intervalId);
    _intervalId = null;
  }
}

/**
 * Flush buffered pings to POST /api/gps/pings.
 * Returns count flushed. On 409 → stops tracking, discards buffer, invokes callback.
 */
export async function flushPings(): Promise<{ flushed: number; stopped: boolean }> {
  const raw = await AsyncStorage.getItem(QUEUE_KEY);
  if (!raw) return { flushed: 0, stopped: false };

  let arr: PingPayload[];
  try {
    arr = JSON.parse(raw);
  } catch {
    await AsyncStorage.removeItem(QUEUE_KEY);
    return { flushed: 0, stopped: false };
  }
  if (!arr.length) return { flushed: 0, stopped: false };

  const headers = await authHeaders();
  let stopped = false;
  let totalFlushed = 0;
  const remaining = [...arr];

  while (remaining.length > 0) {
    const batch = remaining.splice(0, MAX_BATCH);
    try {
      const res = await fetch(`${BASE}/api/gps/pings`, {
        method: "POST",
        headers,
        body: JSON.stringify({ pings: batch }),
      });

      if (res.status === 409) {
        stopped = true;
        remaining.length = 0;
        break;
      }
      if (res.ok) {
        totalFlushed += batch.length;
      } else {
        remaining.unshift(...batch);
        break;
      }
    } catch {
      remaining.unshift(...batch);
      break;
    }
  }

  if (stopped) {
    await AsyncStorage.removeItem(QUEUE_KEY);
    stopTracking();
    _onStoppedCb?.();
  } else {
    await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(remaining));
  }

  return { flushed: totalFlushed, stopped };
}

/** Clear the ping buffer without sending. */
export async function clearBuffer(): Promise<void> {
  await AsyncStorage.removeItem(QUEUE_KEY);
}

/** Return the number of buffered pings. */
export async function bufferCount(): Promise<number> {
  const raw = await AsyncStorage.getItem(QUEUE_KEY);
  if (!raw) return 0;
  try {
    return JSON.parse(raw).length;
  } catch {
    return 0;
  }
}

/* ── Internals ─────────────────────────────────────────────────────── */

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getAuthToken();
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

async function enqueue(ping: PingPayload) {
  const raw = await AsyncStorage.getItem(QUEUE_KEY);
  const arr: PingPayload[] = raw ? JSON.parse(raw) : [];
  arr.push(ping);
  await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(arr));

  if (arr.length >= MAX_BATCH) {
    flushPings().catch(() => {});
  }
}

async function capturePing() {
  try {
    const pos = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    });
    const ping: PingPayload = {
      lat: pos.coords.latitude,
      lon: pos.coords.longitude,
      accuracy_m: pos.coords.accuracy ?? undefined,
      heading: pos.coords.heading ?? undefined,
      speed_mps: pos.coords.speed ?? undefined,
      source: "foreground",
      captured_at: new Date().toISOString(),
    };
    await enqueue(ping);
  } catch {
    // GPS unavailable this tick — ignore silently
  }
}
