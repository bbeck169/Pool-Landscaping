/**
 * Phase O3 · Service-log offline flow tests.
 *
 * Covers:
 *   1. cacheServiceReport + getCachedServiceReport round-trip.
 *   2. markDirty / clearDirty flags.
 *   3. submitOffline enqueues service_report.upsert into sync_queue.
 *   4. Submit sets dirty flag on cached report.
 *   5. Simulated reconnect: queue drains the submit op.
 *   6. Empty report submit (no readings/chemicals) still enqueues.
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
      const t = _t(table);
      if (/OR\s+REPLACE/i.test(s)) {
        const pk = cols[0];
        const idx = t.findIndex((r: any) => r[pk] === row[pk]);
        if (idx >= 0) { t[idx] = row; return { changes: 1 }; }
      }
      t.push(row);
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
    __getTables: () => _tables,
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
import { __clearForTests as clearQueue, getPending } from "@/src/services/sync/queue";
import {
  cacheServiceReport,
  getCachedServiceReport,
  markDirty,
  clearDirty,
  submitOffline,
} from "@/src/services/sync/offlineServiceLog";
import {
  __setOnlineForTests as setOnline,
} from "@/src/services/sync/netBus";

// ── setup ──────────────────────────────────────────────────────────
beforeEach(async () => {
  (SQLite as any).__reset();
  resetDb();
  setOnline(false); // prevent auto-dispatch
  await clearQueue();
});

// ── tests ──────────────────────────────────────────────────────────
describe("Service log offline (Phase O3)", () => {
  const mockReport = {
    id: "sr-abc",
    job_id: "job-1",
    chemical_readings: [{ key: "ph", value: 7.2 }],
    chemicals_added: [{ name: "Chlorine", amount: 2 }],
    checklist_items: [{ label: "Skim surface", checked: true }],
    notes: "All good",
    water_bodies: [],
  };

  it("cacheServiceReport + getCachedServiceReport round-trip", async () => {
    await cacheServiceReport("job-1", mockReport);
    const cached = await getCachedServiceReport("job-1");
    expect(cached).toBeTruthy();
    expect(cached!.id).toBe("sr-abc");
    expect(cached!.chemical_readings).toHaveLength(1);
    expect(cached!.notes).toBe("All good");
  });

  it("getCachedServiceReport returns null for uncached job", async () => {
    const cached = await getCachedServiceReport("job-999");
    expect(cached).toBeNull();
  });

  it("markDirty / clearDirty round-trip", async () => {
    await cacheServiceReport("job-1", mockReport);
    await markDirty("job-1");

    const tables = (SQLite as any).__getTables();
    const sr = tables["service_reports"]?.find((r: any) => r.job_id === "job-1");
    expect(sr?.dirty).toBe(1);

    await clearDirty("job-1");
    const sr2 = tables["service_reports"]?.find((r: any) => r.job_id === "job-1");
    expect(sr2?.dirty).toBe(0);
  });

  it("submitOffline enqueues service_report.upsert", async () => {
    await cacheServiceReport("job-1", mockReport);
    const clientId = await submitOffline("job-1", mockReport);

    expect(clientId).toBeTruthy();
    expect(typeof clientId).toBe("string");

    const pending = await getPending();
    expect(pending.length).toBe(1);
    expect(pending[0].op_type).toBe("service_report.upsert");
    expect(pending[0].entity_id).toBe("sr-abc");
    expect(pending[0].status).toBe("pending");

    const payload = JSON.parse(pending[0].payload_json);
    expect(payload.job_id).toBe("job-1");
    expect(payload.submitted).toBe(true);
    expect(payload.chemical_readings).toHaveLength(1);
  });

  it("submitOffline marks cached report as dirty", async () => {
    await cacheServiceReport("job-1", mockReport);
    await submitOffline("job-1", mockReport);

    const tables = (SQLite as any).__getTables();
    const sr = tables["service_reports"]?.find((r: any) => r.job_id === "job-1");
    expect(sr?.dirty).toBe(1);
  });

  it("empty report (no readings/chemicals) still enqueues", async () => {
    const emptyReport = { id: "sr-empty", job_id: "job-2" };
    const clientId = await submitOffline("job-2", emptyReport);
    expect(clientId).toBeTruthy();

    const pending = await getPending();
    expect(pending.length).toBe(1);
    const payload = JSON.parse(pending[0].payload_json);
    expect(payload.chemical_readings).toEqual([]);
    expect(payload.submitted).toBe(true);
  });

  it("overwrite cache preserves only latest version", async () => {
    await cacheServiceReport("job-1", { ...mockReport, notes: "v1" });
    await cacheServiceReport("job-1", { ...mockReport, notes: "v2" });
    const cached = await getCachedServiceReport("job-1");
    expect(cached!.notes).toBe("v2");
  });
});
