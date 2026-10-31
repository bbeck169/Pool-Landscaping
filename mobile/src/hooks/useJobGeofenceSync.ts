/**
 * β-core 2 · P37c arrival-geofence sync lifecycle (moved out of the
 * pre-login boot effect in app/_layout.tsx).
 *
 * - Fleet-role techs only (`isFleetTechRole`); no user / other roles →
 *   `stopJobGeofencesP37c()` and NO `/jobs` call (no pre-login 401).
 * - Runs on login, on `notifyJobsChanged()` (Schedule load), and on
 *   AppState → "active". Calls while a sync is in flight coalesce into one
 *   trailing run.
 */
import { useEffect } from "react";
import { AppState } from "react-native";

import { isFleetTechRole } from "@/src/lib/fleetRoles";
import { syncJobGeofencesP37c, stopJobGeofencesP37c, onJobsChanged } from "@/src/background/jobGeofence";

export function useJobGeofenceSync(user: { id?: string; role?: string | null } | null | undefined): void {
  const eligible = !!user?.id && isFleetTechRole(user?.role);
  const uid = user?.id;
  useEffect(() => {
    if (!eligible) {
      stopJobGeofencesP37c().catch(() => {});
      return;
    }
    let alive = true;
    let inFlight = false;
    let pending = false;
    const run = async () => {
      if (inFlight) { pending = true; return; }
      inFlight = true;
      try { await syncJobGeofencesP37c(); } catch { /* sync never throws to the UI */ }
      inFlight = false;
      if (alive && pending) { pending = false; run(); }
    };
    run();
    const unsubJobs = onJobsChanged(() => { run(); });
    const sub = AppState.addEventListener("change", (s) => { if (s === "active") run(); });
    return () => { alive = false; unsubJobs(); sub.remove(); };
  }, [eligible, uid]);
}
