import { Platform } from "react-native";
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";

import { api } from "@/src/api";

export const GEOFENCE_TASK = "job-arrival-geofence";
const RADIUS_M = 150;

// Background task: fires when the tech's device enters a job-site region (native builds only).
if (Platform.OS !== "web") {
  TaskManager.defineTask(GEOFENCE_TASK, async ({ data, error }: any) => {
    if (error || !data) return;
    const { eventType, region } = data;
    if (eventType === Location.GeofencingEventType.Enter && region?.identifier?.startsWith("job:")) {
      const jobId = region.identifier.slice(4);
      try {
        await api.post(`/jobs/${jobId}/arrive`, {
          lat: region.latitude, lng: region.longitude,
          site_lat: region.latitude, site_lng: region.longitude,
        });
      } catch {}
    }
  });
}

/**
 * Register geofences for the technician's upcoming (not-yet-timed) jobs so the timer
 * auto-starts on arrival even when the app is backgrounded. Requires a native build + "Always" location.
 * No-ops on web/Expo Go or without background permission.
 */
export async function syncJobGeofences() {
  if (Platform.OS === "web") return;
  try {
    const fg = await Location.getForegroundPermissionsAsync();
    let fgOk = fg.status === "granted";
    if (!fgOk && fg.canAskAgain) fgOk = (await Location.requestForegroundPermissionsAsync()).status === "granted";
    if (!fgOk) return;
    const bg = await Location.getBackgroundPermissionsAsync();
    let bgOk = bg.status === "granted";
    if (!bgOk && bg.canAskAgain) bgOk = (await Location.requestBackgroundPermissionsAsync()).status === "granted";
    if (!bgOk) return;

    const jobs: any[] = await api.get("/jobs");
    const active = jobs
      .filter((j) => j.status !== "completed" && !j.timer_started_at && (j.address || (j.site_lat && j.site_lng)))
      .slice(0, 18); // platform geofence cap
    const regions: any[] = [];
    for (const j of active) {
      let lat = j.site_lat, lng = j.site_lng;
      if ((lat == null || lng == null) && j.address) {
        try { const g = await Location.geocodeAsync(j.address); if (g?.[0]) { lat = g[0].latitude; lng = g[0].longitude; } } catch {}
      }
      if (lat != null && lng != null) {
        regions.push({ identifier: `job:${j.id}`, latitude: lat, longitude: lng, radius: RADIUS_M, notifyOnEnter: true, notifyOnExit: false });
      }
    }
    const running = await Location.hasStartedGeofencingAsync(GEOFENCE_TASK).catch(() => false);
    if (running) await Location.stopGeofencingAsync(GEOFENCE_TASK).catch(() => {});
    if (regions.length) await Location.startGeofencingAsync(GEOFENCE_TASK, regions);
  } catch {
    // silent — geofencing is a best-effort native enhancement
  }
}
