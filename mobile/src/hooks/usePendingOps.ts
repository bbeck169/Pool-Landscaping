/**
 * Phase 2 · usePendingOps — per-entity pending sync indicator hook.
 *
 * Returns the count of pending + in_flight sync queue entries
 * for a given entity_id. Re-renders on every queue mutation.
 *
 * Usage:
 *   const pendingCount = usePendingOps(jobId);
 *   {pendingCount > 0 && <PendingSyncPill count={pendingCount} />}
 */
import { useEffect, useState, useCallback } from "react";
import { getSyncDb } from "@/src/services/sync/db";
import { subscribe as queueSubscribe } from "@/src/services/sync/queue";

/**
 * Returns the number of pending + in_flight sync queue entries
 * for the given entity_id.
 */
export function usePendingOps(entityId: string | undefined): number {
  const [count, setCount] = useState(0);

  const refresh = useCallback(async () => {
    if (!entityId) { setCount(0); return; }
    try {
      const db = await getSyncDb();
      const row = await db.getFirstAsync<{ cnt: number }>(
        `SELECT COUNT(*) as cnt FROM sync_queue
         WHERE entity_id = ? AND status IN ('pending', 'in_flight')`,
        [entityId],
      );
      setCount(row?.cnt ?? 0);
    } catch {
      setCount(0);
    }
  }, [entityId]);

  useEffect(() => {
    refresh();
    const unsub = queueSubscribe(refresh);
    return unsub;
  }, [refresh]);

  return count;
}

/**
 * Returns a Set of entity_ids that have pending/in_flight ops.
 * Useful for batch-checking multiple items (e.g. schedule job list).
 */
export function usePendingEntityIds(): Set<string> {
  const [ids, setIds] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const db = await getSyncDb();
      const rows = await db.getAllAsync<{ entity_id: string }>(
        `SELECT DISTINCT entity_id FROM sync_queue
         WHERE status IN ('pending', 'in_flight')`,
      );
      setIds(new Set(rows.map((r) => r.entity_id)));
    } catch {
      setIds(new Set());
    }
  }, []);

  useEffect(() => {
    refresh();
    const unsub = queueSubscribe(refresh);
    return unsub;
  }, [refresh]);

  return ids;
}

export default usePendingOps;
