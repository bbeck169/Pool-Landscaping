/**
 * Phase O2 · Reactive sync-status API.
 *
 * Provides `useSyncStatus()` — a React hook that returns the current
 * sync state and re-renders on every queue mutation / network change.
 *
 * Also exports `getSyncStatus()` for non-React consumers.
 */
import { useEffect, useState } from "react";
import { getSyncDb } from "./db";
import { getConfig } from "./db";
import { subscribe as queueSubscribe, isFlushing } from "./queue";
import { isOnlineNow, on } from "./netBus";

// ─── types ─────────────────────────────────────────────────────────
export type SyncStatus = {
  pending_count: number;
  in_flight_count: number;
  failed_count: number;
  done_count: number;
  last_sync_at: string | null;
  is_online: boolean;
  is_flushing: boolean;
};

const EMPTY: SyncStatus = {
  pending_count: 0,
  in_flight_count: 0,
  failed_count: 0,
  done_count: 0,
  last_sync_at: null,
  is_online: true,
  is_flushing: false,
};

// ─── status computation ────────────────────────────────────────────
export async function getSyncStatus(): Promise<SyncStatus> {
  try {
    const db = await getSyncDb();
    const rows = await db.getAllAsync<{ status: string; cnt: number }>(
      `SELECT status, COUNT(*) as cnt FROM sync_queue GROUP BY status`,
    );
    const counts: Record<string, number> = {};
    for (const r of rows) counts[r.status] = r.cnt;

    const lastSync = await getConfig("last_sync_at");

    return {
      pending_count: counts["pending"] ?? 0,
      in_flight_count: counts["in_flight"] ?? 0,
      failed_count: counts["failed"] ?? 0,
      done_count: counts["done"] ?? 0,
      last_sync_at: lastSync,
      is_online: isOnlineNow(),
      is_flushing: isFlushing(),
    };
  } catch {
    return { ...EMPTY, is_online: isOnlineNow() };
  }
}

// ─── React hook ────────────────────────────────────────────────────
export function useSyncStatus(): SyncStatus {
  const [status, setStatus] = useState<SyncStatus>({
    ...EMPTY,
    is_online: isOnlineNow(),
  });

  useEffect(() => {
    let mounted = true;

    const refresh = () => {
      getSyncStatus().then((s) => { if (mounted) setStatus(s); }).catch(() => {});
    };

    // Initial fetch.
    refresh();

    // Subscribe to queue mutations.
    const unsubQueue = queueSubscribe(refresh);
    // Subscribe to network changes.
    const unsubOnline = on("network:online", refresh);
    const unsubOffline = on("network:offline", refresh);

    return () => {
      mounted = false;
      unsubQueue();
      unsubOnline();
      unsubOffline();
    };
  }, []);

  return status;
}
