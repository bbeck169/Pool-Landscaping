/**
 * Phase 32 · Offline Sync Store
 *
 * Manages the local offline bundle cache + outbox queue using AsyncStorage.
 * - `downloadBundle()`: GET /api/mobile/offline-bundle → cache to AsyncStorage
 * - `getCachedBundle()`: Returns cached data or null
 * - `enqueueOutbox(item)`: Adds a write to the outbox for later sync
 * - `flushOutbox()`: POST /api/mobile/sync with all queued writes
 * - `getOutboxSize()`: Returns count of pending writes
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { api } from "@/src/api";

const BUNDLE_KEY = "offline_bundle";
const BUNDLE_TS_KEY = "offline_bundle_ts";
const OUTBOX_KEY = "offline_outbox";

export type OutboxItem = {
  id: string;
  method: "POST" | "PUT" | "PATCH" | "DELETE";
  url: string;
  body?: any;
  createdAt: string;
};

export type OfflineBundle = {
  jobs?: any[];
  customers?: any[];
  routes?: any[];
  checklists?: any[];
  config?: any;
  ts?: string;
};

/** Download the offline bundle from the server and cache it locally. */
export async function downloadBundle(): Promise<OfflineBundle | null> {
  try {
    const data = await api.get("/mobile/offline-bundle");
    const ts = new Date().toISOString();
    await AsyncStorage.setItem(BUNDLE_KEY, JSON.stringify(data));
    await AsyncStorage.setItem(BUNDLE_TS_KEY, ts);
    return { ...data, ts };
  } catch (e) {
    console.warn("[Offline] Bundle download failed:", e);
    return null;
  }
}

/** Get the cached bundle. Returns null if no bundle is cached. */
export async function getCachedBundle(): Promise<OfflineBundle | null> {
  try {
    const raw = await AsyncStorage.getItem(BUNDLE_KEY);
    if (!raw) return null;
    const ts = (await AsyncStorage.getItem(BUNDLE_TS_KEY)) || "";
    return { ...JSON.parse(raw), ts };
  } catch {
    return null;
  }
}

/** Get the timestamp of the last bundle download. */
export async function getBundleTimestamp(): Promise<string | null> {
  return AsyncStorage.getItem(BUNDLE_TS_KEY);
}

/** Clear the cached bundle. */
export async function clearBundle(): Promise<void> {
  await AsyncStorage.multiRemove([BUNDLE_KEY, BUNDLE_TS_KEY]);
}

// ─── Outbox ─────────────────────────────────────────────

/** Get all items in the outbox queue. */
async function getOutbox(): Promise<OutboxItem[]> {
  try {
    const raw = await AsyncStorage.getItem(OUTBOX_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

/** Save the outbox queue. */
async function saveOutbox(items: OutboxItem[]): Promise<void> {
  await AsyncStorage.setItem(OUTBOX_KEY, JSON.stringify(items));
}

/** Add a write operation to the outbox for later sync. */
export async function enqueueOutbox(
  method: OutboxItem["method"],
  url: string,
  body?: any,
): Promise<void> {
  const items = await getOutbox();
  items.push({
    id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    method,
    url,
    body,
    createdAt: new Date().toISOString(),
  });
  await saveOutbox(items);
}

/** Get the number of pending outbox writes. */
export async function getOutboxSize(): Promise<number> {
  return (await getOutbox()).length;
}

/** Flush the outbox by sending all queued writes to the server.
 * Returns { synced: number, failed: number }. */
export async function flushOutbox(): Promise<{ synced: number; failed: number }> {
  const items = await getOutbox();
  if (items.length === 0) return { synced: 0, failed: 0 };

  let synced = 0;
  let failed = 0;
  const remaining: OutboxItem[] = [];

  for (const item of items) {
    try {
      // Try individual replay first
      if (item.method === "POST") await api.post(item.url, item.body);
      else if (item.method === "PUT") await api.put(item.url, item.body);
      else if (item.method === "PATCH") await api.patch(item.url, item.body);
      else if (item.method === "DELETE") await api.delete(item.url);
      synced++;
    } catch (e) {
      console.warn("[Offline] Sync failed for item:", item.id, e);
      remaining.push(item);
      failed++;
    }
  }

  await saveOutbox(remaining);
  return { synced, failed };
}

/** Clear the entire outbox. */
export async function clearOutbox(): Promise<void> {
  await AsyncStorage.removeItem(OUTBOX_KEY);
}
