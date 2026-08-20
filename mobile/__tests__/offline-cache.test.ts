/**
 * Feb-2026 · Phase 1 offline foundation — cache tests (jest-expo).
 *
 * We mock ``expo-sqlite`` with an in-memory shim inside the mock
 * factory itself (jest requires factories to be self-contained; no
 * out-of-scope refs allowed).  The real ``cache.ts`` module is
 * exercised end-to-end: schema init, upsert, retrieve, wipe.
 */

jest.mock("expo-sqlite", () => {
  const _tables: Record<string, any[]> = {};
  const _t = (name: string) => (_tables[name] = _tables[name] || []);

  async function runAsync(sql: string, params: any[] = []): Promise<void> {
    const s = sql.trim();
    const insertMatch = /^INSERT (?:OR REPLACE )?INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)/i.exec(s);
    if (insertMatch) {
      const [, table, colsRaw] = insertMatch;
      const cols = colsRaw.split(",").map((c) => c.trim());
      const row: any = {};
      cols.forEach((c, i) => { row[c] = params[i]; });
      const t = _t(table);
      if (/OR REPLACE/i.test(s)) {
        const idx = t.findIndex((r: any) => r.id === row.id);
        if (idx >= 0) { t[idx] = row; return; }
      }
      t.push(row);
      return;
    }
    const delMatch = /^DELETE FROM\s+(\w+)(?:\s+WHERE\s+(\w+)\s*=\s*\?)?/i.exec(s);
    if (delMatch) {
      const [, table, col] = delMatch;
      const t = _t(table);
      if (col) {
        const kept = t.filter((r: any) => r[col] !== params[0]);
        t.length = 0; t.push(...kept);
      } else {
        t.length = 0;
      }
      return;
    }
    throw new Error(`shim: unhandled SQL: ${s}`);
  }

  async function execAsync(sql: string): Promise<void> {
    for (const stmt of sql.split(";").map((s) => s.trim()).filter(Boolean)) {
      if (/^(CREATE|PRAGMA)/i.test(stmt)) continue;
      await runAsync(stmt, []);
    }
  }

  async function getAllAsync(sql: string, params: any[] = []): Promise<any[]> {
    const m = /^SELECT payload FROM\s+(\w+)(?:\s+WHERE\s+(\w+)\s*=\s*\?)?/i.exec(sql);
    if (!m) throw new Error(`shim: unhandled SELECT: ${sql}`);
    const [, table, col] = m;
    const t = _t(table);
    const rows = col ? t.filter((r: any) => r[col] === params[0]) : t.slice();
    return rows.map((r: any) => ({ payload: r.payload }));
  }

  async function getFirstAsync(sql: string, params: any[] = []): Promise<any> {
    const rows = await getAllAsync(sql, params);
    return rows[0] || null;
  }

  async function withTransactionAsync(cb: () => Promise<void>): Promise<void> { await cb(); }

  // Expose a reset hook via a special SQL — call from beforeEach.
  return {
    openDatabaseAsync: jest.fn(async () => ({
      execAsync, runAsync, getAllAsync, getFirstAsync, withTransactionAsync,
    })),
    __resetTables: () => { for (const k of Object.keys(_tables)) delete _tables[k]; },
  };
});

import * as SQLite from "expo-sqlite";
import {
  initCache, cacheWeekJobs, getCachedWeekJobs, getCachedJob,
  cacheCustomer, getCachedCustomer,
  cacheProperty, getCachedProperty,
  cacheMe, getCachedMe,
  wipeCache, __resetForTests,
} from "@/src/lib/offline/cache";


beforeEach(() => {
  (SQLite as any).__resetTables();
  __resetForTests();
});


describe("offline cache · schema + jobs", () => {
  test("initCache is idempotent", async () => {
    await initCache();
    await initCache();
  });

  test("cacheWeekJobs + getCachedWeekJobs round-trip preserves payload", async () => {
    await initCache();
    await cacheWeekJobs("T1", [
      { id: "j1", tech_user_id: "T1", scheduled_date: "2026-03-15", customer_name: "A" },
      { id: "j2", tech_user_id: "T1", scheduled_date: "2026-03-16", customer_name: "B" },
    ]);
    const back = await getCachedWeekJobs("T1");
    expect(back.map((j: any) => j.id).sort()).toEqual(["j1", "j2"]);
    expect(back.find((j: any) => j.id === "j1")!.customer_name).toBe("A");
  });

  test("cacheWeekJobs replaces the tech's prior week (no ghost rows)", async () => {
    await initCache();
    await cacheWeekJobs("T1", [
      { id: "j1", tech_user_id: "T1", scheduled_date: "2026-03-15" },
      { id: "j2", tech_user_id: "T1", scheduled_date: "2026-03-16" },
    ]);
    await cacheWeekJobs("T1", [
      { id: "j1", tech_user_id: "T1", scheduled_date: "2026-03-15" },
      { id: "j3", tech_user_id: "T1", scheduled_date: "2026-03-17" },
    ]);
    const back = await getCachedWeekJobs("T1");
    expect(back.map((j: any) => j.id).sort()).toEqual(["j1", "j3"]);
  });

  test("getCachedJob returns a single job by id or null", async () => {
    await initCache();
    await cacheWeekJobs("T1", [{ id: "j9", tech_user_id: "T1", scheduled_date: "2026-03-15", note: "x" }]);
    expect((await getCachedJob("j9"))?.note).toBe("x");
    expect(await getCachedJob("nope")).toBeNull();
  });
});


describe("offline cache · customers / properties / me", () => {
  test("cacheCustomer round-trip", async () => {
    await initCache();
    await cacheCustomer({ id: "c1", first_name: "Robert" });
    expect((await getCachedCustomer("c1"))?.first_name).toBe("Robert");
    expect(await getCachedCustomer("nope")).toBeNull();
  });

  test("cacheProperty round-trip", async () => {
    await initCache();
    await cacheProperty({ id: "p1", customer_id: "c1", address: "1 Pool Ln" });
    const back = await getCachedProperty("p1");
    expect(back?.address).toBe("1 Pool Ln");
  });

  test("cacheMe round-trip", async () => {
    await initCache();
    await cacheMe({ id: "u1", role: "technician" });
    expect((await getCachedMe())?.role).toBe("technician");
  });
});


describe("offline cache · wipe", () => {
  test("wipeCache drops every table", async () => {
    await initCache();
    await cacheWeekJobs("T1", [{ id: "j1", tech_user_id: "T1", scheduled_date: "2026-03-15" }]);
    await cacheCustomer({ id: "c1", first_name: "A" });
    await cacheProperty({ id: "p1", customer_id: "c1" });
    await cacheMe({ id: "u1", role: "technician" });

    await wipeCache();

    expect(await getCachedWeekJobs("T1")).toEqual([]);
    expect(await getCachedCustomer("c1")).toBeNull();
    expect(await getCachedProperty("p1")).toBeNull();
    expect(await getCachedMe()).toBeNull();
  });
});
