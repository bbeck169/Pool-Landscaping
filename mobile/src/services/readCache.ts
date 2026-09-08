/**
 * Phase O5 · Generic SQLite read-cache layer for offline queries.
 *
 * Stores arbitrary JSON payloads keyed by a cache key string.
 * Uses the sync DB from O2 (same poolcrm-offline.db).
 */
import { getSyncDb } from "./sync/db";

const TABLE = "read_cache";

/** Ensure the read_cache table exists (idempotent). */
let _ensured = false;
async function ensureTable(): Promise<void> {
  if (_ensured) return;
  const db = await getSyncDb();
  await db.execAsync(`
    CREATE TABLE IF NOT EXISTS ${TABLE} (
      key        TEXT PRIMARY KEY,
      payload    TEXT NOT NULL,
      cached_at  INTEGER NOT NULL
    );
  `);
  _ensured = true;
}

/** Write a value into the cache. */
export async function writeCache(key: string, data: any): Promise<void> {
  await ensureTable();
  const db = await getSyncDb();
  await db.runAsync(
    `INSERT OR REPLACE INTO ${TABLE} (key, payload, cached_at) VALUES (?, ?, ?)`,
    [key, JSON.stringify(data), Date.now()],
  );
}

/** Read a value from the cache. Returns null if not found. */
export async function readCache<T = any>(key: string): Promise<T | null> {
  await ensureTable();
  const db = await getSyncDb();
  const row = await db.getFirstAsync<{ payload: string; cached_at: number }>(
    `SELECT payload, cached_at FROM ${TABLE} WHERE key = ?`,
    [key],
  );
  if (!row?.payload) return null;
  try { return JSON.parse(row.payload) as T; }
  catch { return null; }
}

/** Read with age info. */
export async function readCacheWithAge<T = any>(key: string): Promise<{
  data: T | null;
  cachedAt: number | null;
}> {
  await ensureTable();
  const db = await getSyncDb();
  const row = await db.getFirstAsync<{ payload: string; cached_at: number }>(
    `SELECT payload, cached_at FROM ${TABLE} WHERE key = ?`,
    [key],
  );
  if (!row?.payload) return { data: null, cachedAt: null };
  try { return { data: JSON.parse(row.payload) as T, cachedAt: row.cached_at }; }
  catch { return { data: null, cachedAt: null }; }
}

/** Delete a cache entry. */
export async function invalidateCache(key: string): Promise<void> {
  await ensureTable();
  const db = await getSyncDb();
  await db.runAsync(`DELETE FROM ${TABLE} WHERE key = ?`, [key]);
}

/** Delete all cache entries matching a prefix. */
export async function invalidateCachePrefix(prefix: string): Promise<void> {
  await ensureTable();
  const db = await getSyncDb();
  await db.runAsync(
    `DELETE FROM ${TABLE} WHERE key LIKE ?`,
    [`${prefix}%`],
  );
}

/** Wipe all cached data. */
export async function clearAllCache(): Promise<void> {
  await ensureTable();
  const db = await getSyncDb();
  await db.runAsync(`DELETE FROM ${TABLE}`);
}

/** Count entries matching a prefix (for diagnostics). */
export async function countCacheKeys(prefix?: string): Promise<number> {
  await ensureTable();
  const db = await getSyncDb();
  const row = prefix
    ? await db.getFirstAsync<{ cnt: number }>(
        `SELECT count(*) as cnt FROM ${TABLE} WHERE key LIKE ?`,
        [`${prefix}%`],
      )
    : await db.getFirstAsync<{ cnt: number }>(
        `SELECT count(*) as cnt FROM ${TABLE}`,
      );
  return row?.cnt ?? 0;
}

/** Approximate total cache size in bytes (diagnostics). */
export async function cacheByteSize(): Promise<number> {
  await ensureTable();
  const db = await getSyncDb();
  const row = await db.getFirstAsync<{ sz: number }>(
    `SELECT coalesce(sum(length(payload)), 0) as sz FROM ${TABLE}`,
  );
  return row?.sz ?? 0;
}

/** For tests. */
export function __resetEnsured(): void {
  _ensured = false;
}
