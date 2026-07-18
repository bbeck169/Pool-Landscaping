/**
 * Templates Library — Phase 3 · Offline Draft Support
 *
 * Persists template-instance edits to AsyncStorage BEFORE each PATCH,
 * queues failed PATCHes for replay on reconnect / foreground, and
 * merges local-over-server on load when the local snapshot is newer.
 *
 * Storage primitive: raw AsyncStorage (matches writeQueue.ts and offline.ts
 * patterns — the typed `storage` singleton is limited to scalar values).
 *
 * Keys:
 *   template_draft:{id}       → { instance_id, title, values, dirty_since }
 *   template_drafts_pending   → [ { instance_id, title, values, ts } ]  (FIFO)
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import NetInfo from "@react-native-community/netinfo";
import { AppState, AppStateStatus } from "react-native";
import { api, ApiNetworkError } from "@/src/api";

// ─── Types ──────────────────────────────────────────────────────────
export type LocalSnapshot = {
  instance_id: string;
  title: string;
  values: Record<string, any>;
  dirty_since: string; // ISO-8601
};

export type PendingEntry = {
  instance_id: string;
  title: string;
  values: Record<string, any>;
  ts: string; // ISO-8601 (enqueue time)
};

// ─── Key helpers ────────────────────────────────────────────────────
const snapshotKey = (id: string) => `template_draft:${id}`;
const PENDING_KEY = "template_drafts_pending";

// ─── Snapshot CRUD ──────────────────────────────────────────────────
export async function writeSnapshot(snap: LocalSnapshot): Promise<void> {
  try {
    await AsyncStorage.setItem(snapshotKey(snap.instance_id), JSON.stringify(snap));
  } catch {
    /* Storage full — non-fatal */
  }
}

export async function readSnapshot(instanceId: string): Promise<LocalSnapshot | null> {
  try {
    const raw = await AsyncStorage.getItem(snapshotKey(instanceId));
    return raw ? (JSON.parse(raw) as LocalSnapshot) : null;
  } catch {
    return null;
  }
}

export async function clearSnapshot(instanceId: string): Promise<void> {
  try {
    await AsyncStorage.removeItem(snapshotKey(instanceId));
  } catch {
    /* non-fatal */
  }
}

// ─── Pending queue CRUD ─────────────────────────────────────────────
export async function getPendingQueue(): Promise<PendingEntry[]> {
  try {
    const raw = await AsyncStorage.getItem(PENDING_KEY);
    return raw ? (JSON.parse(raw) as PendingEntry[]) : [];
  } catch {
    return [];
  }
}

async function setPendingQueue(q: PendingEntry[]): Promise<void> {
  try {
    await AsyncStorage.setItem(PENDING_KEY, JSON.stringify(q));
  } catch {
    /* non-fatal */
  }
}

/** Enqueue a failed-to-sync draft edit. Replaces any earlier entry for the same instance. */
export async function enqueuePending(entry: PendingEntry): Promise<void> {
  const q = await getPendingQueue();
  const idx = q.findIndex((e) => e.instance_id === entry.instance_id);
  if (idx >= 0) {
    // Replace in-place (latest values supersede — still FIFO by first appearance)
    q[idx] = entry;
  } else {
    q.push(entry);
  }
  await setPendingQueue(q);
}

export async function removePending(instanceId: string): Promise<void> {
  const q = await getPendingQueue();
  await setPendingQueue(q.filter((e) => e.instance_id !== instanceId));
}

export async function hasPendingForInstance(instanceId: string): Promise<boolean> {
  const q = await getPendingQueue();
  return q.some((e) => e.instance_id === instanceId);
}

export async function pendingCount(): Promise<number> {
  return (await getPendingQueue()).length;
}

// ─── Flush (replay) pending queue in FIFO order ─────────────────────
let _flushing = false;

export async function flushPendingTemplateDrafts(): Promise<{
  synced: number;
  remaining: number;
}> {
  if (_flushing) return { synced: 0, remaining: (await getPendingQueue()).length };
  _flushing = true;
  let synced = 0;
  try {
    const q = await getPendingQueue();
    const remaining: PendingEntry[] = [];
    for (const entry of q) {
      try {
        await api.patch(`/templates/instances/${entry.instance_id}`, {
          title: entry.title,
          values: entry.values,
        });
        // On success, also clear the local snapshot's dirty state
        await clearSnapshot(entry.instance_id);
        synced++;
        console.log(`[offlineTemplateDrafts] synced ${entry.instance_id}`);
      } catch (e: any) {
        if (e instanceof ApiNetworkError) {
          // Still offline — keep this + all remaining entries
          remaining.push(entry, ...q.slice(q.indexOf(entry) + 1).filter((x) => !remaining.includes(x)));
          break;
        }
        // Server error (4xx/5xx) — drop entry to avoid poisoning queue
        console.warn(`[offlineTemplateDrafts] dropping ${entry.instance_id}: ${e.message}`);
      }
    }
    // Rebuild queue with only the entries that weren't synced
    if (remaining.length > 0) {
      await setPendingQueue(remaining);
    } else {
      // Everything synced or dropped — reread to catch concurrent enqueues
      const current = await getPendingQueue();
      const syncedIds = new Set(q.filter((_, i) => i < q.length - remaining.length).map((e) => e.instance_id));
      await setPendingQueue(current.filter((e) => !syncedIds.has(e.instance_id)));
    }
  } finally {
    _flushing = false;
  }
  const finalRemaining = (await getPendingQueue()).length;
  return { synced, remaining: finalRemaining };
}

// ─── Merge logic (local wins if newer) ──────────────────────────────
/**
 * Called after loading the server instance. If a local snapshot exists
 * and its `dirty_since` is after the server's `updated_at`, returns the
 * merged instance (local values + title overriding server). Otherwise null.
 */
export async function mergeLocalOverServer(
  serverInstance: any,
): Promise<{ merged: any; hadLocalEdits: boolean }> {
  const snap = await readSnapshot(serverInstance.id);
  if (!snap || !snap.dirty_since) {
    return { merged: serverInstance, hadLocalEdits: false };
  }
  const serverUpdated = new Date(serverInstance.updated_at || 0).getTime();
  const localDirty = new Date(snap.dirty_since).getTime();
  if (localDirty > serverUpdated) {
    // Local is newer — merge values (last-write-wins per field)
    const merged = {
      ...serverInstance,
      title: snap.title || serverInstance.title,
      values: { ...(serverInstance.values || {}), ...(snap.values || {}) },
    };
    console.log(`[offlineTemplateDrafts] merged local edits for ${serverInstance.id}`);
    return { merged, hadLocalEdits: true };
  }
  // Server is newer — clear stale snapshot
  await clearSnapshot(serverInstance.id);
  return { merged: serverInstance, hadLocalEdits: false };
}

// ─── Global listener (NetInfo + AppState) ───────────────────────────
let _listenerActive = false;
let _unsubNet: (() => void) | null = null;
let _unsubApp: ReturnType<typeof AppState.addEventListener> | null = null;

/**
 * Register global listeners that auto-flush the pending template-drafts
 * queue when network comes back online or the app foregrounds.
 * Safe to call multiple times — only registers once.
 */
export function registerOfflineTemplateDraftListeners(): () => void {
  if (_listenerActive) return () => {};
  _listenerActive = true;

  // Flush on network recovery
  _unsubNet = NetInfo.addEventListener((state) => {
    if (state.isConnected && state.isInternetReachable !== false) {
      flushPendingTemplateDrafts().catch(() => {});
    }
  });

  // Flush on app foreground
  const handleAppState = (next: AppStateStatus) => {
    if (next === "active") {
      flushPendingTemplateDrafts().catch(() => {});
    }
  };
  _unsubApp = AppState.addEventListener("change", handleAppState);

  return () => {
    _listenerActive = false;
    _unsubNet?.();
    _unsubNet = null;
    _unsubApp?.remove();
    _unsubApp = null;
  };
}
