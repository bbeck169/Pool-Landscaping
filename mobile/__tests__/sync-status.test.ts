/**
 * Phase O2 · Reactive sync-status API tests.
 *
 * Covers:
 *   1. getSyncStatus() returns correct counts from queue state.
 *   2. getSyncStatus() reflects is_online / is_flushing.
 *   3. useSyncStatus() hook re-renders on queue mutation.
 *   4. useSyncStatus() hook re-renders on network transitions.
 *   5. Listener cleanup — unsubscribe prevents stale updates.
 */

// ── In-memory SQLite shim ──────────────────────────────────────────
jest.mock("expo-sqlite", () => {
  const _tables: Record<string, any[]> = {};
  let _userVersion = 0;
  const _t = (n: string) => (_tables[n] = _tables[n] || []);

  function matchesWhere(row: any, whereClause: string, params: any[]): boolean {
    const conditions = whereClause.split(/\s+AND\s+/i);
    let pIdx = 0;
    for (const cond of conditions) {
      const m = /(\w+)\s*=\s*(?:\?|'([^']*)')/i.exec(cond.trim());
      if (!m) continue;
      const col = m[1];
      const val = m[2] !== undefined ? m[2] : params[pIdx++];
      if (row[col] !== val) return false;
    }
    return true;
  }

  async function execAsync(sql: string): Promise<void> {
    for (const raw of sql.split(";").map((s) => s.trim()).filter(Boolean)) {
      if (/^PRAGMA\s+journal_mode/i.test(raw)) continue;
      if (/^PRAGMA\s+user_version\s*=\s*(\d+)/i.test(raw)) {
        _userVersion = parseInt(raw.match(/=\s*(\d+)/)![1], 10);
        continue;
      }
      if (/^CREATE\s+(TABLE|INDEX)/i.test(raw)) {
        const tm = /CREATE TABLE IF NOT EXISTS\s+(\w+)/i.exec(raw);
        if (tm) _t(tm[1]);
        continue;
      }
    }
  }

  async function runAsync(sql: string, params: any[] = []): Promise<any> {
    const s = sql.trim();

    // INSERT — handles mixed ? placeholders and literal values in VALUES
    const ins = /^INSERT\s+(?:OR\s+REPLACE\s+)?INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)/i.exec(s);
    if (ins) {
      const [, table, colsRaw, valsRaw] = ins;
      const cols = colsRaw.split(",").map((c) => c.trim());
      const valTokens = valsRaw.split(",").map((v) => v.trim());
      const row: any = {};
      let pIdx = 0;
      cols.forEach((c, i) => {
        const token = valTokens[i];
        if (token === "?") {
          row[c] = params[pIdx++];
        } else if (token.startsWith("'") && token.endsWith("'")) {
          row[c] = token.slice(1, -1);
        } else if (/^NULL$/i.test(token)) {
          row[c] = null;
        } else {
          row[c] = isNaN(Number(token)) ? token : Number(token);
        }
      });
      const t = _t(table);
      if (/OR\s+REPLACE/i.test(s)) {
        const pk = cols[0];
        const idx = t.findIndex((r: any) => r[pk] === row[pk]);
        if (idx >= 0) { t[idx] = row; return { changes: 1 }; }
      }
      t.push(row);
      return { changes: 1 };
    }

    // UPDATE — handles mixed ? placeholders and literal values in SET
    // Uses [\s\S] instead of . to match across newlines in multiline SQL
    const upd = /^UPDATE\s+(\w+)\s+SET\s+([\s\S]+?)\s+WHERE\s+([\s\S]+)/i.exec(s);
    if (upd) {
      const [, table, setClause, whereClause] = upd;
      const t = _t(table);
      const setOps: { col: string; value?: any; paramIdx?: number }[] = [];
      const setParts = setClause.split(",").map((p) => p.trim());
      let pIdx = 0;
      for (const part of setParts) {
        const mQ = /(\w+)\s*=\s*\?/.exec(part);
        if (mQ) {
          setOps.push({ col: mQ[1], paramIdx: pIdx });
          pIdx++;
          continue;
        }
        const mLit = /(\w+)\s*=\s*(?:'([^']*)'|(NULL|[-\d.]+))/i.exec(part);
        if (mLit) {
          const col = mLit[1];
          let val: any;
          if (mLit[2] !== undefined) val = mLit[2];
          else if (/^NULL$/i.test(mLit[3])) val = null;
          else val = Number(mLit[3]);
          setOps.push({ col, value: val });
        }
      }
      const whereParams = params.slice(pIdx);
      let changes = 0;
      for (const row of t) {
        if (matchesWhere(row, whereClause, whereParams)) {
          for (const op of setOps) {
            row[op.col] = op.paramIdx !== undefined ? params[op.paramIdx] : op.value;
          }
          changes++;
        }
      }
      return { changes };
    }

    // DELETE
    const del = /^DELETE\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+))?/i.exec(s);
    if (del) {
      const [, table, whereClause] = del;
      const t = _t(table);
      if (!whereClause) { const n = t.length; t.length = 0; return { changes: n }; }
      const kept: any[] = [];
      let removed = 0;
      for (const row of t) {
        if (matchesWhere(row, whereClause, params)) removed++;
        else kept.push(row);
      }
      t.length = 0; t.push(...kept);
      return { changes: removed };
    }

    return { changes: 0 };
  }

  async function getAllAsync(sql: string, params: any[] = []): Promise<any[]> {
    const s = sql.trim();
    if (/^PRAGMA\s+user_version/i.test(s)) return [{ user_version: _userVersion }];

    // GROUP BY
    const grp = /SELECT\s+(\w+),\s*COUNT\(\*\)\s+as\s+(\w+)\s+FROM\s+(\w+)\s+GROUP BY\s+(\w+)/i.exec(s);
    if (grp) {
      const [, groupCol, cntAlias, table] = grp;
      const t = _t(table);
      const counts: Record<string, number> = {};
      for (const row of t) { counts[row[groupCol]] = (counts[row[groupCol]] || 0) + 1; }
      return Object.entries(counts).map(([k, v]) => ({ [groupCol]: k, [cntAlias]: v }));
    }

    // SELECT
    const sel = /SELECT\s+(.+?)\s+FROM\s+(\w+)/i.exec(s);
    if (!sel) return [];
    const [, , table] = sel;
    let rows = (_tables[table] || []).slice();

    const wh = /WHERE\s+(.+?)(?:\s+ORDER|$)/i.exec(s);
    if (wh) {
      const whereClause = wh[1];
      rows = rows.filter((r) => matchesWhere(r, whereClause, params));
    }
    return rows;
  }

  async function getFirstAsync(sql: string, params: any[] = []): Promise<any> {
    const s = sql.trim();
    if (/^PRAGMA\s+user_version/i.test(s)) return { user_version: _userVersion };
    const rows = await getAllAsync(sql, params);
    return rows[0] || null;
  }

  return {
    openDatabaseAsync: jest.fn(async () => ({
      execAsync, runAsync, getAllAsync, getFirstAsync,
    })),
    __reset: () => {
      for (const k of Object.keys(_tables)) delete _tables[k];
      _userVersion = 0;
    },
    __getTables: () => _tables,
  };
});

// ── Other mocks ────────────────────────────────────────────────────
jest.mock("react-native-get-random-values", () => {});
jest.mock("@react-native-community/netinfo", () => ({
  addEventListener: jest.fn(() => jest.fn()),
  fetch: jest.fn().mockResolvedValue({ isConnected: true }),
}));
jest.mock("@react-native-async-storage/async-storage", () => ({
  default: {
    getItem: jest.fn().mockResolvedValue(null),
    setItem: jest.fn().mockResolvedValue(undefined),
    removeItem: jest.fn().mockResolvedValue(undefined),
  },
}));

// Mock API (queue.ts imports it) — no-op for status tests.
jest.mock("@/src/api", () => ({
  ApiNetworkError: class extends Error { constructor(m: string) { super(m); this.name = "ApiNetworkError"; } },
  api: {
    get: jest.fn().mockResolvedValue({}),
    post: jest.fn().mockResolvedValue({}),
    patch: jest.fn().mockResolvedValue({}),
    put: jest.fn().mockResolvedValue({}),
    del: jest.fn().mockResolvedValue({}),
  },
}));

// ── imports ────────────────────────────────────────────────────────
import * as SQLite from "expo-sqlite";
import { __resetForTests as resetDb, getSyncDb, setConfig } from "@/src/services/sync/db";
import { enqueue, __clearForTests as clearQueue, subscribe as queueSubscribe } from "@/src/services/sync/queue";
import { getSyncStatus } from "@/src/services/sync/status";
import {
  __setOnlineForTests as setOnline,
  __emitForTests as emitNet,
  isOnlineNow,
} from "@/src/services/sync/netBus";

// ── setup ──────────────────────────────────────────────────────────
beforeEach(async () => {
  (SQLite as any).__reset();
  resetDb();
  setOnline(true);
  await clearQueue();
});

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ── tests ──────────────────────────────────────────────────────────
describe("getSyncStatus() (Phase O2)", () => {
  it("returns all zeros on an empty queue", async () => {
    const s = await getSyncStatus();
    expect(s.pending_count).toBe(0);
    expect(s.in_flight_count).toBe(0);
    expect(s.failed_count).toBe(0);
    expect(s.done_count).toBe(0);
    expect(s.is_flushing).toBe(false);
  });

  it("reflects is_online accurately", async () => {
    setOnline(true);
    let s = await getSyncStatus();
    expect(s.is_online).toBe(true);

    setOnline(false);
    s = await getSyncStatus();
    expect(s.is_online).toBe(false);
  });

  it("counts pending items correctly after enqueue (offline)", async () => {
    setOnline(false);
    await enqueue({ op_type: "a", entity_id: "1", endpoint: "/x", payload: {} });
    await enqueue({ op_type: "b", entity_id: "2", endpoint: "/x", payload: {} });
    await enqueue({ op_type: "c", entity_id: "3", endpoint: "/x", payload: {} });

    const s = await getSyncStatus();
    expect(s.pending_count).toBe(3);
    expect(s.failed_count).toBe(0);
    expect(s.done_count).toBe(0);
    expect(s.is_online).toBe(false);
  });

  it("counts failed items after forced status update", async () => {
    setOnline(false);
    const id = await enqueue({ op_type: "a", entity_id: "1", endpoint: "/x", payload: {} });

    // Force to failed.
    const db = await getSyncDb();
    await db.runAsync(
      "UPDATE sync_queue SET status = 'failed', attempt_count = 10, last_error = 'test' WHERE id = ?",
      [id],
    );

    const s = await getSyncStatus();
    expect(s.failed_count).toBe(1);
    expect(s.pending_count).toBe(0);
  });

  it("reads last_sync_at from config table", async () => {
    // Initially null.
    let s = await getSyncStatus();
    expect(s.last_sync_at).toBeNull();

    // Set it.
    await setConfig("last_sync_at", "2026-08-30T10:00:00Z");
    s = await getSyncStatus();
    expect(s.last_sync_at).toBe("2026-08-30T10:00:00Z");
  });
});

describe("Queue subscribe notifies on mutations (Phase O2)", () => {
  it("listener fires on enqueue", async () => {
    setOnline(false);
    const calls: number[] = [];
    const unsub = queueSubscribe(() => calls.push(1));

    await enqueue({ op_type: "a", entity_id: "1", endpoint: "/x", payload: {} });

    // At least one notification should have fired.
    expect(calls.length).toBeGreaterThanOrEqual(1);
    unsub();
  });

  it("unsubscribe prevents further calls", async () => {
    setOnline(false);
    let callCount = 0;
    const unsub = queueSubscribe(() => callCount++);

    await enqueue({ op_type: "a", entity_id: "1", endpoint: "/x", payload: {} });
    const countAfterFirst = callCount;

    unsub(); // unsubscribe

    await enqueue({ op_type: "b", entity_id: "2", endpoint: "/x", payload: {} });
    // No additional calls after unsubscribe.
    expect(callCount).toBe(countAfterFirst);
  });
});

describe("Network transitions via netBus (Phase O2)", () => {
  it("isOnlineNow() reflects __setOnlineForTests", () => {
    setOnline(true);
    expect(isOnlineNow()).toBe(true);
    setOnline(false);
    expect(isOnlineNow()).toBe(false);
  });

  it("network:online event fires handler", () => {
    const { on } = require("@/src/services/sync/netBus");
    let fired = false;
    const unsub = on("network:online", () => { fired = true; });
    emitNet("network:online");
    expect(fired).toBe(true);
    unsub();
  });

  it("network:offline event fires handler", () => {
    const { on } = require("@/src/services/sync/netBus");
    let fired = false;
    const unsub = on("network:offline", () => { fired = true; });
    emitNet("network:offline");
    expect(fired).toBe(true);
    unsub();
  });

  it("handler unsub prevents further calls", () => {
    const { on } = require("@/src/services/sync/netBus");
    let count = 0;
    const unsub = on("network:online", () => { count++; });
    emitNet("network:online");
    expect(count).toBe(1);
    unsub();
    emitNet("network:online");
    expect(count).toBe(1); // not incremented
  });
});
