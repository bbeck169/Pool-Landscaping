/**
 * Phase O2 · Sync queue lifecycle + status API tests.
 *
 * Covers: enqueue, online dispatch, offline hold, reconnect flush,
 * failure shelving, triggerSyncNow, retrySingle, status counts.
 *
 * Strategy: full in-memory SQLite shim + mocked api + netBus control
 * via __setOnlineForTests / __emitForTests.
 */
jest.setTimeout(15000);

// ── In-memory SQLite shim (comprehensive) ──────────────────────────
jest.mock("expo-sqlite", () => {
  const _tables: Record<string, any[]> = {};
  let _userVersion = 0;
  const _t = (n: string) => (_tables[n] = _tables[n] || []);

  function matchesWhere(row: any, whereClause: string, params: any[]): boolean {
    // Parse "col1 = ? AND col2 = ?" patterns
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

    // SELECT * FROM table [WHERE ...] [ORDER BY ...]
    const sel = /SELECT\s+(.+?)\s+FROM\s+(\w+)/i.exec(s);
    if (!sel) return [];
    const [, , table] = sel;
    let rows = (_tables[table] || []).slice();

    const wh = /WHERE\s+(.+?)(?:\s+ORDER|$)/i.exec(s);
    if (wh) {
      const whereClause = wh[1];
      rows = rows.filter((r) => matchesWhere(r, whereClause, params));
    }

    const ord = /ORDER BY\s+(\w+)\s+(ASC|DESC)/i.exec(s);
    if (ord) {
      const [, col, dir] = ord;
      rows.sort((a, b) => {
        const av = a[col] ?? ""; const bv = b[col] ?? "";
        return dir === "DESC" ? (bv < av ? -1 : 1) : (av < bv ? -1 : 1);
      });
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

// ── API mock ───────────────────────────────────────────────────────
const mockApiPost = jest.fn().mockResolvedValue({});
const mockApiPatch = jest.fn().mockResolvedValue({});
const mockApiPut = jest.fn().mockResolvedValue({});
const mockApiDel = jest.fn().mockResolvedValue({});

jest.mock("@/src/api", () => ({
  ApiNetworkError: class extends Error { constructor(m: string) { super(m); this.name = "ApiNetworkError"; } },
  api: {
    get: jest.fn().mockResolvedValue({}),
    post: (...a: any[]) => mockApiPost(...a),
    patch: (...a: any[]) => mockApiPatch(...a),
    put: (...a: any[]) => mockApiPut(...a),
    del: (...a: any[]) => mockApiDel(...a),
  },
}));

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

// ── imports ────────────────────────────────────────────────────────
import * as SQLite from "expo-sqlite";
import { __resetForTests as resetDb } from "@/src/services/sync/db";
import {
  enqueue,
  flush,
  getPending,
  getFailed,
  getAll,
  clearDone,
  triggerSyncNow,
  retrySingle,
  wireAutoFlush,
  __clearForTests as clearQueue,
} from "@/src/services/sync/queue";
import { getSyncStatus } from "@/src/services/sync/status";
import {
  __setOnlineForTests as setOnline,
  __emitForTests as emitNet,
} from "@/src/services/sync/netBus";

// ── setup ──────────────────────────────────────────────────────────
beforeEach(async () => {
  (SQLite as any).__reset();
  resetDb();
  mockApiPost.mockReset().mockResolvedValue({});
  mockApiPatch.mockReset().mockResolvedValue({});
  mockApiPut.mockReset().mockResolvedValue({});
  mockApiDel.mockReset().mockResolvedValue({});
  setOnline(true);
  // Ensure DB is initialized for each test.
  await clearQueue();
});

// ── helpers ────────────────────────────────────────────────────────
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ── tests ──────────────────────────────────────────────────────────
describe("Sync queue (Phase O2)", () => {
  it("enqueue() writes a pending row with correct idempotency_key", async () => {
    setOnline(false); // prevent auto-dispatch
    const id = await enqueue({
      op_type: "job.update",
      entity_id: "job-1",
      endpoint: "/mobile/sync",
      payload: { status: "completed" },
    });
    expect(id).toBeTruthy();

    const rows = await getPending();
    expect(rows.length).toBe(1);
    expect(rows[0].id).toBe(id);
    expect(rows[0].status).toBe("pending");
    expect(rows[0].idempotency_key).toBe(`job.update:${id}`);
    expect(rows[0].op_type).toBe("job.update");
    expect(JSON.parse(rows[0].payload_json)).toEqual({ status: "completed" });
  });

  it("online mode: enqueue() dispatches immediately → row flips to done", async () => {
    setOnline(true);
    mockApiPost.mockResolvedValueOnce({ ok: true });

    const id = await enqueue({
      op_type: "job.update",
      entity_id: "job-2",
      endpoint: "/mobile/sync",
      payload: { notes: "test" },
    });

    // Give the fire-and-forget flush a moment to complete.
    await wait(200);

    const all = await getAll();
    const row = all.find((r) => r.id === id);
    expect(row?.status).toBe("done");
    expect(mockApiPost).toHaveBeenCalled();
  });

  it("offline mode: enqueue() stays pending — no dispatch occurs", async () => {
    setOnline(false);

    await enqueue({
      op_type: "service_report.upsert",
      entity_id: "sr-1",
      endpoint: "/mobile/sync",
      payload: { readings: {} },
    });

    await wait(100);

    const rows = await getPending();
    expect(rows.length).toBe(1);
    expect(rows[0].status).toBe("pending");
    // API should NOT have been called.
    expect(mockApiPost).not.toHaveBeenCalled();
  });

  it("reconnect event triggers flush — pending rows drain", async () => {
    setOnline(false);
    wireAutoFlush();

    await enqueue({ op_type: "job.update", entity_id: "j1", endpoint: "/mobile/sync", payload: {} });
    await enqueue({ op_type: "job.update", entity_id: "j2", endpoint: "/mobile/sync", payload: {} });

    expect((await getPending()).length).toBe(2);
    expect(mockApiPost).not.toHaveBeenCalled();

    // Simulate reconnect.
    setOnline(true);
    emitNet("network:online");

    // Wait for debounce (1.5s) + flush time.
    await wait(2500);

    const pending = await getPending();
    expect(pending.length).toBe(0);
    expect(mockApiPost).toHaveBeenCalled();
  });

  it("after max_retries attempts, row is shelved as failed", async () => {
    // Enqueue offline to prevent auto-dispatch race with _flushing guard.
    setOnline(false);
    mockApiPost.mockRejectedValue(new Error("Server 500"));

    const id = await enqueue({
      op_type: "job.update",
      entity_id: "j-fail",
      endpoint: "/mobile/sync",
      payload: {},
      maxRetries: 1, // use 1 — first failure shelves immediately
    });

    // Go online and flush once — the single failure shelves the row.
    setOnline(true);
    await flush();

    const failed = await getFailed();
    expect(failed.length).toBe(1);
    expect(failed[0].id).toBe(id);
    expect(failed[0].status).toBe("failed");
    expect(failed[0].attempt_count).toBeGreaterThanOrEqual(1);
    expect(failed[0].last_error).toContain("Server 500");
  });

  it("network errors do NOT increment attempt_count", async () => {
    setOnline(true);
    const { ApiNetworkError } = require("@/src/api");
    mockApiPost.mockRejectedValueOnce(new ApiNetworkError("No network"));

    const id = await enqueue({
      op_type: "job.update",
      entity_id: "j-net",
      endpoint: "/mobile/sync",
      payload: {},
    });

    await wait(300);

    const all = await getAll();
    const row = all.find((r) => r.id === id);
    // Network error → back to pending, attempt_count stays 0.
    expect(row?.status).toBe("pending");
    expect(row?.attempt_count).toBe(0);
  });

  it("triggerSyncNow() re-marks failed → pending and flushes", async () => {
    setOnline(false);
    const id = await enqueue({
      op_type: "job.update",
      entity_id: "j-retry",
      endpoint: "/mobile/sync",
      payload: {},
      maxRetries: 1,
    });

    // Force the row to failed status via direct DB manipulation.
    const { getSyncDb } = require("@/src/services/sync/db");
    const db = await getSyncDb();
    await db.runAsync(
      "UPDATE sync_queue SET status = 'failed', attempt_count = 5, last_error = 'test fail' WHERE id = ?",
      [id],
    );

    // Verify it's failed.
    let failed = await getFailed();
    expect(failed.length).toBe(1);

    // Now triggerSyncNow — should re-mark and flush.
    setOnline(true);
    mockApiPost.mockResolvedValueOnce({ ok: true });
    await triggerSyncNow();

    await wait(200);

    failed = await getFailed();
    // After sync, the item should be done (or re-pending if flush succeeded).
    // The key assertion: no items left as "failed".
    expect(failed.length).toBe(0);
  });

  it("retrySingle(id) retries one shelved entry", async () => {
    setOnline(false);
    const id = await enqueue({
      op_type: "note.add",
      entity_id: "j-single",
      endpoint: "/mobile/sync",
      payload: { text: "hello" },
    });

    // Force to failed.
    const { getSyncDb } = require("@/src/services/sync/db");
    const db = await getSyncDb();
    await db.runAsync(
      "UPDATE sync_queue SET status = 'failed', attempt_count = 10 WHERE id = ?",
      [id],
    );
    expect((await getFailed()).length).toBe(1);

    // Retry.
    setOnline(true);
    mockApiPost.mockResolvedValueOnce({ ok: true });
    await retrySingle(id);
    await wait(300);

    // Should have been dispatched.
    expect((await getFailed()).length).toBe(0);
  });
});

describe("Sync status API (Phase O2)", () => {
  it("getSyncStatus() returns correct counts for seeded queue", async () => {
    setOnline(false);

    // Enqueue 3 items (all pending since offline).
    await enqueue({ op_type: "a", entity_id: "1", endpoint: "/x", payload: {} });
    await enqueue({ op_type: "b", entity_id: "2", endpoint: "/x", payload: {} });
    await enqueue({ op_type: "c", entity_id: "3", endpoint: "/x", payload: {} });

    const status = await getSyncStatus();
    expect(status.pending_count).toBe(3);
    expect(status.in_flight_count).toBe(0);
    expect(status.failed_count).toBe(0);
    expect(status.is_online).toBe(false);
    expect(status.is_flushing).toBe(false);
  });

  it("clearDone() removes completed entries", async () => {
    setOnline(true);
    mockApiPost.mockResolvedValue({});
    await enqueue({ op_type: "a", entity_id: "1", endpoint: "/x", payload: {} });
    await wait(300);

    let all = await getAll();
    expect(all.some((r) => r.status === "done")).toBe(true);

    await clearDone();
    all = await getAll();
    expect(all.filter((r) => r.status === "done").length).toBe(0);
  });
});
