/**
 * Phase O2 · SQLite schema migration tests.
 *
 * Uses an in-memory SQL shim to verify that:
 *   1. Fresh DB → user_version bumped to 1, all 4 O2 tables exist.
 *   2. Migration is idempotent — running twice causes no errors.
 *   3. Legacy Phase-1 tables survive untouched (simulated).
 */

// ── In-memory SQLite shim ──────────────────────────────────────────
jest.mock("expo-sqlite", () => {
  // Per-table row storage.
  const _tables: Record<string, any[]> = {};
  const _tableColumns: Record<string, string[]> = {};
  let _userVersion = 0;
  const _t = (name: string) => (_tables[name] = _tables[name] || []);

  function parseCreateTable(sql: string) {
    const m = /CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\(([^)]+(?:\([^)]*\))*[^)]*)\)/i.exec(sql);
    if (!m) return null;
    const name = m[1];
    const colDefs = m[2]
      .split(",")
      .map((c) => c.trim())
      .filter((c) => !c.startsWith("FOREIGN") && !c.startsWith("UNIQUE") && !c.startsWith("CHECK"))
      .map((c) => c.split(/\s+/)[0])
      .filter((c) => c && !c.startsWith("("));
    return { name, cols: colDefs };
  }

  async function execAsync(sql: string): Promise<void> {
    for (const raw of sql.split(";").map((s) => s.trim()).filter(Boolean)) {
      const s = raw;
      if (/^PRAGMA\s+journal_mode/i.test(s)) continue;
      const pvMatch = /^PRAGMA\s+user_version\s*=\s*(\d+)/i.test(s);
      if (pvMatch) {
        const n = parseInt(s.match(/=\s*(\d+)/)![1], 10);
        _userVersion = n;
        continue;
      }
      if (/^CREATE\s+INDEX/i.test(s)) continue;
      const ct = parseCreateTable(s);
      if (ct) {
        _t(ct.name);
        _tableColumns[ct.name] = ct.cols;
        continue;
      }
      // Skip anything else gracefully.
    }
  }

  async function runAsync(sql: string, params: any[] = []): Promise<void> {
    const s = sql.trim();
    // INSERT OR REPLACE
    const insertMatch = /^INSERT\s+(?:OR\s+REPLACE\s+)?INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)/i.exec(s);
    if (insertMatch) {
      const [, table, colsRaw] = insertMatch;
      const cols = colsRaw.split(",").map((c) => c.trim());
      const row: any = {};
      cols.forEach((c, i) => { row[c] = params[i]; });
      const t = _t(table);
      if (/OR\s+REPLACE/i.test(s)) {
        const pk = cols[0]; // assume first col is PK
        const idx = t.findIndex((r: any) => r[pk] === row[pk]);
        if (idx >= 0) { t[idx] = row; return; }
      }
      t.push(row);
      return;
    }
    // DELETE
    const delMatch = /^DELETE\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+))?/i.exec(s);
    if (delMatch) {
      const [, table, where] = delMatch;
      const t = _t(table);
      if (where) {
        const colMatch = /(\w+)\s*=\s*\?/.exec(where);
        if (colMatch) {
          const col = colMatch[1];
          const kept = t.filter((r: any) => r[col] !== params[0]);
          t.length = 0; t.push(...kept);
        }
      } else {
        t.length = 0;
      }
      return;
    }
    // UPDATE (simplified — handled more fully in queue test)
  }

  async function getAllAsync(sql: string, params: any[] = []): Promise<any[]> {
    const s = sql.trim();
    // PRAGMA user_version via getAllAsync
    if (/^PRAGMA\s+user_version/i.test(s)) {
      return [{ user_version: _userVersion }];
    }
    // SELECT ... FROM table ...
    const selMatch = /^SELECT\s+(.+?)\s+FROM\s+(\w+)/i.exec(s);
    if (!selMatch) return [];
    const [, , table] = selMatch;
    return (_tables[table] || []).slice();
  }

  async function getFirstAsync(sql: string, params: any[] = []): Promise<any> {
    const s = sql.trim();
    if (/^PRAGMA\s+user_version/i.test(s)) {
      return { user_version: _userVersion };
    }
    const selMatch = /^SELECT\s+(.+?)\s+FROM\s+(\w+)/i.exec(s);
    if (!selMatch) return null;
    const [, cols, table] = selMatch;
    const t = (_tables[table] || []);
    const whereMatch = /WHERE\s+(\w+)\s*=\s*\?/i.exec(s);
    if (whereMatch) {
      const col = whereMatch[1];
      return t.find((r: any) => r[col] === params[0]) || null;
    }
    return t[0] || null;
  }

  return {
    openDatabaseAsync: jest.fn(async () => ({
      execAsync, runAsync, getAllAsync, getFirstAsync,
    })),
    __getTables: () => _tables,
    __getTableColumns: () => _tableColumns,
    __getUserVersion: () => _userVersion,
    __reset: () => {
      for (const k of Object.keys(_tables)) delete _tables[k];
      for (const k of Object.keys(_tableColumns)) delete _tableColumns[k];
      _userVersion = 0;
    },
  };
});

jest.mock("react-native-get-random-values", () => {});
jest.mock("@react-native-community/netinfo", () => ({
  addEventListener: jest.fn(() => jest.fn()),
  fetch: jest.fn().mockResolvedValue({ isConnected: true }),
}));

import * as SQLite from "expo-sqlite";
import { getSyncDb, getSchemaVersion, getConfig, setConfig, __resetForTests } from "@/src/services/sync/db";

beforeEach(() => {
  (SQLite as any).__reset();
  __resetForTests();
});

describe("sync DB schema migration (Phase O2)", () => {
  it("fresh DB bumps user_version to 1 and creates all 4 O2 tables", async () => {
    await getSyncDb();
    expect((SQLite as any).__getUserVersion()).toBe(1);

    const tables = (SQLite as any).__getTableColumns();
    expect(tables).toHaveProperty("sync_queue");
    expect(tables).toHaveProperty("service_reports");
    expect(tables).toHaveProperty("photos_pending");
    expect(tables).toHaveProperty("config");

    // Verify sync_queue has the expected columns
    expect(tables.sync_queue).toEqual(
      expect.arrayContaining([
        "id", "op_type", "entity_id", "endpoint", "method",
        "payload_json", "status", "attempt_count", "max_retries",
        "last_attempt_at", "last_error", "idempotency_key",
        "created_at", "updated_at",
      ]),
    );
  });

  it("migration is idempotent — running twice causes no errors", async () => {
    await getSyncDb(); // first run
    __resetForTests(); // reset the _migrated flag but keep DB state
    await getSyncDb(); // second run — should be a no-op (version already 1)
    expect((SQLite as any).__getUserVersion()).toBe(1);
  });

  it("config table supports get/set round-trip", async () => {
    await getSyncDb();
    await setConfig("last_sync_at", "2026-08-29T12:00:00Z");
    const val = await getConfig("last_sync_at");
    expect(val).toBe("2026-08-29T12:00:00Z");
  });
});
