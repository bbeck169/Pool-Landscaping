/**
 * Phase O3 · job.arrive offline queue tests.
 *
 * Covers:
 *   1. enqueueJobArrive creates a sync_queue entry with correct op_type.
 *   2. Payload includes job_id and arrived_at timestamp.
 *   3. Online enqueue auto-dispatches (via flush).
 *   4. Offline enqueue holds as pending until reconnect.
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
        _userVersion = parseInt(raw.match(/=\s*(\d+)/)![1], 10); continue;
      }
      if (/^CREATE\s+(TABLE|INDEX)/i.test(raw)) {
        const tm = /CREATE TABLE IF NOT EXISTS\s+(\w+)/i.exec(raw);
        if (tm) _t(tm[1]); continue;
      }
    }
  }

  async function runAsync(sql: string, params: any[] = []): Promise<any> {
    const s = sql.trim();
    const ins = /^INSERT\s+(?:OR\s+REPLACE\s+)?INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)/i.exec(s);
    if (ins) {
      const [, table, colsRaw, valsRaw] = ins;
      const cols = colsRaw.split(",").map((c) => c.trim());
      const valTokens = valsRaw.split(",").map((v) => v.trim());
      const row: any = {};
      let pIdx = 0;
      cols.forEach((c, i) => {
        const token = valTokens[i];
        if (token === "?") { row[c] = params[pIdx++]; }
        else if (token.startsWith("'") && token.endsWith("'")) { row[c] = token.slice(1, -1); }
        else if (/^NULL$/i.test(token)) { row[c] = null; }
        else { row[c] = isNaN(Number(token)) ? token : Number(token); }
      });
      _t(table).push(row);
      return { changes: 1 };
    }
    const upd = /^UPDATE\s+(\w+)\s+SET\s+([\s\S]+?)\s+WHERE\s+([\s\S]+)/i.exec(s);
    if (upd) {
      const [, table, setClause, whereClause] = upd;
      const t = _t(table);
      const setOps: { col: string; value?: any; paramIdx?: number }[] = [];
      const setParts = setClause.split(",").map((p) => p.trim());
      let pIdx = 0;
      for (const part of setParts) {
        const mQ = /(\w+)\s*=\s*\?/.exec(part);
        if (mQ) { setOps.push({ col: mQ[1], paramIdx: pIdx }); pIdx++; continue; }
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
      for (const row of t) {
        if (matchesWhere(row, whereClause, whereParams)) {
          for (const op of setOps) {
            row[op.col] = op.paramIdx !== undefined ? params[op.paramIdx] : op.value;
          }
        }
      }
      return { changes: 0 };
    }
    const del = /^DELETE\s+FROM\s+(\w+)/i.exec(s);
    if (del) { const t = _t(del[1]); t.length = 0; return { changes: 0 }; }
    return { changes: 0 };
  }

  async function getAllAsync(sql: string, params: any[] = []): Promise<any[]> {
    const s = sql.trim();
    if (/^PRAGMA\s+user_version/i.test(s)) return [{ user_version: _userVersion }];
    const grp = /SELECT\s+(\w+),\s*COUNT\(\*\)\s+as\s+(\w+)\s+FROM\s+(\w+)\s+GROUP BY\s+(\w+)/i.exec(s);
    if (grp) {
      const [, groupCol, cntAlias, table] = grp;
      const t = _t(table);
      const counts: Record<string, number> = {};
      for (const row of t) { counts[row[groupCol]] = (counts[row[groupCol]] || 0) + 1; }
      return Object.entries(counts).map(([k, v]) => ({ [groupCol]: k, [cntAlias]: v }));
    }
    const sel = /SELECT\s+(.+?)\s+FROM\s+(\w+)/i.exec(s);
    if (!sel) return [];
    const [, , table] = sel;
    let rows = (_tables[table] || []).slice();
    const wh = /WHERE\s+(.+?)(?:\s+ORDER|$)/i.exec(s);
    if (wh) { rows = rows.filter((r) => matchesWhere(r, wh[1], params)); }
    return rows;
  }

  async function getFirstAsync(sql: string, params: any[] = []): Promise<any> {
    if (/^PRAGMA\s+user_version/i.test(sql.trim())) return { user_version: _userVersion };
    const rows = await getAllAsync(sql, params);
    return rows[0] || null;
  }

  return {
    openDatabaseAsync: jest.fn(async () => ({ execAsync, runAsync, getAllAsync, getFirstAsync })),
    __reset: () => { for (const k of Object.keys(_tables)) delete _tables[k]; _userVersion = 0; },
  };
});

jest.mock("react-native-get-random-values", () => {});
jest.mock("@react-native-community/netinfo", () => ({
  addEventListener: jest.fn(() => jest.fn()),
  fetch: jest.fn().mockResolvedValue({ isConnected: true }),
}));
jest.mock("@react-native-async-storage/async-storage", () => ({
  default: { getItem: jest.fn().mockResolvedValue(null), setItem: jest.fn(), removeItem: jest.fn() },
}));
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
import { __resetForTests as resetDb } from "@/src/services/sync/db";
import { __clearForTests as clearQueue, getPending, flush } from "@/src/services/sync/queue";
import { enqueueJobArrive } from "@/src/services/sync/jobArrive";
import {
  __setOnlineForTests as setOnline,
} from "@/src/services/sync/netBus";

const { api: mockApi } = require("@/src/api");

// ── setup ──────────────────────────────────────────────────────────
beforeEach(async () => {
  (SQLite as any).__reset();
  resetDb();
  setOnline(false);
  await clearQueue();
  jest.clearAllMocks();
});

// ── tests ──────────────────────────────────────────────────────────
describe("job.arrive offline queue (Phase O3)", () => {
  it("enqueueJobArrive creates sync_queue entry with op_type job.arrive", async () => {
    const id = await enqueueJobArrive("job-123");
    expect(id).toBeTruthy();

    const pending = await getPending();
    expect(pending).toHaveLength(1);
    expect(pending[0].op_type).toBe("job.arrive");
    expect(pending[0].entity_id).toBe("job-123");
    expect(pending[0].endpoint).toBe("/mobile/sync");
    expect(pending[0].method).toBe("BATCH");
    expect(pending[0].status).toBe("pending");
  });

  it("payload includes job_id and arrived_at ISO timestamp", async () => {
    const before = new Date().toISOString();
    await enqueueJobArrive("job-456");

    const pending = await getPending();
    const payload = JSON.parse(pending[0].payload_json);
    expect(payload.job_id).toBe("job-456");
    expect(payload.arrived_at).toBeTruthy();
    // Verify it's a valid ISO timestamp
    expect(new Date(payload.arrived_at).toISOString()).toBe(payload.arrived_at);
    // Verify it's recent
    expect(new Date(payload.arrived_at).getTime()).toBeGreaterThanOrEqual(new Date(before).getTime());
  });

  it("offline enqueue holds as pending", async () => {
    setOnline(false);
    await enqueueJobArrive("job-789");

    const pending = await getPending();
    expect(pending).toHaveLength(1);
    expect(pending[0].status).toBe("pending");
    // API should NOT have been called
    expect(mockApi.post).not.toHaveBeenCalled();
  });

  it("online enqueue triggers flush (auto-dispatch)", async () => {
    setOnline(true);
    mockApi.post.mockResolvedValueOnce({ ok: true });
    await enqueueJobArrive("job-online");

    // Give flush a tick to fire
    await new Promise((r) => setTimeout(r, 100));

    // Should have attempted to dispatch
    expect(mockApi.post).toHaveBeenCalled();
  });
});
