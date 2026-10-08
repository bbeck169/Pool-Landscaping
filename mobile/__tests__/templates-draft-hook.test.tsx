/**
 * Templates Library — Phase 3 (Mobile) · useTemplateDraft autosave + offline.
 *
 * - 750ms debounce → PATCH; snapshot written BEFORE PATCH.
 * - Offline edit → snapshot + pending queue, no PATCH, saveState "offline".
 * - Network error mid-PATCH → queued.
 * - Load merges a newer local snapshot + flags loadedLocalEdits.
 * - Opens from cached bundle when offline.
 * - Finalize blocked while pending / offline; allowed after sync.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { renderHook, act, waitFor } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPatch = jest.fn();
const mockPost = jest.fn();
jest.mock("@/src/api", () => {
  class ApiNetworkError extends Error { kind = "network"; }
  class ApiError extends Error { status: number; constructor(m: string, s: number) { super(m); this.status = s; } }
  return {
  api: {
    get: (...a: any[]) => mockGet(...a),
    patch: (...a: any[]) => mockPatch(...a),
    post: (...a: any[]) => mockPost(...a),
    del: jest.fn(),
  },
  api_base: () => "http://x/api",
  getAuthToken: async () => "tok",
  ApiNetworkError,
  ApiError,
};
});
const { ApiNetworkError: MockNetErr, ApiError: MockHttpErr } = jest.requireMock("@/src/api");
jest.mock("expo/fetch", () => ({ fetch: jest.fn() }));
jest.mock("expo-file-system", () => ({ File: jest.fn(), Paths: { cache: "/cache" } }));
jest.mock("expo-sharing", () => ({ isAvailableAsync: jest.fn(), shareAsync: jest.fn() }));

import { useTemplateDraft, AUTOSAVE_DEBOUNCE_MS } from "@/src/screens/templates/useTemplateDraft";
import { readSnapshot, hasPendingForInstance, writeSnapshot, cacheInstanceBundle, enqueuePending } from "@/src/utils/offlineTemplateDrafts";

const INST = { id: "i1", template_code: "log", title: "Log", status: "draft", updated_at: "2026-01-01T10:00:00.000Z", values: { a: "1" } };
const DEF = { code: "log", category: "operations_checklists", schema: [{ title: "S", fields: [{ key: "a", type: "text", label: "A" }] }] };

function serverOK() {
  mockGet.mockImplementation(async (p: string) => (p.startsWith("/templates/instances/") ? { ...INST } : DEF));
}

beforeEach(async () => {
  await AsyncStorage.clear();
  mockGet.mockReset(); mockPatch.mockReset(); mockPost.mockReset();
  jest.spyOn(console, "log").mockImplementation(() => {});
  jest.useRealTimers();
});

async function mount(online = true) {
  const hook = renderHook(({ on }) => useTemplateDraft("i1", on), { initialProps: { on: online } });
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
  return hook;
}

it("debounces edits 750ms, writes snapshot BEFORE PATCH, then shows Saved", async () => {
  serverOK();
  mockPatch.mockImplementation(async () => {
    // snapshot must already exist at PATCH time
    expect((await readSnapshot("i1"))?.values).toEqual({ a: "2" });
    return { ...INST, values: { a: "2" }, updated_at: "2026-01-01T10:05:00.000Z" };
  });
  const { result } = await mount();
  jest.useFakeTimers();
  act(() => { result.current.setValue("a", "2"); });
  act(() => { jest.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS - 50); });
  expect(mockPatch).not.toHaveBeenCalled();
  await act(async () => { jest.advanceTimersByTime(60); });
  jest.useRealTimers();
  await waitFor(() => expect(result.current.saveState).toBe("saved"));
  expect(mockPatch).toHaveBeenCalledWith("/templates/instances/i1", { title: "Log", values: { a: "2" } });
  expect(result.current.lastSaved).toBeInstanceOf(Date);
  expect(await readSnapshot("i1")).toBeNull();
  expect(result.current.instance.values).toEqual({ a: "2" });
});

it("offline edit → snapshot + pending queue, no PATCH, indicator 'offline'", async () => {
  serverOK();
  const { result } = await mount(false);
  act(() => { result.current.setValue("a", "offline-edit"); });
  await act(async () => { await result.current.flushSave(); });
  expect(mockPatch).not.toHaveBeenCalled();
  expect(result.current.saveState).toBe("offline");
  expect(result.current.hasPending).toBe(true);
  expect((await readSnapshot("i1"))?.values).toEqual({ a: "offline-edit" });
  const raw = JSON.parse((await AsyncStorage.getItem("template_drafts_pending_sync:i1")) as string);
  expect(raw.values).toEqual({ a: "offline-edit" });
});

it("network error during PATCH → queued for sync", async () => {
  serverOK();
  mockPatch.mockRejectedValue(new MockNetErr("Network error"));
  const { result } = await mount();
  act(() => { result.current.setValue("a", "x"); });
  await act(async () => { await result.current.flushSave(); });
  expect(mockPatch).toHaveBeenCalledTimes(1);
  expect(result.current.saveState).toBe("offline");
  expect(await hasPendingForInstance("i1")).toBe(true);
});

it("merges newer local snapshot on load and flags the soft warning", async () => {
  serverOK();
  await writeSnapshot({ instance_id: "i1", title: "Local title", values: { a: "local" }, dirty_since: "2026-01-02T00:00:00.000Z" });
  await enqueuePending({ instance_id: "i1", title: "Local title", values: { a: "local" } });
  const { result } = await mount(false);
  expect(result.current.loadedLocalEdits).toBe(true);
  expect(result.current.instance.values.a).toBe("local");
  expect(result.current.instance.title).toBe("Local title");
  expect(result.current.hasPending).toBe(true);
});

it("opens from cached bundle when the device is offline", async () => {
  await cacheInstanceBundle("i1", INST, DEF);
  mockGet.mockRejectedValue(new MockNetErr("offline"));
  const { result } = await mount(false);
  expect(result.current.fromCache).toBe(true);
  expect(result.current.definition.code).toBe("log");
  expect(result.current.loadError).toBe("");
});

it("shows a clear error when offline and never opened on this device", async () => {
  mockGet.mockRejectedValue(new MockNetErr("offline"));
  const { result } = await mount(false);
  expect(result.current.loadError).toMatch(/offline/i);
});

it("finalize is BLOCKED while a pending sync exists, and while offline", async () => {
  serverOK();
  await enqueuePending({ instance_id: "i1", title: "Log", values: { a: "q" } });
  mockPatch.mockRejectedValue(new MockNetErr("still flaky"));
  const offline = await mount(false);
  const r1 = await offline.result.current.canFinalize();
  expect(r1).toMatchObject({ ok: false, reason: "offline" });
  offline.unmount();

  const online = await mount(true);
  let r2: any;
  await act(async () => { r2 = await online.result.current.finalize(); });
  expect(r2).toMatchObject({ ok: false, reason: "pending" });
  expect(mockPost).not.toHaveBeenCalled();
});

it("finalize succeeds when synced and makes the instance read-only", async () => {
  serverOK();
  mockPost.mockResolvedValue({ ...INST, status: "finalized" });
  const { result } = await mount(true);
  let r: any;
  await act(async () => { r = await result.current.finalize(); });
  expect(r).toEqual({ ok: true });
  expect(mockPost).toHaveBeenCalledWith("/templates/instances/i1/finalize");
  expect(result.current.instance.status).toBe("finalized");
  act(() => { result.current.setValue("a", "ignored"); });
  expect(result.current.instance.values.a).toBe("1");
});

it("409 on autosave (finalized elsewhere) reloads instead of queueing", async () => {
  serverOK();
  mockPatch.mockRejectedValue(new MockHttpErr("Cannot edit a finalized instance", 409));
  const { result } = await mount();
  act(() => { result.current.setValue("a", "z"); });
  await act(async () => { await result.current.flushSave(); });
  expect(await hasPendingForInstance("i1")).toBe(false);
  await waitFor(() => expect(mockGet.mock.calls.filter((c) => c[0] === "/templates/instances/i1").length).toBeGreaterThanOrEqual(2));
});

it("reconnect (offline → online) auto-syncs the queued PATCH and clears the indicator", async () => {
  serverOK();
  const hook = await mount(false);
  act(() => { hook.result.current.setValue("a", "typed-offline"); });
  await act(async () => { await hook.result.current.flushSave(); });
  expect(hook.result.current.hasPending).toBe(true);
  mockPatch.mockResolvedValue({ ...INST, values: { a: "typed-offline" } });
  hook.rerender({ on: true });
  await waitFor(() => expect(hook.result.current.hasPending).toBe(false));
  expect(mockPatch).toHaveBeenCalledWith("/templates/instances/i1", { title: "Log", values: { a: "typed-offline" } });
  expect(await hasPendingForInstance("i1")).toBe(false);
  expect(await readSnapshot("i1")).toBeNull();
  expect(hook.result.current.saveState).toBe("saved");
});

it("retries queued PATCHes on the 15s tick even if NetInfo never reported a reconnect", async () => {
  serverOK();
  mockPatch.mockRejectedValueOnce(new MockNetErr("blip"));
  jest.useFakeTimers();
  const hook = await mount(true);
  act(() => { hook.result.current.setValue("a", "blip-edit"); });
  await act(async () => { await hook.result.current.flushSave(); });
  expect(hook.result.current.hasPending).toBe(true);
  mockPatch.mockResolvedValue({ ...INST, values: { a: "blip-edit" } });
  await act(async () => { jest.advanceTimersByTime(15000); });
  jest.useRealTimers();
  await waitFor(() => expect(hook.result.current.hasPending).toBe(false));
  expect(mockPatch).toHaveBeenCalledTimes(2);
  expect(await hasPendingForInstance("i1")).toBe(false);
});
