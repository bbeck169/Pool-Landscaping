/**
 * Templates Library — Phase 3 (Mobile) · draft state + autosave + offline sync.
 *
 *  - Debounced autosave (750ms) + 15s safety-net flush when dirty.
 *  - Local snapshot written BEFORE every PATCH (`template_drafts:{id}`).
 *  - Network failure / offline → queued (`template_drafts_pending_sync:{id}`).
 *  - On open: server ⟵ local merge when the local snapshot is newer/unsynced.
 *  - Opens from the last cached copy when the device is offline.
 *  - Finalize is blocked while a pending sync exists for this instance.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState } from "react-native";
import { ApiError, ApiNetworkError } from "@/src/api";
import { getInstance, getDefinition, updateInstance, finalizeInstance } from "@/src/api/templates";
import {
  writeSnapshot, clearSnapshot, enqueuePending, removePending, hasPendingForInstance,
  mergeLocalOverServer, flushPendingTemplateDrafts, subscribeTemplateSync,
  cacheInstanceBundle, readInstanceBundle,
} from "@/src/utils/offlineTemplateDrafts";

export const AUTOSAVE_DEBOUNCE_MS = 750;
export const AUTOSAVE_INTERVAL_MS = 15000;

export type SaveState = "idle" | "saving" | "saved" | "offline" | "error";
export type FinalizeResult = { ok: boolean; reason?: "offline" | "pending" | "error"; message?: string };

export function useTemplateDraft(id: string, online: boolean) {
  const [instance, setInstance] = useState<any>(null);
  const [definition, setDefinition] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState("");
  const [lastSaved, setLastSaved] = useState<Date | null>(null);
  const [hasPending, setHasPending] = useState(false);
  const [loadedLocalEdits, setLoadedLocalEdits] = useState(false);
  const [fromCache, setFromCache] = useState(false);

  const instanceRef = useRef<any>(null);
  const definitionRef = useRef<any>(null);
  const dirtyRef = useRef(false);
  const savingRef = useRef(false);
  const againRef = useRef(false);
  const onlineRef = useRef(online);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hasPendingRef = useRef(false);
  onlineRef.current = online;
  hasPendingRef.current = hasPending;

  const commit = (next: any) => { instanceRef.current = next; setInstance(next); };

  const schedule = () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => { flushSave(); }, AUTOSAVE_DEBOUNCE_MS);
  };

  const flushSave = useCallback(async (): Promise<boolean> => {
    const inst = instanceRef.current;
    if (!inst || inst.status === "finalized" || !dirtyRef.current) return true;
    if (savingRef.current) { againRef.current = true; return false; }
    savingRef.current = true;
    dirtyRef.current = false;
    const title = inst.title || "";
    const values = inst.values || {};
    // 1. Snapshot BEFORE any network call.
    await writeSnapshot({ instance_id: inst.id, title, values, dirty_since: new Date().toISOString() });
    const queue = async (why: string) => {
      await enqueuePending({ instance_id: inst.id, title, values });
      setHasPending(true);
      setSaveState("offline");
      console.log(`[TemplateFill] ${why} — PATCH queued for ${inst.id}`);
    };
    try {
      if (!onlineRef.current) { await queue("offline"); return false; }
      setSaveState("saving");
      const updated = await updateInstance(inst.id, { title, values });
      // Keep local values — the user may have typed while the PATCH was in flight.
      const next = { ...instanceRef.current, updated_at: updated?.updated_at, status: updated?.status || "draft" };
      commit(next);
      if (!dirtyRef.current) await clearSnapshot(inst.id);
      await removePending(inst.id);
      cacheInstanceBundle(inst.id, next, definitionRef.current);
      setHasPending(false);
      setSaveError("");
      setSaveState("saved");
      setLastSaved(new Date());
      return true;
    } catch (e: any) {
      if (e instanceof ApiNetworkError) { await queue("network error"); return false; }
      if (e instanceof ApiError && e.status === 409) {
        await clearSnapshot(inst.id);
        await removePending(inst.id);
        setSaveError("This template was finalized elsewhere — reloading.");
        setSaveState("error");
        load();
        return false;
      }
      dirtyRef.current = true;
      setSaveError(e?.message || "Autosave failed.");
      setSaveState("error");
      return false;
    } finally {
      savingRef.current = false;
      if (againRef.current) { againRef.current = false; schedule(); }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    let inst: any;
    let defn: any;
    let cached = false;
    try {
      inst = await getInstance(id);
      defn = await getDefinition(inst.template_code);
      cacheInstanceBundle(id, inst, defn);
    } catch (e: any) {
      const bundle = e instanceof ApiNetworkError ? await readInstanceBundle(id) : null;
      if (!bundle) {
        setLoadError(e instanceof ApiNetworkError
          ? "You're offline and this template hasn't been opened on this device yet."
          : e?.message || "Failed to load template.");
        setLoading(false);
        return;
      }
      inst = bundle.instance;
      defn = bundle.definition;
      cached = true;
    }
    const { merged, hadLocalEdits } = await mergeLocalOverServer(inst);
    const pending = await hasPendingForInstance(id);
    definitionRef.current = defn;
    setDefinition(defn);
    commit(merged);
    setFromCache(cached);
    setLoadedLocalEdits(hadLocalEdits);
    setHasPending(pending);
    if (pending) {
      setSaveState("offline");
      if (onlineRef.current) flushPendingTemplateDrafts().catch(() => {});
    }
    if (hadLocalEdits && !pending && !cached) { dirtyRef.current = true; schedule(); }
    setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // 15s safety net (+ retry queued PATCHes when NetInfo missed the reconnect),
  // flush on background, flush on unmount.
  useEffect(() => {
    const iv = setInterval(() => {
      if (dirtyRef.current) flushSave();
      else if (hasPendingRef.current && onlineRef.current) flushPendingTemplateDrafts().catch(() => {});
    }, AUTOSAVE_INTERVAL_MS);
    const sub = AppState.addEventListener("change", (s) => { if (s !== "active") flushSave(); });
    return () => {
      clearInterval(iv);
      sub.remove();
      if (debounceRef.current) clearTimeout(debounceRef.current);
      flushSave();
    };
  }, [flushSave]);

  // Global queue flush → reflect in this screen.
  useEffect(() => subscribeTemplateSync((r) => {
    if (r.syncedIds.includes(id)) {
      setHasPending(false);
      setLoadedLocalEdits(false);
      setSaveState("saved");
      setLastSaved(new Date());
    }
    if (r.droppedIds.includes(id)) load();
  }), [id, load]);

  // Reconnect (offline → online) → replay queue (FIFO) + push anything typed while offline.
  useEffect(() => {
    if (!online) return;
    if (hasPendingRef.current) flushPendingTemplateDrafts().catch(() => {});
    if (dirtyRef.current) flushSave();
  }, [online, flushSave]);

  const edit = (patch: Record<string, any>) => {
    const cur = instanceRef.current;
    if (!cur || cur.status === "finalized") return;
    commit({ ...cur, ...patch });
    dirtyRef.current = true;
    schedule();
  };
  const setValue = (key: string, val: any) => edit({ values: { ...(instanceRef.current?.values || {}), [key]: val } });
  const setTitle = (title: string) => edit({ title });

  const canFinalize = async (): Promise<FinalizeResult> => {
    if (!onlineRef.current) return { ok: false, reason: "offline", message: "You're offline. Reconnect to finalize this template." };
    await flushSave();
    if (await hasPendingForInstance(id)) {
      setHasPending(true);
      return { ok: false, reason: "pending", message: "You have unsynced changes. Reconnect so they can sync before finalizing." };
    }
    return { ok: true };
  };

  const finalize = async (): Promise<FinalizeResult> => {
    const gate = await canFinalize();
    if (!gate.ok) return gate;
    try {
      const updated = await finalizeInstance(id);
      commit(updated);
      await Promise.all([clearSnapshot(id), removePending(id)]);
      cacheInstanceBundle(id, updated, definitionRef.current);
      setLoadedLocalEdits(false);
      return { ok: true };
    } catch (e: any) {
      return { ok: false, reason: "error", message: e?.message || "Could not finalize." };
    }
  };

  return {
    instance, definition, loading, loadError, saveState, saveError, lastSaved, hasPending,
    loadedLocalEdits, fromCache, setLoadedLocalEdits, setValue, setTitle, flushSave, canFinalize, finalize, reload: load,
  };
}
