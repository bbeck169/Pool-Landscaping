/**
 * FLEET-B · Location Emitter Service
 *
 * Foreground-only GPS emission for technicians.
 * - Cadence: 15s (active) / 60s (idle when screen locked but app still "active")
 * - Battery-aware: <20% degrades to 60s active / 300s idle
 * - Stops completely when app goes to background (AppState !== "active")
 * - Error handling: 403 → stop, 400 → resync time, 429 → skip, network → retry once 5s
 *
 * Does NOT use background location tasks. Foreground only.
 */
import * as Location from "expo-location";
import * as Battery from "expo-battery";
import { AppState, type AppStateStatus } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api, ApiError, ApiNetworkError } from "@/src/api";

/* ── Constants ─────────────────────────────────────────────────────── */

const ACTIVE_INTERVAL_MS = 15_000;        // 15s normal
const IDLE_INTERVAL_MS = 60_000;          // 60s when idle/battery-saving
const LOW_BATT_ACTIVE_MS = 60_000;        // 60s when battery <20%
const LOW_BATT_IDLE_MS = 300_000;         // 5min when battery <20% & idle
const LOW_BATTERY_THRESHOLD = 0.20;       // 20%
const RETRY_BACKOFF_MS = 5_000;           // 5s retry on network failure
const PAUSE_KEY = "fleet_pause_shift";    // AsyncStorage key for pause toggle

/* ── Types ─────────────────────────────────────────────────────────── */

export type EmitterStatus = "active" | "idle" | "paused" | "stopped" | "not_in_fleet" | "no_permission";

type StatusListener = (status: EmitterStatus) => void;

/* ── Module State ──────────────────────────────────────────────────── */

let _running = false;
let _intervalId: ReturnType<typeof setInterval> | null = null;
let _appStateListener: { remove(): void } | null = null;
let _batteryListener: Battery.Subscription | null = null;
let _netListener: (() => void) | null = null;
let _status: EmitterStatus = "stopped";
let _lowBattery = false;
let _appActive = true;
let _statusListeners: StatusListener[] = [];
let _lastPingAt = 0;
let _consecutiveNetworkErrors = 0;

/* ── Public API ────────────────────────────────────────────────────── */

export function getEmitterStatus(): EmitterStatus {
  return _status;
}

export function onStatusChange(cb: StatusListener): () => void {
  _statusListeners.push(cb);
  return () => {
    _statusListeners = _statusListeners.filter((l) => l !== cb);
  };
}

function _setStatus(s: EmitterStatus) {
  if (_status === s) return;
  _status = s;
  _statusListeners.forEach((cb) => {
    try { cb(s); } catch { /* swallow */ }
  });
}

/**
 * Start the fleet location emitter.
 * Returns true if started, false if cannot start (no permission, paused, etc.)
 */
export async function startEmitter(): Promise<boolean> {
  if (_running) return true;

  // Check pause toggle
  const paused = await isPaused();
  if (paused) {
    _setStatus("paused");
    return false;
  }

  // Request foreground location permission
  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== "granted") {
    _setStatus("no_permission");
    return false;
  }

  // Probe battery state
  try {
    const battLevel = await Battery.getBatteryLevelAsync();
    _lowBattery = battLevel >= 0 && battLevel < LOW_BATTERY_THRESHOLD;
  } catch {
    _lowBattery = false;
  }

  _running = true;
  _appActive = AppState.currentState === "active";
  _consecutiveNetworkErrors = 0;
  _setStatus(_appActive ? "active" : "idle");

  // Start the interval
  _scheduleInterval();

  // AppState listener — stop interval on background, restart on foreground
  _appStateListener = AppState.addEventListener("change", _handleAppState);

  // Battery listener
  try {
    _batteryListener = Battery.addBatteryLevelListener(({ batteryLevel }) => {
      const wasLow = _lowBattery;
      _lowBattery = batteryLevel >= 0 && batteryLevel < LOW_BATTERY_THRESHOLD;
      if (wasLow !== _lowBattery && _running) {
        // Reschedule interval with new cadence
        _scheduleInterval();
      }
    });
  } catch {
    // expo-battery not available on web
  }

  // Fire first ping immediately
  _doPing();

  return true;
}

/** Stop the emitter completely. */
export function stopEmitter(): void {
  _running = false;
  _clearInterval();
  if (_appStateListener) {
    _appStateListener.remove();
    _appStateListener = null;
  }
  if (_batteryListener) {
    _batteryListener.remove();
    _batteryListener = null;
  }
  if (_netListener) {
    _netListener();
    _netListener = null;
  }
  _setStatus("stopped");
}

/** Check if emitter is running */
export function isEmitterRunning(): boolean {
  return _running;
}

/** Pause / resume toggle (persisted in AsyncStorage) */
export async function setPaused(paused: boolean): Promise<void> {
  if (paused) {
    await AsyncStorage.setItem(PAUSE_KEY, "1");
    stopEmitter();
    _setStatus("paused");
  } else {
    await AsyncStorage.removeItem(PAUSE_KEY);
    // Caller should call startEmitter() after this
  }
}

export async function isPaused(): Promise<boolean> {
  const val = await AsyncStorage.getItem(PAUSE_KEY);
  return val === "1";
}

/* ── Internals ─────────────────────────────────────────────────────── */

function _getIntervalMs(): number {
  if (_lowBattery) {
    return _appActive ? LOW_BATT_ACTIVE_MS : LOW_BATT_IDLE_MS;
  }
  return _appActive ? ACTIVE_INTERVAL_MS : IDLE_INTERVAL_MS;
}

function _clearInterval() {
  if (_intervalId) {
    clearInterval(_intervalId);
    _intervalId = null;
  }
}

function _scheduleInterval() {
  _clearInterval();
  if (!_running) return;
  const ms = _getIntervalMs();
  _intervalId = setInterval(() => {
    if (_running && _appActive) {
      _doPing();
    }
  }, ms);
}

function _handleAppState(state: AppStateStatus) {
  const wasActive = _appActive;
  _appActive = state === "active";

  if (!_running) return;

  if (_appActive && !wasActive) {
    // Came to foreground — restart interval and fire immediate ping
    _setStatus(_lowBattery ? "idle" : "active");
    _scheduleInterval();
    _doPing();
  } else if (!_appActive && wasActive) {
    // Went to background — stop interval (foreground-only)
    _clearInterval();
    _setStatus("idle");
  }
}

// TD-fleet-pings-not-reaching-be (Lane A, D4) · dev-only visibility for the
// _doPing short-circuit paths. Gated by __DEV__ so production stays silent.
function _devWarn(msg: string, err?: unknown) {
  if (__DEV__) console.warn(`[fleet.emitter] ${msg}`, err ?? "");
}

async function _doPing() {
  if (!_running || !_appActive) return;

  // Rate limit: don't ping faster than 5s
  const now = Date.now();
  if (now - _lastPingAt < 5000) {
    _devWarn("ping skipped: rate limit (<5s since last ping)");
    return;
  }

  try {
    // Lane A (D1/D3): request a fresh Balanced (~100 m) fix. The previous
    // getLastKnownPositionAsync() is null on web and on cold-start native,
    // which silently skipped every ping (0 tech_locations rows on preview).
    let loc: Location.LocationObject | null = null;
    try {
      loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    } catch (err) {
      _devWarn("ping skipped: getCurrentPositionAsync failed", err);
      return;
    }
    if (!loc) {
      _devWarn("ping skipped: no position available");
      return;
    }

    const battLevel = await Battery.getBatteryLevelAsync().catch((err) => {
      _devWarn("battery level unavailable; ping sent without battery_pct", err);
      return -1;
    });

    const body: Record<string, any> = {
      lat: loc.coords.latitude,
      lng: loc.coords.longitude,
      accuracy_m: loc.coords.accuracy ?? undefined,
      speed_kmh: loc.coords.speed != null ? Math.max(0, loc.coords.speed * 3.6) : undefined,
      heading_deg: loc.coords.heading ?? undefined,
      battery_pct: battLevel >= 0 ? Math.round(battLevel * 100) : undefined,
      device_time: new Date().toISOString(),
    };

    _lastPingAt = Date.now();

    await api.post("/fleet/ping", body);
    _consecutiveNetworkErrors = 0;
    if (_status !== "active" && _running && _appActive) {
      _setStatus("active");
    }
  } catch (e: any) {
    if (e instanceof ApiError) {
      if (e.status === 403) {
        // Not in fleet — stop emitter
        stopEmitter();
        _setStatus("not_in_fleet");
        return;
      }
      if (e.status === 400) {
        // Stale ping — server time skew. Just skip this one.
        // The next ping will have a fresh device_time.
        return;
      }
      if (e.status === 429) {
        // Rate limited — just skip
        return;
      }
    }
    if (e instanceof ApiNetworkError) {
      _consecutiveNetworkErrors++;
      if (_consecutiveNetworkErrors <= 1) {
        // Retry once after 5s backoff
        setTimeout(() => {
          if (_running && _appActive) _doPing();
        }, RETRY_BACKOFF_MS);
      }
      // Otherwise just skip until next interval
    }
  }
}
