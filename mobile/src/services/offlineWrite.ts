/**
 * Phase O6 · offlineWrite — unified write wrapper with offline fallback.
 *
 * Wraps any API write call so it:
 *   1. Executes directly when online (returning the server response).
 *   2. Falls back to the O2 sync queue when offline or on network error.
 *   3. Returns `{ data, queued }` so the caller can show optimistic UI.
 *
 * Categories:
 *   - W-A (silent queue): user doesn't notice the enqueue.
 *   - W-B (queue + warning): caller shows a "pending sync" badge/alert.
 *   - W-C (hard block): don't use this helper — keep the direct API call
 *     wrapped in an OfflineGate or manual `isOnlineNow()` check.
 */
import { isOnlineNow } from "@/src/services/sync/netBus";
import { enqueue } from "@/src/services/sync/queue";
import { ApiNetworkError } from "@/src/api";

export type OfflineWriteResult<T> = {
  /** Server response (null when queued offline). */
  data: T | null;
  /** True when the write was enqueued instead of executed. */
  queued: boolean;
};

/**
 * Execute a write call with automatic offline fallback.
 *
 * @param opts.op_type   Sync queue op_type (e.g. "job.update").
 * @param opts.entity_id Entity UUID the write targets.
 * @param opts.endpoint  API path (e.g. "/jobs/123").
 * @param opts.method    HTTP method for queue replay.
 * @param opts.payload   Request body (serializable to JSON).
 * @param opts.onlineFn  The actual API call (only invoked when online).
 */
export async function offlineWrite<T = any>(opts: {
  op_type: string;
  entity_id: string;
  endpoint: string;
  method: "POST" | "PATCH" | "PUT" | "DELETE";
  payload: Record<string, any>;
  onlineFn: () => Promise<T>;
}): Promise<OfflineWriteResult<T>> {
  // Fast path — online.
  if (isOnlineNow()) {
    try {
      const data = await opts.onlineFn();
      return { data, queued: false };
    } catch (e: any) {
      // If network dropped mid-request, fall through to queue.
      if (e instanceof ApiNetworkError || e?.name === "ApiNetworkError") {
        console.log(`[offlineWrite] Network error for ${opts.op_type}/${opts.entity_id} — queueing`);
        await _enqueue(opts);
        return { data: null, queued: true };
      }
      throw e; // Re-throw non-network errors (4xx, 5xx).
    }
  }

  // Offline path.
  console.log(`[offlineWrite] Offline — queueing ${opts.op_type}/${opts.entity_id}`);
  await _enqueue(opts);
  return { data: null, queued: true };
}

async function _enqueue(opts: {
  op_type: string;
  entity_id: string;
  endpoint: string;
  method: "POST" | "PATCH" | "PUT" | "DELETE";
  payload: Record<string, any>;
}): Promise<string> {
  return enqueue({
    op_type: opts.op_type,
    entity_id: opts.entity_id,
    endpoint: opts.endpoint,
    method: opts.method,
    payload: opts.payload,
  });
}

/**
 * Check if a write result was queued and return a user-facing message.
 */
export function queuedMessage(category: "A" | "B"): string {
  if (category === "A") return "Saved offline — will sync automatically.";
  return "Saved offline — will sync when you're back online.";
}
