/**
 * Phase 40 · Step 2 · Local write queue for offline checklist mutations.
 *
 * When a tech is offline in a zero-signal backyard, mutations they trigger
 * (autosave patches, photo uploads, submit) are enqueued in AsyncStorage
 * with a stable `X-Idempotency-Key`. On the next online transition — or
 * on demand via `flush()` — every queued entry is replayed against the
 * backend in FIFO order.
 *
 * Backend contract (see `utils_idempotency.py`):
 *   - Same key + same body → cached response, no double-write.
 *   - Same key + different body → `{"error": "idempotency_key_body_mismatch"}`
 *     (client bug — we drop the entry).
 *   - 24h TTL on server side.
 *
 * Retry policy:
 *   - `ApiNetworkError` (from `api.ts`) → keep the entry, abort remainder
 *     (order matters — subsequent entries may depend on this one landing).
 *   - Any other error (4xx/5xx) → mark `lastError`, keep tries incremented,
 *     BUT continue processing the rest of the queue. The tech sees a
 *     "Sync error — retry" pill and can tap-to-retry manually.
 *   - `idempotency_key_body_mismatch` → drop the entry (client sent the
 *     same key with a mutated body — this is unrecoverable and we log it).
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { ApiNetworkError, api } from "@/src/api";

const KEY = "checklist-write-queue-v1";

export type QueueEndpoint =
  | { kind: "patch-service-report"; jobId: string; body: any }
  | { kind: "submit-service-report"; jobId: string }
  | { kind: "upload-photo"; jobId: string; body: { data: string; label?: string } }
  | { kind: "reserve-inventory"; body: any };

export type QueueEntry = {
  id: string;                       // uuid — doubles as X-Idempotency-Key.
  endpoint: QueueEndpoint;
  tries: number;
  lastError?: string;
  enqueuedAt: string;
};

export type QueueState = {
  count: number;
  syncing: boolean;
  lastError?: string;
};

// ────────────────── uuid (RFC-4122 v4, no external deps) ───────────────
function uuid(): string {
  // A pragmatic v4 — good enough for a per-device idempotency key. Not
  // suitable for cryptographic contexts.
  let d = Date.now();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (d + Math.random() * 16) % 16 | 0;
    d = Math.floor(d / 16);
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

// ────────────────── pub-sub for React subscribers ──────────────────────
type Listener = (s: QueueState) => void;
const listeners = new Set<Listener>();
let syncing = false;
let lastError: string | undefined = undefined;

async function currentState(): Promise<QueueState> {
  const q = await getQueue();
  return { count: q.length, syncing, lastError };
}

async function notify() {
  const s = await currentState();
  listeners.forEach((l) => { try { l(s); } catch { /* subscriber threw — ignore */ } });
}

export function subscribe(cb: Listener): () => void {
  listeners.add(cb);
  // Push the current state to the new subscriber immediately.
  currentState().then((s) => { try { cb(s); } catch {} });
  return () => { listeners.delete(cb); };
}

export async function getState(): Promise<QueueState> {
  return currentState();
}

// ────────────────── storage helpers ────────────────────────────────────
async function getQueue(): Promise<QueueEntry[]> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as QueueEntry[]) : [];
  } catch { return []; }
}

async function setQueue(q: QueueEntry[]) {
  try { await AsyncStorage.setItem(KEY, JSON.stringify(q)); }
  catch { /* storage full — non-fatal but the entry is lost */ }
}

// ────────────────── public: enqueue ────────────────────────────────────
/**
 * Enqueue a mutation for later replay. Returns the entry id (also its
 * X-Idempotency-Key) so the caller can associate it with an optimistic
 * UI update if desired.
 */
export async function enqueue(endpoint: QueueEndpoint): Promise<string> {
  const entry: QueueEntry = {
    id: uuid(),
    endpoint,
    tries: 0,
    enqueuedAt: new Date().toISOString(),
  };
  const q = await getQueue();
  q.push(entry);
  await setQueue(q);
  await notify();
  return entry.id;
}

// ────────────────── public: flush ──────────────────────────────────────
async function executeEntry(entry: QueueEntry): Promise<any> {
  const idem: Record<string, string> = { "X-Idempotency-Key": entry.id };
  switch (entry.endpoint.kind) {
    case "patch-service-report":
      return api.patch(
        `/jobs/${entry.endpoint.jobId}/service-report`,
        entry.endpoint.body, idem,
      );
    case "submit-service-report":
      return api.post(
        `/jobs/${entry.endpoint.jobId}/service-report/submit`,
        {}, 30000, idem,
      );
    case "upload-photo":
      return api.post(
        `/jobs/${entry.endpoint.jobId}/photos`,
        entry.endpoint.body, 60000, idem,
      );
    case "reserve-inventory":
      return api.post("/inventory/reserve", entry.endpoint.body, 30000, idem);
  }
}

/**
 * Drain the queue front-to-back. Network errors abort the remainder
 * (preserving ordering); non-network errors are recorded and skipped so
 * one bad entry can't wedge the whole queue forever.
 */
export async function flush(): Promise<{ synced: number; remaining: number }> {
  if (syncing) return { synced: 0, remaining: (await getQueue()).length };
  syncing = true;
  lastError = undefined;
  await notify();
  let synced = 0;
  try {
    // Reload the queue each iteration so a concurrent enqueue is picked up
    // (e.g. a photo upload triggered mid-flush).
    while (true) {
      const q = await getQueue();
      if (!q.length) break;
      const head = q[0];
      try {
        const resp: any = await executeEntry(head);
        // Body-mismatch is a client bug — drop the entry so we don't loop.
        if (resp && typeof resp === "object" && resp.error === "idempotency_key_body_mismatch") {
          const q2 = await getQueue();
          await setQueue(q2.slice(1));
          lastError = "A previous request was replaced by a newer one";
          continue;
        }
        // Success — pop head.
        const q2 = await getQueue();
        await setQueue(q2.slice(1));
        synced++;
        await notify();
      } catch (e: any) {
        if (e instanceof ApiNetworkError) {
          // Network dropped mid-flush — keep entry, abort remainder.
          lastError = undefined;
          break;
        }
        // Server-side error — increment tries, keep entry, skip to next.
        head.tries += 1;
        head.lastError = e?.message || "Sync error";
        lastError = head.lastError;
        const q2 = await getQueue();
        q2[0] = head;
        // Rotate the failing entry to the back so subsequent entries can
        // proceed. If it fails again it'll just keep cycling with
        // `tries` climbing — the UI surfaces the retry chip.
        q2.push(q2.shift()!);
        await setQueue(q2);
        await notify();
        // Bail after one bad rotation to avoid tight-looping on the same
        // set of poison entries.
        break;
      }
    }
  } finally {
    syncing = false;
    await notify();
  }
  const remaining = (await getQueue()).length;
  return { synced, remaining };
}

// ────────────────── public: clear (tests / dev only) ───────────────────
export async function _clearForTests() {
  await AsyncStorage.removeItem(KEY);
  lastError = undefined;
  syncing = false;
  await notify();
}
