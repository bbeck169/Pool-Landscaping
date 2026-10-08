/**
 * Templates Library — Phase 3 (Mobile) · Offline Draft Support
 *
 * Storage primitive: raw AsyncStorage (same as writeQueue.ts / offline.ts —
 * the app does not use MMKV).
 *
 * Keys:
 *   template_drafts:{id}               → LocalSnapshot (written BEFORE every PATCH)
 *   template_drafts_pending_sync:{id}  → PendingEntry  (PATCH failed on network)
 *   template_cache:{id}                → { instance, definition } (open offline)
 *   template_list_cache                → { defs, instances } (browse offline)
 *
 * Flush order is FIFO by first-enqueue `ts` across all pending keys.
 * Only EDITS of existing drafts are offline-tolerant — creation still
 * needs an online round-trip (POST returns the id).
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import NetInfo from "@react-native-community/netinfo";
import { AppState, AppStateStatus } from "react-native";
import { api, ApiError, ApiNetworkError } from "@/src/api";

export type LocalSnapshot = {
  instance_id: string;
  title: string;
  values: Record<string, any>;
  dirty_since: string; // ISO
};

export type PendingEntry = {
  instance_id: string;
  title: string;
  values: Record<string, any>;
  ts: string;          // first enqueue (FIFO key)
  updated_ts?: string; // latest values written
};

export const SNAPSHOT_PREFIX = "template_drafts:";
export const PENDING_PREFIX = "template_drafts_pending_sync:";
const CACHE_PREFIX = "template_cache:";
const LIST_CACHE_KEY = "template_list_cache";

export const snapshotKey = (id: string) => `${SNAPSHOT_PREFIX}${id}`;
export const pendingKey = (id: string) => `${PENDING_PREFIX}${id}`;

async function getJson<T>(key: string): Promise<T | null> {
  try {
    const raw = await AsyncStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

async function setJson(key: string, val: any) {
  try { await AsyncStorage.setItem(key, JSON.stringify(val)); } catch { /* storage full — non-fatal */ }
}

async function remove(key: string) {
  try { await AsyncStorage.removeItem(key); } catch { /* non-fatal */ }
}

// ─── Snapshot ──────────────────────────────────────────────────────
export const writeSnapshot = (snap: LocalSnapshot) => setJson(snapshotKey(snap.instance_id), snap);
export const readSnapshot = (id: string) => getJson<LocalSnapshot>(snapshotKey(id));
export const clearSnapshot = (id: string) => remove(snapshotKey(id));

// ─── Offline caches (open / browse without network) ─────────────────
export const cacheInstanceBundle = (id: string, instance: any, definition: any) =>
  setJson(`${CACHE_PREFIX}${id}`, { instance, definition });
export const readInstanceBundle = (id: string) =>
  getJson<{ instance: any; definition: any }>(`${CACHE_PREFIX}${id}`);
export const clearInstanceBundle = (id: string) => remove(`${CACHE_PREFIX}${id}`);
export const cacheTemplateList = (defs: any[], instances: any[]) =>
  setJson(LIST_CACHE_KEY, { defs, instances, cached_at: new Date().toISOString() });
export const readTemplateList = () =>
  getJson<{ defs: any[]; instances: any[]; cached_at: string }>(LIST_CACHE_KEY);

// ─── Pending queue ─────────────────────────────────────────────────
export async function enqueuePending(entry: Omit<PendingEntry, "ts" | "updated_ts"> & { ts?: string }) {
  const now = entry.ts || new Date().toISOString();
  const existing = await getJson<PendingEntry>(pendingKey(entry.instance_id));
  const next: PendingEntry = {
    instance_id: entry.instance_id,
    title: entry.title,
    values: entry.values,
    ts: existing?.ts || now, // keep FIFO position of first failure
    updated_ts: now,
  };
  await setJson(pendingKey(entry.instance_id), next);
  console.log(`[offlineTemplateDrafts] queued ${entry.instance_id} (pending since ${next.ts})`);
}

export const removePending = (id: string) => remove(pendingKey(id));

export async function hasPendingForInstance(id: string): Promise<boolean> {
  return (await getJson<PendingEntry>(pendingKey(id))) !== null;
}

export async function getPendingQueue(): Promise<PendingEntry[]> {
  try {
    const keys = (await AsyncStorage.getAllKeys()).filter((k) => k.startsWith(PENDING_PREFIX));
    if (!keys.length) return [];
    const pairs = await AsyncStorage.multiGet(keys);
    const rows: PendingEntry[] = [];
    for (const [, raw] of pairs) {
      try { if (raw) rows.push(JSON.parse(raw)); } catch { /* skip corrupt */ }
    }
    return rows.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));
  } catch {
    return [];
  }
}

export async function pendingCount(): Promise<number> {
  return (await getPendingQueue()).length;
}

// ─── Sync event bus (fill screen listens to update its indicator) ───
type SyncResult = { synced: number; remaining: number; syncedIds: string[]; droppedIds: string[] };
const listeners = new Set<(r: SyncResult) => void>();
export function subscribeTemplateSync(fn: (r: SyncResult) => void) {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

// ─── Flush (FIFO replay) ────────────────────────────────────────────
let _flushing = false;

export async function flushPendingTemplateDrafts(): Promise<SyncResult> {
  if (_flushing) return { synced: 0, remaining: await pendingCount(), syncedIds: [], droppedIds: [] };
  _flushing = true;
  const syncedIds: string[] = [];
  const droppedIds: string[] = [];
  try {
    const queue = await getPendingQueue();
    for (const entry of queue) {
      try {
        await api.patch(`/templates/instances/${entry.instance_id}`, { title: entry.title, values: entry.values });
        // Only clear if nothing newer was queued while the PATCH was in flight.
        const latest = await getJson<PendingEntry>(pendingKey(entry.instance_id));
        if (!latest || latest.updated_ts === entry.updated_ts) {
          await removePending(entry.instance_id);
          const snap = await readSnapshot(entry.instance_id);
          if (!snap || !entry.updated_ts || snap.dirty_since <= entry.updated_ts) {
            await clearSnapshot(entry.instance_id);
          }
        }
        syncedIds.push(entry.instance_id);
        console.log(`[offlineTemplateDrafts] synced ${entry.instance_id}`);
      } catch (e: any) {
        if (e instanceof ApiNetworkError) {
          console.log(`[offlineTemplateDrafts] still offline — ${queue.length - syncedIds.length - droppedIds.length} pending`);
          break; // keep this + everything after it (FIFO preserved)
        }
        const status = e instanceof ApiError ? e.status : 0;
        if (status >= 400 && status < 500) {
          // 409 finalized elsewhere / 404 deleted / 403 — unrecoverable, drop.
          await removePending(entry.instance_id);
          await clearSnapshot(entry.instance_id);
          droppedIds.push(entry.instance_id);
          console.warn(`[offlineTemplateDrafts] dropped ${entry.instance_id} (${status}): ${e.message}`);
        }
        // 5xx — leave queued for the next flush attempt.
      }
    }
  } finally {
    _flushing = false;
  }
  const result = { synced: syncedIds.length, remaining: await pendingCount(), syncedIds, droppedIds };
  if (syncedIds.length || droppedIds.length) listeners.forEach((fn) => fn(result));
  return result;
}

// ─── Merge (local wins when newer / unsynced) ───────────────────────
export async function mergeLocalOverServer(serverInstance: any): Promise<{ merged: any; hadLocalEdits: boolean }> {
  const snap = await readSnapshot(serverInstance.id);
  if (!snap?.dirty_since) return { merged: serverInstance, hadLocalEdits: false };
  if (serverInstance.status === "finalized") {
    await clearSnapshot(serverInstance.id);
    await removePending(serverInstance.id);
    return { merged: serverInstance, hadLocalEdits: false };
  }
  const pending = await hasPendingForInstance(serverInstance.id);
  const serverUpdated = new Date(serverInstance.updated_at || 0).getTime();
  const localDirty = new Date(snap.dirty_since).getTime();
  if (pending || localDirty > serverUpdated) {
    console.log(`[offlineTemplateDrafts] merged local edits for ${serverInstance.id}`);
    return {
      merged: {
        ...serverInstance,
        title: snap.title || serverInstance.title,
        values: { ...(serverInstance.values || {}), ...(snap.values || {}) },
      },
      hadLocalEdits: true,
    };
  }
  await clearSnapshot(serverInstance.id); // server newer — stale snapshot
  return { merged: serverInstance, hadLocalEdits: false };
}

// ─── Global listeners (NetInfo reconnect + AppState foreground) ─────
let _listenerActive = false;

export function registerOfflineTemplateDraftListeners(): () => void {
  if (_listenerActive) return () => {};
  _listenerActive = true;
  const unsubNet = NetInfo.addEventListener((state) => {
    if (state.isConnected && state.isInternetReachable !== false) {
      flushPendingTemplateDrafts().catch(() => {});
    }
  });
  const sub = AppState.addEventListener("change", (next: AppStateStatus) => {
    if (next === "active") flushPendingTemplateDrafts().catch(() => {});
  });
  flushPendingTemplateDrafts().catch(() => {}); // cold start
  return () => {
    _listenerActive = false;
    unsubNet?.();
    sub?.remove();
  };
}
