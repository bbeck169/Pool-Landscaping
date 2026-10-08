/**
 * Templates Library — Phase 3 (Mobile) · offline draft storage + sync.
 *
 * Covers: spec storage keys, snapshot CRUD, FIFO pending queue, flush
 * success / still-offline / 4xx-drop / 5xx-keep, concurrent-enqueue guard,
 * local-over-server merge rules, and sync event emission.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

const mockPatch = jest.fn();
jest.mock("@/src/api", () => {
  class ApiNetworkError extends Error { kind = "network"; }
  class ApiError extends Error { status: number; constructor(m: string, s: number) { super(m); this.status = s; } }
  return {
  api: { patch: (...a: any[]) => mockPatch(...a) },
  ApiNetworkError,
  ApiError,
};
});
const { ApiNetworkError: MockNetErr, ApiError: MockHttpErr } = jest.requireMock("@/src/api");

import {
  snapshotKey, pendingKey, writeSnapshot, readSnapshot, clearSnapshot,
  enqueuePending, getPendingQueue, hasPendingForInstance, pendingCount,
  flushPendingTemplateDrafts, mergeLocalOverServer, subscribeTemplateSync,
  cacheInstanceBundle, readInstanceBundle,
} from "@/src/utils/offlineTemplateDrafts";

beforeEach(async () => {
  await AsyncStorage.clear();
  mockPatch.mockReset();
  jest.spyOn(console, "log").mockImplementation(() => {});
  jest.spyOn(console, "warn").mockImplementation(() => {});
});

describe("storage keys (spec)", () => {
  it("uses template_drafts:{id} and template_drafts_pending_sync:{id}", () => {
    expect(snapshotKey("abc")).toBe("template_drafts:abc");
    expect(pendingKey("abc")).toBe("template_drafts_pending_sync:abc");
  });

  it("writes the snapshot under the spec key", async () => {
    await writeSnapshot({ instance_id: "i1", title: "T", values: { a: 1 }, dirty_since: "2026-01-01T00:00:00.000Z" });
    const raw = await AsyncStorage.getItem("template_drafts:i1");
    expect(JSON.parse(raw as string)).toMatchObject({ instance_id: "i1", values: { a: 1 } });
    expect(await readSnapshot("i1")).toMatchObject({ title: "T" });
    await clearSnapshot("i1");
    expect(await readSnapshot("i1")).toBeNull();
  });

  it("caches instance+definition bundle for offline open", async () => {
    await cacheInstanceBundle("i1", { id: "i1" }, { code: "c" });
    expect(await readInstanceBundle("i1")).toEqual({ instance: { id: "i1" }, definition: { code: "c" } });
  });
});

describe("pending queue", () => {
  it("enqueues under per-instance key and keeps first-enqueue ts on re-queue", async () => {
    await enqueuePending({ instance_id: "i1", title: "a", values: { x: 1 }, ts: "2026-01-01T00:00:00.000Z" });
    await enqueuePending({ instance_id: "i1", title: "b", values: { x: 2 }, ts: "2026-01-02T00:00:00.000Z" });
    const raw = JSON.parse((await AsyncStorage.getItem("template_drafts_pending_sync:i1")) as string);
    expect(raw.ts).toBe("2026-01-01T00:00:00.000Z");
    expect(raw.values).toEqual({ x: 2 });
    expect(raw.title).toBe("b");
    expect(await pendingCount()).toBe(1);
    expect(await hasPendingForInstance("i1")).toBe(true);
    expect(await hasPendingForInstance("nope")).toBe(false);
  });

  it("returns entries in FIFO order by first-enqueue ts", async () => {
    await enqueuePending({ instance_id: "late", title: "", values: {}, ts: "2026-03-01T00:00:00.000Z" });
    await enqueuePending({ instance_id: "early", title: "", values: {}, ts: "2026-01-01T00:00:00.000Z" });
    await enqueuePending({ instance_id: "mid", title: "", values: {}, ts: "2026-02-01T00:00:00.000Z" });
    await AsyncStorage.setItem("unrelated_key", "1");
    expect((await getPendingQueue()).map((e) => e.instance_id)).toEqual(["early", "mid", "late"]);
  });
});

describe("flushPendingTemplateDrafts", () => {
  const seed = async () => {
    await enqueuePending({ instance_id: "a", title: "A", values: { v: 1 }, ts: "2026-01-01T00:00:00.000Z" });
    await enqueuePending({ instance_id: "b", title: "B", values: { v: 2 }, ts: "2026-01-02T00:00:00.000Z" });
    await writeSnapshot({ instance_id: "a", title: "A", values: { v: 1 }, dirty_since: "2026-01-01T00:00:00.000Z" });
  };

  it("PATCHes FIFO, then clears pending + snapshot on success and emits event", async () => {
    await seed();
    mockPatch.mockResolvedValue({});
    const evt = jest.fn();
    const unsub = subscribeTemplateSync(evt);
    const r = await flushPendingTemplateDrafts();
    unsub();
    expect(mockPatch.mock.calls.map((c) => c[0])).toEqual(["/templates/instances/a", "/templates/instances/b"]);
    expect(mockPatch.mock.calls[0][1]).toEqual({ title: "A", values: { v: 1 } });
    expect(r).toMatchObject({ synced: 2, remaining: 0, syncedIds: ["a", "b"] });
    expect(await readSnapshot("a")).toBeNull();
    expect(evt).toHaveBeenCalledWith(expect.objectContaining({ syncedIds: ["a", "b"] }));
  });

  it("stops at the first network error and keeps the rest queued (FIFO preserved)", async () => {
    await seed();
    mockPatch.mockRejectedValueOnce(new MockNetErr("offline"));
    const r = await flushPendingTemplateDrafts();
    expect(mockPatch).toHaveBeenCalledTimes(1);
    expect(r).toMatchObject({ synced: 0, remaining: 2 });
    expect((await getPendingQueue()).map((e) => e.instance_id)).toEqual(["a", "b"]);
    expect(await readSnapshot("a")).not.toBeNull();
  });

  it("drops entries on 4xx (e.g. 409 finalized elsewhere) and continues", async () => {
    await seed();
    mockPatch.mockRejectedValueOnce(new MockHttpErr("Cannot edit a finalized instance", 409)).mockResolvedValueOnce({});
    const r = await flushPendingTemplateDrafts();
    expect(r).toMatchObject({ synced: 1, remaining: 0, droppedIds: ["a"], syncedIds: ["b"] });
    expect(await readSnapshot("a")).toBeNull();
  });

  it("keeps entries on 5xx for the next attempt", async () => {
    await seed();
    mockPatch.mockRejectedValueOnce(new MockHttpErr("boom", 503)).mockResolvedValueOnce({});
    const r = await flushPendingTemplateDrafts();
    expect(r.remaining).toBe(1);
    expect(await hasPendingForInstance("a")).toBe(true);
  });

  it("does not drop a newer edit queued while the PATCH was in flight", async () => {
    await enqueuePending({ instance_id: "a", title: "A", values: { v: 1 }, ts: "2026-01-01T00:00:00.000Z" });
    mockPatch.mockImplementationOnce(async () => {
      await enqueuePending({ instance_id: "a", title: "A2", values: { v: 9 }, ts: "2026-01-05T00:00:00.000Z" });
      return {};
    });
    await flushPendingTemplateDrafts();
    const q = await getPendingQueue();
    expect(q).toHaveLength(1);
    expect(q[0].values).toEqual({ v: 9 });
  });
});

describe("mergeLocalOverServer", () => {
  const server = { id: "i1", status: "draft", title: "Server", updated_at: "2026-01-01T10:00:00.000Z", values: { a: 1, b: 1 } };

  it("merges local values on top when local snapshot is newer", async () => {
    await writeSnapshot({ instance_id: "i1", title: "Local", values: { b: 2 }, dirty_since: "2026-01-01T11:00:00.000Z" });
    const { merged, hadLocalEdits } = await mergeLocalOverServer(server);
    expect(hadLocalEdits).toBe(true);
    expect(merged.title).toBe("Local");
    expect(merged.values).toEqual({ a: 1, b: 2 });
  });

  it("keeps server + clears stale snapshot when server is newer and nothing pending", async () => {
    await writeSnapshot({ instance_id: "i1", title: "Old", values: { b: 0 }, dirty_since: "2026-01-01T09:00:00.000Z" });
    const { merged, hadLocalEdits } = await mergeLocalOverServer(server);
    expect(hadLocalEdits).toBe(false);
    expect(merged).toBe(server);
    expect(await readSnapshot("i1")).toBeNull();
  });

  it("treats an unsynced pending entry as local-wins even with clock skew", async () => {
    await writeSnapshot({ instance_id: "i1", title: "Skewed", values: { b: 5 }, dirty_since: "2026-01-01T09:00:00.000Z" });
    await enqueuePending({ instance_id: "i1", title: "Skewed", values: { b: 5 } });
    const { merged, hadLocalEdits } = await mergeLocalOverServer(server);
    expect(hadLocalEdits).toBe(true);
    expect(merged.values.b).toBe(5);
  });

  it("discards local edits for a finalized server instance", async () => {
    await writeSnapshot({ instance_id: "i1", title: "L", values: { b: 9 }, dirty_since: "2026-02-01T00:00:00.000Z" });
    await enqueuePending({ instance_id: "i1", title: "L", values: { b: 9 } });
    const { hadLocalEdits } = await mergeLocalOverServer({ ...server, status: "finalized" });
    expect(hadLocalEdits).toBe(false);
    expect(await hasPendingForInstance("i1")).toBe(false);
  });

  it("returns server untouched when no snapshot exists", async () => {
    const { merged, hadLocalEdits } = await mergeLocalOverServer(server);
    expect(hadLocalEdits).toBe(false);
    expect(merged).toBe(server);
  });
});
