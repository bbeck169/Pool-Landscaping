/**
 * Phase 1 Offline Read · useRouteHydration hook
 *
 * Provides React state for the hydration engine:
 *   - meta: { totalJobs, cachedJobs, lastSyncedAt, inProgress }
 *   - triggerHydrate(): kick off a manual hydration
 *
 * Automatically triggers hydration on mount if online.
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { AppState, AppStateStatus } from "react-native";
import { useAuth } from "@/src/auth";
import { isOnlineNow } from "@/src/services/sync/netBus";
import {
  hydrateToday,
  subscribeHydration,
  restoreHydrationMeta,
  type HydrationMeta,
} from "@/src/services/routeHydrator";

const EMPTY: HydrationMeta = {
  lastSyncedAt: "",
  totalJobs: 0,
  cachedJobs: 0,
  inProgress: false,
};

export function useRouteHydration() {
  const { user } = useAuth();
  const userId = user?.id || "";
  const [meta, setMeta] = useState<HydrationMeta>(EMPTY);
  const hydratedOnceRef = useRef(false);

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
        hydrateToday(userId);
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
  }, [userId]);

  const triggerHydrate = useCallback(() => {
    if (userId) hydrateToday(userId);
  }, [userId]);

  return { meta, triggerHydrate };
}
