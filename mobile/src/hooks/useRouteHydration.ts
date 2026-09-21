/**
 * Phase 1 Offline Read · useRouteHydration hook
 *
 * Provides React state for the hydration engine:
 *   - meta: { totalJobs, cachedJobs, lastSyncedAt, inProgress }
 *   - triggerHydrate(): kick off a manual hydration
 *
 * Automatically triggers hydration on mount if online.
 */
import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { AppState, AppStateStatus } from "react-native";
import { useAuth } from "@/src/auth";
import { isOnlineNow } from "@/src/services/sync/netBus";
import {
  hydrateToday,
  subscribeHydration,
  restoreHydrationMeta,
  type HydrationMeta,
} from "@/src/services/routeHydrator";
import { runP9cPurgeMigration } from "@/src/lib/offline/p9cPurge";

const EMPTY: HydrationMeta = {
  lastSyncedAt: "",
  lastPartialSyncAt: "",
  lastError: "",
  syncStatus: "idle",
  totalJobs: 0,
  cachedJobs: 0,
  inProgress: false,
};

export function useRouteHydration() {
  const { user } = useAuth();
  const userId = user?.id || "";
  const userRole = (user?.role as string) || "";
  const userTechId = user?.technician_id ?? null;
  const [meta, setMeta] = useState<HydrationMeta>(EMPTY);
  const hydratedOnceRef = useRef(false);

  // P9-C: tech scope for cache filtering.
  const techScope = useMemo(() => {
    if (userRole === "technician" || userRole === "tech") {
      return { role: userRole, technicianId: userTechId };
    }
    return undefined;
  }, [userRole, userTechId]);

  // P9-C: one-shot purge migration (runs at most once per install).
  useEffect(() => {
    if (userId) runP9cPurgeMigration(userRole, userTechId, userId);
  }, [userId, userRole, userTechId]);

  // Subscribe to hydration state changes.
  useEffect(() => {
    const unsub = subscribeHydration(setMeta);
    return unsub;
  }, []);

  // Restore persisted meta on cold start.
  useEffect(() => {
    if (userId) restoreHydrationMeta(userId);
  }, [userId]);

  // Auto-hydrate on mount + when app returns to foreground.
  useEffect(() => {
    if (!userId) return;

    const doHydrate = () => {
      if (isOnlineNow() && userId) {
        hydrateToday(userId, techScope);
        hydratedOnceRef.current = true;
      }
    };

    // Hydrate immediately on mount.
    doHydrate();

    // Re-hydrate when app returns to foreground.
    const handleAppState = (state: AppStateStatus) => {
      if (state === "active") doHydrate();
    };
    const sub = AppState.addEventListener("change", handleAppState);
    return () => sub.remove();
  }, [userId, techScope]);

  const triggerHydrate = useCallback(() => {
    if (userId) hydrateToday(userId, techScope);
  }, [userId, techScope]);

  return { meta, triggerHydrate };
}
