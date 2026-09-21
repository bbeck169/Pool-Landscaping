/**
 * Phase 32 · SyncManager
 *
 * Orchestrates the offline → online sync lifecycle:
 * - Listens to NetInfo connectivity changes
 * - Exposes `isOnline`, `syncStatus`, `outboxCount` via a React context
 * - Auto-flushes outbox when connectivity is restored
 * - Provides a manual `syncNow()` trigger
 * - Downloads a fresh bundle after a successful flush
 */
import React, { createContext, useContext, useEffect, useState, useCallback, useRef, useMemo } from "react";
import NetInfo, { NetInfoState } from "@react-native-community/netinfo";
import { useAuth } from "@/src/auth";
import {
  downloadBundle,
  flushOutbox,
  getOutboxSize,
  getBundleTimestamp,
} from "./offlineStore";

export type SyncStatus = "idle" | "syncing" | "error" | "offline";

type SyncContextValue = {
  isOnline: boolean;
  syncStatus: SyncStatus;
  outboxCount: number;
  lastBundleTs: string | null;
  syncNow: () => Promise<void>;
  refreshBundle: () => Promise<void>;
};

const SyncContext = createContext<SyncContextValue>({
  isOnline: true,
  syncStatus: "idle",
  outboxCount: 0,
  lastBundleTs: null,
  syncNow: async () => {},
  refreshBundle: async () => {},
});

export function useSyncManager() {
  return useContext(SyncContext);
}

export function SyncManagerProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const [isOnline, setIsOnline] = useState(true);
  const [syncStatus, setSyncStatus] = useState<SyncStatus>("idle");
  const [outboxCount, setOutboxCount] = useState(0);
  const [lastBundleTs, setLastBundleTs] = useState<string | null>(null);
  const wasOffline = useRef(false);

  // P9-C: tech scope for defense-in-depth cache filtering.
  const techScope = useMemo(() => {
    const role = (user?.role as string) || "";
    if (role === "technician" || role === "tech") {
      return { role, technicianId: user?.technician_id ?? null };
    }
    return undefined;
  }, [user?.role, user?.technician_id]);

  // Poll outbox count
  const updateOutboxCount = useCallback(async () => {
    const c = await getOutboxSize();
    setOutboxCount(c);
    return c;
  }, []);

  // Sync now: flush outbox + download fresh bundle
  const syncNow = useCallback(async () => {
    if (!isOnline) return;
    setSyncStatus("syncing");
    try {
      const { synced, failed } = await flushOutbox();
      console.log(`[Sync] Flushed outbox: ${synced} synced, ${failed} failed`);
      await updateOutboxCount();
      // Download fresh bundle after flush
      await downloadBundle(techScope);
      const ts = await getBundleTimestamp();
      setLastBundleTs(ts);
      setSyncStatus(failed > 0 ? "error" : "idle");
    } catch (e) {
      console.warn("[Sync] syncNow failed:", e);
      setSyncStatus("error");
    }
  }, [isOnline, updateOutboxCount, techScope]);

  // Download bundle only
  const refreshBundle = useCallback(async () => {
    if (!isOnline) return;
    setSyncStatus("syncing");
    try {
      await downloadBundle(techScope);
      const ts = await getBundleTimestamp();
      setLastBundleTs(ts);
      setSyncStatus("idle");
    } catch {
      setSyncStatus("error");
    }
  }, [isOnline, techScope]);

  // NetInfo listener
  useEffect(() => {
    const unsub = NetInfo.addEventListener((state: NetInfoState) => {
      const online = !!state.isConnected && !!state.isInternetReachable;
      setIsOnline(online);
      if (!online) {
        setSyncStatus("offline");
        wasOffline.current = true;
      } else if (wasOffline.current) {
        // Coming back online → auto-flush
        wasOffline.current = false;
        syncNow();
      }
    });
    return () => unsub();
  }, [syncNow]);

  // Initial load
  useEffect(() => {
    (async () => {
      const ts = await getBundleTimestamp();
      setLastBundleTs(ts);
      await updateOutboxCount();
    })();
  }, [updateOutboxCount]);

  // Periodic outbox poll (every 30s)
  useEffect(() => {
    const id = setInterval(updateOutboxCount, 30_000);
    return () => clearInterval(id);
  }, [updateOutboxCount]);

  const value = {
    isOnline,
    syncStatus,
    outboxCount,
    lastBundleTs,
    syncNow,
    refreshBundle,
  };

  return React.createElement(SyncContext.Provider, { value }, children);
}
