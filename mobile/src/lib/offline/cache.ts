/**
 * Feb-2026 · Phase 1 mobile offline foundation — SQLite read cache.
 *
 * Stores the tech's this-week route + associated customers +
 * properties + the last successful ``/api/me`` payload, so the app
 * has enough data to render the schedule day view + job detail +
 * customer detail when the device is offline (or the first API
 * request in a session fails with a network error).
 *
 * Only the JSON payload is stored — no field-level columns.  Phase
 * 2 (write queue) will add indexed columns for pending writes; this
 * phase keeps the schema minimal.  Every consumer must handle a
 * ``null`` return (empty cache on first-run / fresh install).
 */
import * as SQLite from "expo-sqlite";


let _dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;
let _initPromise: Promise<void> | null = null;

async function _db(): Promise<SQLite.SQLiteDatabase> {
  if (!_dbPromise) {
    _dbPromise = SQLite.openDatabaseAsync("poolcrm-offline.db");
  }
  const db = await _dbPromise;
  if (!_initPromise) {
    _initPromise = db.execAsync(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY,
      tech_user_id TEXT,
      scheduled_date TEXT,
      payload TEXT NOT NULL,
      cached_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_jobs_tech_date
      ON jobs (tech_user_id, scheduled_date);
    CREATE TABLE IF NOT EXISTS customers (
      id TEXT PRIMARY KEY,
      payload TEXT NOT NULL,
      cached_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS properties (
      id TEXT PRIMARY KEY,
      customer_id TEXT,
      payload TEXT NOT NULL,
      cached_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS user (
      id TEXT PRIMARY KEY,
      payload TEXT NOT NULL,
      cached_at INTEGER NOT NULL
    );
  `);
  }
  await _initPromise;
  return db;
}

/** Legacy no-op kept for callers that already invoke it; schema
 *  creation is now lazy inside ``_db()``.  Safe to call on boot. */
export async function initCache(): Promise<void> {
  await _db();
}

type AnyRow = { id: string; [k: string]: any };


export async function cacheWeekJobs(
  techUserId: string,
  jobs: AnyRow[],
): Promise<void> {
  if (!techUserId) return;
  const db = await _db();
  await db.withTransactionAsync(async () => {
    // Wipe the tech's existing week — write-through is a full
    // replace, so removed jobs don't linger in the cache.
    await db.runAsync(`DELETE FROM jobs WHERE tech_user_id = ?`, [techUserId]);
    for (const j of jobs) {
      if (!j?.id) continue;
      await db.runAsync(
        `INSERT INTO jobs (id, tech_user_id, scheduled_date, payload, cached_at)
         VALUES (?, ?, ?, ?, ?)`,
        [
          j.id,
          techUserId,
          String(j.scheduled_date || "").slice(0, 10),
          JSON.stringify(j),
          Date.now(),
        ],
      );
    }
  });
}


export async function getCachedWeekJobs(
  techUserId: string,
  weekStart?: string | null,
): Promise<AnyRow[]> {
  if (!techUserId) return [];
  const db = await _db();
  const rows = weekStart
    ? await db.getAllAsync<{ payload: string }>(
        `SELECT payload FROM jobs
          WHERE tech_user_id = ?
            AND scheduled_date >= ?
            AND scheduled_date < date(?, '+7 days')
          ORDER BY scheduled_date, id`,
        [techUserId, weekStart, weekStart],
      )
    : await db.getAllAsync<{ payload: string }>(
        `SELECT payload FROM jobs
          WHERE tech_user_id = ?
          ORDER BY scheduled_date, id`,
        [techUserId],
      );
  return rows.map((r) => { try { return JSON.parse(r.payload); } catch { return null; } })
             .filter(Boolean) as AnyRow[];
}


export async function getCachedJob(id: string): Promise<AnyRow | null> {
  if (!id) return null;
  const db = await _db();
  const row = await db.getFirstAsync<{ payload: string }>(
    `SELECT payload FROM jobs WHERE id = ? LIMIT 1`, [id],
  );
  if (!row) return null;
  try { return JSON.parse(row.payload); } catch { return null; }
}


async function _upsert(
  table: "customers" | "properties" | "user",
  id: string,
  payload: any,
  extraCols?: Record<string, string | null>,
): Promise<void> {
  if (!id) return;
  const db = await _db();
  const cols = ["id", ...Object.keys(extraCols || {}), "payload", "cached_at"];
  const vals = [id, ...Object.values(extraCols || {}), JSON.stringify(payload), Date.now()];
  const placeholders = cols.map(() => "?").join(", ");
  await db.runAsync(
    `INSERT OR REPLACE INTO ${table} (${cols.join(", ")}) VALUES (${placeholders})`,
    vals as any,
  );
}


async function _get<T = AnyRow>(
  table: "customers" | "properties" | "user",
  id: string,
): Promise<T | null> {
  if (!id) return null;
  const db = await _db();
  const row = await db.getFirstAsync<{ payload: string }>(
    `SELECT payload FROM ${table} WHERE id = ? LIMIT 1`, [id],
  );
  if (!row) return null;
  try { return JSON.parse(row.payload) as T; } catch { return null; }
}


export const cacheCustomer   = (c: AnyRow) => _upsert("customers", c?.id, c);
export const getCachedCustomer = (id: string) => _get("customers", id);

export const cacheProperty   = (p: AnyRow) =>
  _upsert("properties", p?.id, p, { customer_id: p?.customer_id ?? null });
export const getCachedProperty = (id: string) => _get("properties", id);

export const cacheMe   = (u: AnyRow) => _upsert("user", u?.id, u);
export const getCachedMe = async (): Promise<AnyRow | null> => {
  const db = await _db();
  const row = await db.getFirstAsync<{ payload: string }>(
    `SELECT payload FROM user ORDER BY cached_at DESC LIMIT 1`,
  );
  if (!row) return null;
  try { return JSON.parse(row.payload); } catch { return null; }
};


export async function wipeCache(): Promise<void> {
  const db = await _db();
  await db.execAsync(`
    DELETE FROM jobs;
    DELETE FROM customers;
    DELETE FROM properties;
    DELETE FROM user;
  `);
}


// Test-only: reset the module-level DB reference so a fresh in-memory
// database can be opened in a jest test.  Do NOT call this from app
// code.
export function __resetForTests() {
  _dbPromise = null;
  _initPromise = null;
}
