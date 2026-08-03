/**
 * Phase 20A.3 · Background GPS auto-clock-in.
 *
 * Registers a background TaskManager task that pings
 * `POST /api/workforce/auto-clock-in` from a foreground service (Android)
 * or via `Location.startLocationUpdatesAsync` while the app is backgrounded.
 *
 * Safe in Expo Go: the task registers as a no-op if the native modules
 * aren't available. The user must cut an EAS native build to see it fire
 * in the background.
 *
 * Default-ON for techs: on first visit the pref key doesn't exist so
 * `isAutoClockinEnabled` returns `true` for tech-role callers. The
 * sentinel `_EXPLICIT` key tracks whether the user has ever toggled.
 */
import { Platform } from "react-native";
import { storage } from "@/src/utils/storage";
import { TOKEN_KEY } from "@/src/api";

export const BACKGROUND_AUTOCLOCK_TASK = "BACKGROUND_AUTOCLOCK_TASK";
const AUTO_CLOCKIN_ENABLED_KEY = "auto_clockin_enabled";
const AUTO_CLOCKIN_EXPLICIT_KEY = "auto_clockin_explicit";

let taskDefined = false;

async function _defineTask(): Promise<boolean> {
  if (taskDefined) return true;
  try {
    const TaskManager = await import("expo-task-manager");
    TaskManager.defineTask(BACKGROUND_AUTOCLOCK_TASK, async ({ data, error }: any) => {
      if (error) return;
      const locs = (data as any)?.locations || [];
      if (!locs.length) return;
      const p = locs[0].coords;
      try {
        const base = process.env.EXPO_PUBLIC_BACKEND_URL;
        const token = await storage.secureGet<string>(TOKEN_KEY, "");
        if (!base || !token) return;
        await fetch(`${base}/api/workforce/auto-clock-in`, {
          method: "POST",
          headers: { "Content-Type": "application/json",
                     Authorization: `Bearer ${token}` },
          body: JSON.stringify({
            lat: p.latitude, lng: p.longitude, accuracy: p.accuracy,
          }),
        });
      } catch { /* network / no-op */ }
    });
    taskDefined = true;
    return true;
  } catch (e) {
    // Not available in Expo Go — silently no-op.
    return false;
  }
}

export async function isAutoClockinEnabled(role?: string): Promise<boolean> {
  // Phase 29 · Feb-2026 — Auto Clock-In is MANDATORY for
  // technicians. Even if a tech ever flipped the storage key
  // to ``false`` (via a debug build or a prior UI bug), the
  // getter short-circuits to ``true`` so runtime behaviour
  // stays enforced regardless of stored state.
  if (role === "technician") return true;
  const explicit = await storage.getItem<boolean>(AUTO_CLOCKIN_EXPLICIT_KEY, false);
  if (explicit) {
    // User has toggled at least once — use their saved preference.
    return (await storage.getItem<boolean>(AUTO_CLOCKIN_ENABLED_KEY, false)) === true;
  }
  // First visit: default OFF for non-techs (tech branch handled
  // above via the mandatory short-circuit).
  return false;
}

export async function setAutoClockinEnabled(enabled: boolean, role?: string): Promise<void> {
  // Phase 29 · Feb-2026 — tech-role callers cannot persist a
  // ``false`` value. Any attempt is silently coerced to
  // ``true`` at the persistence layer so a debug-build tamper
  // still ends up with storage in the correct state.
  const safe = role === "technician" ? true : enabled;
  await storage.setItem(AUTO_CLOCKIN_ENABLED_KEY, safe);
  await storage.setItem(AUTO_CLOCKIN_EXPLICIT_KEY, true);
}

export async function startBackgroundAutoClockin(): Promise<{
  started: boolean; reason?: string;
}> {
  const ok = await _defineTask();
  if (!ok) return { started: false, reason: "not_supported_in_expo_go" };
  try {
    const Location = await import("expo-location");
    const fg = await Location.requestForegroundPermissionsAsync();
    if (!fg.granted) return { started: false, reason: "foreground_permission_denied" };
    const bg = await Location.requestBackgroundPermissionsAsync();
    if (!bg.granted) return { started: false, reason: "background_permission_denied" };
    const running = await Location.hasStartedLocationUpdatesAsync(BACKGROUND_AUTOCLOCK_TASK);
    if (running) return { started: true, reason: "already_running" };
    await Location.startLocationUpdatesAsync(BACKGROUND_AUTOCLOCK_TASK, {
      accuracy: Location.Accuracy.Balanced,
      timeInterval: 60_000,
      distanceInterval: 25,
      showsBackgroundLocationIndicator: true,
      foregroundService: Platform.OS === "android" ? {
        notificationTitle: "Pool & Landscaping is tracking arrival",
        notificationBody: "Auto clock-in enabled",
        notificationColor: "#0EA5E9",
      } : undefined,
      pausesUpdatesAutomatically: false,
    });
    return { started: true };
  } catch (e: any) {
    return { started: false, reason: e?.message || "start_failed" };
  }
}

export async function stopBackgroundAutoClockin(): Promise<void> {
  try {
    const Location = await import("expo-location");
    const running = await Location.hasStartedLocationUpdatesAsync(BACKGROUND_AUTOCLOCK_TASK);
    if (running) {
      await Location.stopLocationUpdatesAsync(BACKGROUND_AUTOCLOCK_TASK);
    }
  } catch { /* Expo Go / not started */ }
}
