/**
 * Phase O3 · Conflict detection tests.
 *
 * Covers:
 *   1. recordConflict inserts a row into sync_conflicts.
 *   2. onConflict listener fires.
 *   3. getUnresolvedConflicts returns only unresolved.
 *   4. resolveConflict marks it resolved.
 *   5. getConflictCount returns correct count.
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
      const m = /(\w+)\s*=\s*(?:\?|'([^']*)'|(\d+))/i.exec(cond.trim());
      if (!m) continue;
      const col = m[1];
      let val: any;
      if (m[2] !== undefined) val = m[2]; // string literal
      else if (m[3] !== undefined) val = Number(m[3]); // numeric literal
      else val = params[pIdx++]; // placeholder
      // Coerce for comparison
      if (typeof row[col] === "number" && typeof val === "string") {
        if (row[col] !== Number(val)) return false;
      } else if (typeof row[col] === "string" && typeof val === "number") {
        if (Number(row[col]) !== val) return false;
      } else if (row[col] !== val) return false;
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
    const cntMatch = /SELECT\s+COUNT\(\*\)\s+as\s+(\w+)\s+FROM\s+(\w+)\s+WHERE\s+(.+)/i.exec(s);
    if (cntMatch) {
      const [, alias, table, where] = cntMatch;
      const t = _t(table);
      const cnt = t.filter((r) => matchesWhere(r, where, params)).length;
      return [{ [alias]: cnt }];
    }
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
import {
  recordConflict,
  onConflict,
  getUnresolvedConflicts,
  resolveConflict,
  getConflictCount,
  __clearForTests as clearConflicts,
} from "@/src/services/sync/conflicts";

// ── setup ──────────────────────────────────────────────────────────
beforeEach(async () => {
  (SQLite as any).__reset();
  resetDb();
  await clearConflicts();
});

// ── tests ──────────────────────────────────────────────────────────
describe("Conflict detection (Phase O3)", () => {
  it("recordConflict inserts a row into sync_conflicts", async () => {
    const conflict = await recordConflict({
      queueEntryId: "q-1",
      opType: "service_report.upsert",
      entityId: "sr-1",
      clientPayload: { notes: "client version" },
      serverState: { notes: "server version" },
      statusCode: 409,
    });

    expect(conflict.id).toBeTruthy();
    expect(conflict.queue_entry_id).toBe("q-1");
    expect(conflict.op_type).toBe("service_report.upsert");
    expect(conflict.entity_id).toBe("sr-1");
    expect(conflict.status_code).toBe(409);
    expect(conflict.resolved).toBe(0);
  });

  it("onConflict listener fires when conflict is recorded", async () => {
    const fired: any[] = [];
    const unsub = onConflict((c) => fired.push(c));

    await recordConflict({
      queueEntryId: "q-2",
      opType: "job.arrive",
      entityId: "job-1",
      clientPayload: {},
      serverState: { error: "conflict" },
      statusCode: 409,
    });

    expect(fired).toHaveLength(1);
    expect(fired[0].op_type).toBe("job.arrive");
    unsub();

    // After unsub, no more calls
    await recordConflict({
      queueEntryId: "q-3",
      opType: "job.arrive",
      entityId: "job-2",
      clientPayload: {},
      serverState: {},
      statusCode: 409,
    });
    expect(fired).toHaveLength(1);
  });

  it("getUnresolvedConflicts returns only unresolved", async () => {
    await recordConflict({
      queueEntryId: "q-a",
      opType: "a",
      entityId: "e-a",
      clientPayload: {},
      serverState: {},
      statusCode: 409,
    });
    const c2 = await recordConflict({
      queueEntryId: "q-b",
      opType: "b",
      entityId: "e-b",
      clientPayload: {},
      serverState: {},
      statusCode: 409,
    });

    // Resolve one
    await resolveConflict(c2.id);

    const unresolved = await getUnresolvedConflicts();
    expect(unresolved).toHaveLength(1);
    expect(unresolved[0].op_type).toBe("a");
  });

  it("getConflictCount returns correct count", async () => {
    expect(await getConflictCount()).toBe(0);

    await recordConflict({
      queueEntryId: "q-x",
      opType: "x",
      entityId: "e-x",
      clientPayload: {},
      serverState: {},
      statusCode: 409,
    });

    expect(await getConflictCount()).toBe(1);

    await recordConflict({
      queueEntryId: "q-y",
      opType: "y",
      entityId: "e-y",
      clientPayload: {},
      serverState: {},
      statusCode: 409,
    });

    expect(await getConflictCount()).toBe(2);
  });

  it("resolveConflict marks conflict as resolved", async () => {
    const c = await recordConflict({
      queueEntryId: "q-r",
      opType: "r",
      entityId: "e-r",
      clientPayload: {},
      serverState: {},
      statusCode: 409,
    });

    await resolveConflict(c.id);

    const unresolved = await getUnresolvedConflicts();
    expect(unresolved).toHaveLength(0);
    expect(await getConflictCount()).toBe(0);
  });
});
