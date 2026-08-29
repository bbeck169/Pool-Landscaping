/**
 * Phase O2 · Expanded SQLite schema + migration engine.
 *
 * Manages the `poolcrm-offline.db` database.  Uses `PRAGMA user_version`
 * as the schema-version sentinel:
 *
 *   v0  — legacy (cache.native.ts Phase 1 tables: jobs, customers,
 *          properties, user).  These tables stay untouched.
 *   v1  — O2 additions: sync_queue, service_reports, photos_pending,
 *          config.
 *
 * The migration is fully idempotent — running it twice is harmless.
 * Existing data in the Phase 1 tables survives across upgrades.
 */
import * as SQLite from "expo-sqlite";

const DB_NAME = "poolcrm-offline.db";
const TARGET_VERSION = 1;

let _dbPromise: Promise<SQLite.SQLiteDatabase> | null = null;
let _migrated = false;

/**
 * Returns the singleton database handle.  First call opens the file
 * and runs any pending migrations.
 */
export async function getSyncDb(): Promise<SQLite.SQLiteDatabase> {
  if (!_dbPromise) {
    _dbPromise = SQLite.openDatabaseAsync(DB_NAME);
  }
  const db = await _dbPromise;
  if (!_migrated) {
    await _runMigrations(db);
    _migrated = true;
  }
  return db;
}

// ═══════════ Migrations ════════════════════════════════════════════
async function _runMigrations(db: SQLite.SQLiteDatabase): Promise<void> {
  // Enable WAL if not already — idempotent.
  await db.execAsync("PRAGMA journal_mode = WAL;");

  // Read current version.
  const row = await db.getFirstAsync<{ user_version: number }>(
    "PRAGMA user_version;",
  );
  const currentVersion = row?.user_version ?? 0;

  if (currentVersion >= TARGET_VERSION) return; // nothing to do

  // ── v0 → v1 ─────────────────────────────────────────────────────
  if (currentVersion < 1) {
    await db.execAsync(`
      -- Sync queue: every offline mutation is a row here.
      CREATE TABLE IF NOT EXISTS sync_queue (
        id                TEXT    PRIMARY KEY,
        op_type           TEXT    NOT NULL,
        entity_id         TEXT    NOT NULL,
        endpoint          TEXT    NOT NULL,
        method            TEXT    NOT NULL DEFAULT 'BATCH',
        payload_json      TEXT    NOT NULL DEFAULT '{}',
        status            TEXT    NOT NULL DEFAULT 'pending',
        attempt_count     INTEGER NOT NULL DEFAULT 0,
        max_retries       INTEGER NOT NULL DEFAULT 10,
        last_attempt_at   TEXT,
        last_error        TEXT,
        idempotency_key   TEXT    NOT NULL,
        created_at        TEXT    NOT NULL,
        updated_at        TEXT    NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_sq_status
        ON sync_queue (status);
      CREATE INDEX IF NOT EXISTS idx_sq_entity
        ON sync_queue (entity_id, created_at);

      -- Service reports cache (full JSON payload).
      CREATE TABLE IF NOT EXISTS service_reports (
        id         TEXT    PRIMARY KEY,
        job_id     TEXT,
        payload    TEXT    NOT NULL,
        dirty      INTEGER NOT NULL DEFAULT 0,
        cached_at  INTEGER NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_sr_job
        ON service_reports (job_id);

      -- Photos pending upload.
      CREATE TABLE IF NOT EXISTS photos_pending (
        id              TEXT    PRIMARY KEY,
        local_uri       TEXT    NOT NULL,
        entity_type     TEXT    NOT NULL DEFAULT 'service_report',
        entity_id       TEXT    NOT NULL,
        upload_status   TEXT    NOT NULL DEFAULT 'pending',
        upload_attempts INTEGER NOT NULL DEFAULT 0,
        last_error      TEXT,
        created_at      TEXT    NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_pp_status
        ON photos_pending (upload_status);

      -- Key-value config store.
      CREATE TABLE IF NOT EXISTS config (
        key   TEXT PRIMARY KEY,
        value TEXT
      );

      PRAGMA user_version = 1;
    `);
  }

  // Future: if currentVersion < 2 → run v2 migration, etc.
}


// ═══════════ Config helpers ════════════════════════════════════════
export async function getConfig(key: string): Promise<string | null> {
  const db = await getSyncDb();
  const row = await db.getFirstAsync<{ value: string }>(
    "SELECT value FROM config WHERE key = ? LIMIT 1",
    [key],
  );
  return row?.value ?? null;
}

export async function setConfig(key: string, value: string): Promise<void> {
  const db = await getSyncDb();
  await db.runAsync(
    "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
    [key, value],
  );
}

// ═══════════ Schema version query (for tests) ══════════════════════
export async function getSchemaVersion(): Promise<number> {
  const db = await getSyncDb();
  const row = await db.getFirstAsync<{ user_version: number }>(
    "PRAGMA user_version;",
  );
  return row?.user_version ?? 0;
}

// ═══════════ Test helpers ══════════════════════════════════════════
export function __resetForTests() {
  _dbPromise = null;
  _migrated = false;
}
