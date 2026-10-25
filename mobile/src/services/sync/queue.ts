/**
 * Phase O2 · Sync queue engine.
 *
 * Every mobile write goes through this queue — even when online.
 * The queue is SQLite-backed (survives force-quit, memory-pressure
 * kills, and app restarts).
 *
 * Enqueue → dispatch immediately if online, otherwise hold as
 * `pending`.  On reconnect (`network:online` event from netBus),
 * a batched flush runs with exponential backoff.
 *
 * Ordering: FIFO per `entity_id`.  Entities flush in parallel.
 *
 * After `max_retries` (default 10), the entry moves to `failed`
 * (shelved).  The user can retry manually via `retryFailed()`.
 */
import { getSyncDb } from "./db";
import { clientUuid } from "../ids/clientUuid";
import { isOnlineNow, on } from "./netBus";
import { api, ApiNetworkError } from "@/src/api";
import { recordConflict } from "./conflicts";
import { invalidateForEntry } from "../cacheInvalidation";
import { noteSyncError } from "../routeHydrator";

// ─── types ─────────────────────────────────────────────────────────
export type SyncEntry = {
  id: string;
  op_type: string;
  entity_id: string;
  endpoint: string;
  method: "BATCH" | "POST" | "PATCH" | "PUT" | "DELETE";
  payload_json: string;
  status: "pending" | "in_flight" | "done" | "failed";
  attempt_count: number;
  max_retries: number;
  last_attempt_at: string | null;
  last_error: string | null;
  idempotency_key: string;
  created_at: string;
  updated_at: string;
};

export type EnqueueParams = {
  op_type: string;
  entity_id: string;
  endpoint: string;
  method?: "BATCH" | "POST" | "PATCH" | "PUT" | "DELETE";
  payload?: Record<string, any>;
  maxRetries?: number;
};

export type FlushResult = {
  succeeded: number;
  failed: number;
  errors: string[];
};

// ─── pub-sub ───────────────────────────────────────────────────────
type QueueListener = () => void;
const _listeners = new Set<QueueListener>();
let _flushing = false;

function _notify() {
  _listeners.forEach((l) => { try { l(); } catch { /* ignore */ } });
}

export function subscribe(listener: QueueListener): () => void {
  _listeners.add(listener);
  return () => { _listeners.delete(listener); };
}

// ─── auto-flush on reconnect ───────────────────────────────────────
let _autoFlushWired = false;

export function wireAutoFlush(): void {
  if (_autoFlushWired) return;
  _autoFlushWired = true;
  on("network:online", () => {
    // Small delay so the radio stabilizes.
    setTimeout(() => { flush().catch(() => {}); }, 1500);
  });
}

// ─── enqueue ───────────────────────────────────────────────────────
/**
 * Enqueue a mutation.  Returns the client UUID (doubles as
 * idempotency key).  If online, dispatches immediately in the
 * background.
 */
export async function enqueue(params: EnqueueParams): Promise<string> {
  const id = clientUuid();
  const now = new Date().toISOString();
  const idemKey = `${params.op_type}:${id}`;
  const db = await getSyncDb();

  await db.runAsync(
    `INSERT INTO sync_queue
       (id, op_type, entity_id, endpoint, method, payload_json,
        status, attempt_count, max_retries, idempotency_key,
        created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?)`,
    [
      id,
      params.op_type,
      params.entity_id,
      params.endpoint,
      params.method ?? "BATCH",
      JSON.stringify(params.payload ?? {}),
      params.maxRetries ?? 10,
      idemKey,
      now,
      now,
    ],
  );
  _notify();

  // If online, dispatch immediately (fire-and-forget).
  if (isOnlineNow()) {
    flush().catch(() => {});
  }

  return id;
}

// ─── flush ─────────────────────────────────────────────────────────
const BASE_DELAY_MS = 2000;
const MAX_DELAY_MS = 30000;

function backoffMs(attempt: number): number {
  return Math.min(BASE_DELAY_MS * Math.pow(2, attempt), MAX_DELAY_MS);
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Drain all `pending` entries.  FIFO per entity_id; entities in
 * parallel.  Returns summary of what happened.
 */
export async function flush(): Promise<FlushResult> {
  if (_flushing) return { succeeded: 0, failed: 0, errors: [] };
  _flushing = true;
  _notify();

  const result: FlushResult = { succeeded: 0, failed: 0, errors: [] };

  try {
    const db = await getSyncDb();

    // Fetch all pending entries ordered by creation time.
    const pending = await db.getAllAsync<SyncEntry>(
      `SELECT * FROM sync_queue
       WHERE status = 'pending'
       ORDER BY created_at ASC`,
    );

    if (!pending.length) return result;

    // Group by entity_id for FIFO-per-entity ordering.
    const byEntity = new Map<string, SyncEntry[]>();
    for (const entry of pending) {
      const arr = byEntity.get(entry.entity_id) || [];
      arr.push(entry);
      byEntity.set(entry.entity_id, arr);
    }

    // Phase 2 · Max 3 concurrent entity syncs (semaphore pattern).
    // Process each entity's queue sequentially, but limit parallel
    // entity dispatch to MAX_CONCURRENT_ENTITIES at a time.
    const entityQueues = Array.from(byEntity.entries());
    const MAX_CONCURRENT_ENTITIES = 3;
    let idx = 0;

    async function processEntity([_entityId, entries]: [string, SyncEntry[]]) {
      for (const entry of entries) {
        if (!isOnlineNow()) break; // abort if we went offline

        const outcome = await _dispatchOne(entry);
        if (outcome === "done") {
          result.succeeded++;
        } else if (outcome === "shelved") {
          result.failed++;
          result.errors.push(entry.last_error || "Max retries exceeded");
        } else {
          // "retry_later" or "network_error" — stop this entity chain
          break;
        }
        _notify();
      }
    }

    async function worker() {
      while (idx < entityQueues.length) {
        const i = idx++;
        if (i < entityQueues.length) {
          await processEntity(entityQueues[i]);
        }
      }
    }

    const workers = Array.from(
      { length: Math.min(MAX_CONCURRENT_ENTITIES, entityQueues.length) },
      () => worker(),
    );
    await Promise.all(workers);
  } finally {
    _flushing = false;
    _notify();
  }

  return result;
}

async function _dispatchOne(
  entry: SyncEntry,
): Promise<"done" | "shelved" | "retry_later" | "network_error"> {
  const db = await getSyncDb();
  const now = new Date().toISOString();

  // Mark in_flight.
  await db.runAsync(
    `UPDATE sync_queue SET status = 'in_flight', last_attempt_at = ?, updated_at = ?
     WHERE id = ?`,
    [now, now, entry.id],
  );

  try {
    const payload = JSON.parse(entry.payload_json);
    const headers: Record<string, string> = {
      "X-Idempotency-Key": entry.idempotency_key,
    };

    if (entry.method === "BATCH") {
      // Route through /mobile/sync batch endpoint.
      await api.post("/mobile/sync", {
        device_id: await _getDeviceId(),
        operations: [{
          client_op_id: entry.id,
          op_type: entry.op_type,
          entity_id: entry.entity_id,
          payload,
          client_ts: entry.created_at,
        }],
      });
    } else {
      // Direct endpoint dispatch.
      switch (entry.method) {
        case "POST":
          await api.post(entry.endpoint, payload, 30000, headers);
          break;
        case "PATCH":
          await api.patch(entry.endpoint, payload, headers);
          break;
        case "PUT":
          await api.put(entry.endpoint, payload, headers);
          break;
        case "DELETE":
          await api.del(entry.endpoint, headers);
          break;
      }
    }

    // Success — mark done.
    await db.runAsync(
      `UPDATE sync_queue SET status = 'done', updated_at = ? WHERE id = ?`,
      [now, entry.id],
    );
    // Phase O5 · Invalidate read caches affected by this write.
    invalidateForEntry(entry).catch(() => {});
    return "done";
  } catch (e: any) {
    const attempt = entry.attempt_count + 1;
    const errMsg = (e?.message || "Unknown error").slice(0, 500);
    noteSyncError(e); // TD-mobile-sync-tech-not-linked · orphan-tech 409 → amber badge

    if (e instanceof ApiNetworkError) {
      // Network dropped — mark back to pending, don't increment attempt.
      await db.runAsync(
        `UPDATE sync_queue SET status = 'pending', last_error = ?, updated_at = ?
         WHERE id = ?`,
        [errMsg, now, entry.id],
      );
      return "network_error";
    }

    // Phase O3 · Conflict detection: capture 409 responses.
    const statusCode = e?.response?.status ?? e?.statusCode ?? 0;
    if (statusCode === 409) {
      const serverState = e?.response?.data ?? {};
      try {
        await recordConflict({
          queueEntryId: entry.id,
          opType: entry.op_type,
          entityId: entry.entity_id,
          clientPayload: JSON.parse(entry.payload_json),
          serverState,
          statusCode: 409,
        });
      } catch { /* non-fatal — don't block queue drain */ }
    }

    if (attempt >= entry.max_retries) {
      // Shelve — too many failures.
      await db.runAsync(
        `UPDATE sync_queue SET status = 'failed', attempt_count = ?,
           last_error = ?, last_attempt_at = ?, updated_at = ?
         WHERE id = ?`,
        [attempt, errMsg, now, now, entry.id],
      );
      return "shelved";
    }

    // Transient failure — mark pending with incremented attempt.
    await db.runAsync(
      `UPDATE sync_queue SET status = 'pending', attempt_count = ?,
         last_error = ?, last_attempt_at = ?, updated_at = ?
       WHERE id = ?`,
      [attempt, errMsg, now, now, entry.id],
    );

    // Backoff delay before continuing.
    await sleep(backoffMs(attempt));
    return "retry_later";
  }
}

// ─── manual sync now ───────────────────────────────────────────────
/**
 * Bypasses backoff and immediately flushes all pending + failed items.
 * Returns a promise resolving to `{ succeeded, failed, errors }`.
 */
export async function triggerSyncNow(): Promise<FlushResult> {
  // First, re-mark all `failed` entries as `pending` so they get
  // picked up by flush.
  const db = await getSyncDb();
  const now = new Date().toISOString();
  await db.runAsync(
    `UPDATE sync_queue SET status = 'pending', attempt_count = 0,
       last_error = NULL, updated_at = ?
     WHERE status = 'failed'`,
    [now],
  );
  _notify();
  return flush();
}

// ─── retry a single failed entry ───────────────────────────────────
export async function retrySingle(entryId: string): Promise<void> {
  const db = await getSyncDb();
  const now = new Date().toISOString();
  await db.runAsync(
    `UPDATE sync_queue SET status = 'pending', attempt_count = 0,
       last_error = NULL, updated_at = ?
     WHERE id = ? AND status = 'failed'`,
    [now, entryId],
  );
  _notify();
  flush().catch(() => {});
}

// ─── queries ───────────────────────────────────────────────────────
export async function getPending(): Promise<SyncEntry[]> {
  const db = await getSyncDb();
  return db.getAllAsync<SyncEntry>(
    `SELECT * FROM sync_queue WHERE status = 'pending' ORDER BY created_at ASC`,
  );
}

export async function getFailed(): Promise<SyncEntry[]> {
  const db = await getSyncDb();
  return db.getAllAsync<SyncEntry>(
    `SELECT * FROM sync_queue WHERE status = 'failed' ORDER BY created_at ASC`,
  );
}

export async function getAll(): Promise<SyncEntry[]> {
  const db = await getSyncDb();
  return db.getAllAsync<SyncEntry>(
    `SELECT * FROM sync_queue ORDER BY created_at ASC`,
  );
}

export async function clearDone(): Promise<void> {
  const db = await getSyncDb();
  await db.runAsync(`DELETE FROM sync_queue WHERE status = 'done'`);
  _notify();
}

// ─── device id (persisted) ─────────────────────────────────────────
import { getConfig, setConfig } from "./db";

let _deviceIdCache: string | null = null;

async function _getDeviceId(): Promise<string> {
  if (_deviceIdCache) return _deviceIdCache;
  let deviceId = await getConfig("device_id");
  if (!deviceId) {
    deviceId = clientUuid();
    await setConfig("device_id", deviceId);
  }
  _deviceIdCache = deviceId;
  return deviceId;
}

// ─── state accessor ────────────────────────────────────────────────
export function isFlushing(): boolean {
  return _flushing;
}

// ─── test helpers ──────────────────────────────────────────────────
export async function __clearForTests(): Promise<void> {
  const db = await getSyncDb();
  await db.runAsync("DELETE FROM sync_queue");
  _flushing = false;
  _deviceIdCache = null;
  _notify();
}
