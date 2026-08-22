// Feb-2026 · P37c — Enhanced geofence listener with the P37 gates.
//
// Wraps and supersedes the pre-P37 ``mobile/src/geofence.ts`` behavior:
//   * Region radius sourced from ``GET /api/settings/gps-auto-start``
//     (``arrival_radius_meters``); falls back to 75m on fetch failure.
//   * 20-region cap (iOS ceiling); silent truncate sorted by soonest
//     ``scheduled_start`` / ``scheduled_date``.
//   * Skips completed jobs + jobs missing coords (canonical
//     ``latitude/longitude`` OR legacy ``site_lat/lng``).
//   * On entry — consent check via ``GET /tech-gps-consent/me`` (session
//     cache) BEFORE calling ``/arrive``. No consent → toast + skip.
//   * Successful ``/arrive`` fires a local push undo banner.
//   * Silent failure on every network / permission / task error.
//
// This module is IMPORT-SAFE on web/Expo Go — every native call is
// wrapped in a Platform.OS !== "web" guard + try/catch.
import { Platform } from "react-native";
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import * as Notifications from "expo-notifications";

import { api } from "@/src/api";


export const JOB_GEOFENCE_TASK = "p37c-job-arrival-geofence";
const FALLBACK_RADIUS_M = 75;
const REGION_CAP = 20;
const UNDO_CATEGORY = "gps_auto_start_undo";


// ── Session-scoped consent cache ─────────────────────────────────
let _consentCached: { active: boolean; fetchedAt: number } | null = null;
const _CONSENT_TTL_MS = 5 * 60 * 1000;

async function _getConsentCached(): Promise<boolean> {
  const now = Date.now();
  if (_consentCached && (now - _consentCached.fetchedAt) < _CONSENT_TTL_MS) {
    return _consentCached.active;
  }
  try {
    const res: any = await api.get("/tech-gps-consent/me");
    const active = !!res?.active;
    _consentCached = { active, fetchedAt: now };
    return active;
  } catch {
    return false;
  }
}

export function invalidateConsentCache(): void { _consentCached = null; }


// ── Background task ─────────────────────────────────────────────
if (Platform.OS !== "web") {
  try {
    TaskManager.defineTask(JOB_GEOFENCE_TASK, async ({ data, error }: any) => {
      if (error || !data) return;
      const { eventType, region } = data;
      if (eventType !== Location.GeofencingEventType.Enter) return;
      if (!region?.identifier?.startsWith?.("job:")) return;
      const jobId = region.identifier.slice(4);

      // P37c consent gate — bail silently if the tech has not granted.
      const consentActive = await _getConsentCached();
      if (!consentActive) return;

      try {
        const res: any = await api.post(`/jobs/${jobId}/arrive`, {
          lat: region.latitude,
          lng: region.longitude,
          site_lat: region.latitude,
          site_lng: region.longitude,
        });
        if (res?.started === true && res?.already_running !== true) {
          await _fireUndoBanner(jobId);
        }
      } catch { /* silent — never surface arrive failures to the tech */ }
    });
  } catch { /* task already defined on hot reload */ }
}


// ── Local push undo banner ──────────────────────────────────────
async function _fireUndoBanner(jobId: string): Promise<void> {
  try {
    const perm = await Notifications.getPermissionsAsync();
    if (perm.status !== "granted") return;  // toast fallback handled by caller
    // Register the category action once per app session.
    try {
      await Notifications.setNotificationCategoryAsync(UNDO_CATEGORY, [
        { identifier: "UNDO",
          buttonTitle: "Undo",
          options: { opensAppToForeground: true } as any },
      ]);
    } catch { /* iOS may reject re-registration; safe to ignore */ }
    await Notifications.scheduleNotificationAsync({
      content: {
        title: "Job timer started",
        body: "Tap Undo within 30s to cancel.",
        categoryIdentifier: UNDO_CATEGORY,
        data: { job_id: jobId, action: "gps_auto_start_undo" },
      },
      trigger: null,  // immediate
    });
  } catch { /* silent */ }
}


// ── Region sync ─────────────────────────────────────────────────
async function _fetchRadius(): Promise<number> {
  try {
    const res: any = await api.get("/settings/gps-auto-start");
    const r = Number(res?.arrival_radius_meters);
    return Number.isFinite(r) && r >= 10 ? r : FALLBACK_RADIUS_M;
  } catch { return FALLBACK_RADIUS_M; }
}

function _jobCoords(j: any): { lat: number | null; lng: number | null } {
  // Prefer P37a-canonical fields; fall back to legacy `site_lat/lng`.
  const lat = j?.latitude ?? j?.site_lat ?? null;
  const lng = j?.longitude ?? j?.site_lng ?? null;
  if (typeof lat === "number" && typeof lng === "number") return { lat, lng };
  return { lat: null, lng: null };
}

function _sortKey(j: any): string {
  return String(j?.scheduled_start || j?.scheduled_date || j?.created_at || "");
}

export type SyncResult = {
  registered: number;
  truncated: number;
  radius: number;
  skipped_no_coords: number;
  skipped_completed: number;
};


export async function syncJobGeofencesP37c(): Promise<SyncResult> {
  const empty: SyncResult = { registered: 0, truncated: 0, radius: 0,
                                skipped_no_coords: 0, skipped_completed: 0 };
  if (Platform.OS === "web") return empty;
  try {
    const fg = await Location.getForegroundPermissionsAsync();
    if (fg.status !== "granted") return empty;
    const bg = await Location.getBackgroundPermissionsAsync();
    if (bg.status !== "granted") return empty;

    const [jobsRaw, radius] = await Promise.all([
      api.get("/jobs") as Promise<any>,
      _fetchRadius(),
    ]);
    const jobs: any[] = Array.isArray(jobsRaw) ? jobsRaw : (jobsRaw?.items || []);

    let skippedCompleted = 0;
    let skippedNoCoords = 0;
    const candidates: any[] = [];
    for (const j of jobs) {
      if (j?.status === "completed") { skippedCompleted++; continue; }
      const { lat, lng } = _jobCoords(j);
      if (lat == null || lng == null) { skippedNoCoords++; continue; }
      if (j?.timer_started_at) continue;  // already running
      candidates.push({ ...j, __lat: lat, __lng: lng });
    }
    candidates.sort((a, b) => _sortKey(a).localeCompare(_sortKey(b)));
    const capped = candidates.slice(0, REGION_CAP);
    const truncated = Math.max(0, candidates.length - capped.length);

    const regions = capped.map((j) => ({
      identifier: `job:${j.id}`,
      latitude: j.__lat,
      longitude: j.__lng,
      radius,
      notifyOnEnter: true,
      notifyOnExit: false,
    }));

    const running = await Location.hasStartedGeofencingAsync(JOB_GEOFENCE_TASK)
      .catch(() => false);
    if (running) {
      await Location.stopGeofencingAsync(JOB_GEOFENCE_TASK).catch(() => {});
    }
    if (regions.length > 0) {
      await Location.startGeofencingAsync(JOB_GEOFENCE_TASK, regions);
    }
    return { registered: regions.length, truncated, radius,
              skipped_no_coords: skippedNoCoords,
              skipped_completed: skippedCompleted };
  } catch {
    return empty;
  }
}


// Helpers for tests + callers.
export const _testables = {
  _jobCoords, _sortKey, JOB_GEOFENCE_TASK, REGION_CAP, FALLBACK_RADIUS_M,
  _getConsentCached, _fireUndoBanner, _fetchRadius,
};
