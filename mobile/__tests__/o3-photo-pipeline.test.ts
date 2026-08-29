/**
 * Phase O3 · Photo capture pipeline tests.
 *
 * Covers:
 *   1. insertPendingPhoto → row in photos_pending table.
 *   2. flushPhotos uploads pending → marks uploaded → deletes local file.
 *   3. 3 failures → row marked stalled.
 *   4. retryStalled resets the photo for re-upload.
 *   5. purgePhotosForEntity removes all photos for deleted entity.
 *   6. cleanupUploaded removes all uploaded photos.
 *   7. getPhotosForEntity returns only photos for that entity.
 */

// ── In-memory SQLite shim ──────────────────────────────────────────
jest.mock("expo-sqlite", () => {
  const _tables: Record<string, any[]> = {};
  let _userVersion = 0;
  const _t = (n: string) => (_tables[n] = _tables[n] || []);

  function matchesWhere(row: any, whereClause: string, params: any[]): boolean {
    // Handle IN clauses
    const inMatch = /(\w+)\s+IN\s*\(([^)]+)\)/i.exec(whereClause);
    if (inMatch) {
      const col = inMatch[1];
      const vals = inMatch[2].split(",").map((v) => v.trim().replace(/^'|'$/g, ""));
      if (!vals.includes(row[col])) return false;
      // Check remaining conditions after IN
      const remaining = whereClause.replace(inMatch[0], "").replace(/^\s*AND\s*/i, "").trim();
      if (remaining) return matchesWhere(row, remaining, params);
      return true;
    }
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

// Mock expo-file-system/legacy
const mockDeleteAsync = jest.fn().mockResolvedValue(undefined);
const mockReadAsStringAsync = jest.fn().mockResolvedValue("dGVzdGltYWdlYmFzZTY0");
const mockGetInfoAsync = jest.fn().mockResolvedValue({ exists: true });
const mockMakeDirectoryAsync = jest.fn().mockResolvedValue(undefined);
const mockMoveAsync = jest.fn().mockResolvedValue(undefined);
jest.mock("expo-file-system/legacy", () => ({
  documentDirectory: "file:///data/app/docs/",
  EncodingType: { Base64: "base64", UTF8: "utf8" },
  deleteAsync: (...args: any[]) => mockDeleteAsync(...args),
  readAsStringAsync: (...args: any[]) => mockReadAsStringAsync(...args),
  getInfoAsync: (...args: any[]) => mockGetInfoAsync(...args),
  makeDirectoryAsync: (...args: any[]) => mockMakeDirectoryAsync(...args),
  moveAsync: (...args: any[]) => mockMoveAsync(...args),
}));

// Mock expo-image-manipulator
jest.mock("expo-image-manipulator", () => ({
  manipulateAsync: jest.fn().mockResolvedValue({ uri: "file:///tmp/manipulated.jpg" }),
  SaveFormat: { JPEG: "jpeg", PNG: "png" },
}));

// ── imports ────────────────────────────────────────────────────────
import * as SQLite from "expo-sqlite";
import { __resetForTests as resetDb } from "@/src/services/sync/db";
import { __clearForTests as clearQueue } from "@/src/services/sync/queue";
import {
  insertPendingPhoto,
  flushPhotos,
  retryStalled,
  retryAllStalled,
  getPendingPhotos,
  getStalledPhotos,
  getPhotosForEntity,
  purgePhotosForEntity,
  cleanupUploaded,
  __clearForTests as clearPhotos,
} from "@/src/services/sync/photoWorker";
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
  await clearPhotos();
  jest.clearAllMocks();
});

// ── tests ──────────────────────────────────────────────────────────
describe("Photo pipeline (Phase O3)", () => {
  it("insertPendingPhoto creates a row in photos_pending", async () => {
    await insertPendingPhoto("photo-1", "file:///staged/p1.jpg", "service_report", "sr-1");

    const pending = await getPendingPhotos();
    expect(pending).toHaveLength(1);
    expect(pending[0].id).toBe("photo-1");
    expect(pending[0].local_uri).toBe("file:///staged/p1.jpg");
    expect(pending[0].entity_type).toBe("service_report");
    expect(pending[0].entity_id).toBe("sr-1");
    expect(pending[0].upload_status).toBe("pending");
    expect(pending[0].upload_attempts).toBe(0);
  });

  it("flushPhotos uploads pending photos and marks uploaded", async () => {
    setOnline(true);
    mockApi.post.mockResolvedValueOnce({ ok: true });
    await insertPendingPhoto("photo-2", "file:///staged/p2.jpg", "job", "job-1");

    const result = await flushPhotos();
    expect(result.uploaded).toBe(1);
    expect(result.stalled).toBe(0);

    // Check mockApi.post was called with correct endpoint
    expect(mockApi.post).toHaveBeenCalledWith(
      "/jobs/job-1/photos",
      expect.objectContaining({
        data: expect.stringContaining("data:image/jpeg;base64,"),
        client_uuid: "photo-2",
      }),
      60000,
      expect.objectContaining({ "X-Idempotency-Key": "photo:photo-2" }),
    );

    // File should be deleted after successful upload
    expect(mockDeleteAsync).toHaveBeenCalledWith(
      "file:///staged/p2.jpg",
      expect.objectContaining({ idempotent: true }),
    );
  });

  it("3 upload failures mark photo as stalled", async () => {
    setOnline(true);
    mockApi.post.mockRejectedValue(new Error("Server error"));

    await insertPendingPhoto("photo-3", "file:///staged/p3.jpg", "job", "job-1");

    // Flush 3 times — each time it fails and increments upload_attempts
    await flushPhotos();
    await flushPhotos();
    await flushPhotos();

    const stalled = await getStalledPhotos();
    expect(stalled).toHaveLength(1);
    expect(stalled[0].id).toBe("photo-3");
    expect(stalled[0].upload_status).toBe("stalled");
    expect(stalled[0].upload_attempts).toBe(3);
    expect(stalled[0].last_error).toContain("Server error");
  });

  it("retryStalled resets a stalled photo for re-upload", async () => {
    setOnline(true);
    mockApi.post.mockRejectedValue(new Error("fail"));
    await insertPendingPhoto("photo-4", "file:///staged/p4.jpg", "job", "job-1");
    await flushPhotos(); await flushPhotos(); await flushPhotos();

    let stalled = await getStalledPhotos();
    expect(stalled).toHaveLength(1);

    // Retry — should reset to pending. Go offline to prevent auto-flush race.
    setOnline(false);
    await retryStalled("photo-4");

    stalled = await getStalledPhotos();
    expect(stalled).toHaveLength(0);

    const pending = await getPendingPhotos();
    expect(pending).toHaveLength(1);
    expect(pending[0].upload_attempts).toBe(0);
  });

  it("purgePhotosForEntity removes all photos for deleted entity", async () => {
    await insertPendingPhoto("pa", "file:///a.jpg", "job", "job-1");
    await insertPendingPhoto("pb", "file:///b.jpg", "job", "job-1");
    await insertPendingPhoto("pc", "file:///c.jpg", "job", "job-2");

    await purgePhotosForEntity("job-1");

    const remaining = await getPendingPhotos();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].entity_id).toBe("job-2");

    // Files should have been deleted
    expect(mockDeleteAsync).toHaveBeenCalledTimes(2);
  });

  it("cleanupUploaded removes all uploaded photos and files", async () => {
    setOnline(true);
    mockApi.post.mockResolvedValue({ ok: true });

    await insertPendingPhoto("pu1", "file:///u1.jpg", "job", "job-1");
    await insertPendingPhoto("pu2", "file:///u2.jpg", "job", "job-1");
    await flushPhotos();

    jest.clearAllMocks();
    const removed = await cleanupUploaded();
    expect(removed).toBe(2);
    expect(mockDeleteAsync).toHaveBeenCalledTimes(2);
  });

  it("getPhotosForEntity returns only photos for that entity", async () => {
    await insertPendingPhoto("x1", "file:///x1.jpg", "job", "job-1");
    await insertPendingPhoto("x2", "file:///x2.jpg", "job", "job-2");
    await insertPendingPhoto("x3", "file:///x3.jpg", "job", "job-1");

    const job1Photos = await getPhotosForEntity("job-1");
    expect(job1Photos).toHaveLength(2);
    expect(job1Photos.every((p) => p.entity_id === "job-1")).toBe(true);
  });

  it("empty photos — no rows when none inserted", async () => {
    const pending = await getPendingPhotos();
    expect(pending).toHaveLength(0);
    const stalled = await getStalledPhotos();
    expect(stalled).toHaveLength(0);
  });

  it("offline enqueue does not flush immediately", async () => {
    setOnline(false);
    await insertPendingPhoto("off-1", "file:///off.jpg", "job", "job-1");

    const pending = await getPendingPhotos();
    expect(pending).toHaveLength(1);
    expect(mockApi.post).not.toHaveBeenCalled();
  });
});
