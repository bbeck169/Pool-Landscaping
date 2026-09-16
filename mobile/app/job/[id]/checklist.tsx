/**
 * Phase 31 · Step 2a — Tap-Job → Checklist route (Expo mobile).
 *
 * Path: /job/{id}/checklist  (Expo Router; `(app)` is a route group).
 * Entry point when a tech (or admin) taps a job on the mobile Schedule
 * (Grid or Calendar). Reuses ONLY endpoints verified in Step 1
 * discovery — no invented endpoints:
 *
 *   GET   /api/jobs/{id}                        — job hydration for the resolver
 *   GET   /api/jobs/{id}/service-report         — bootstrap (auto-provisions)
 *   PATCH /api/jobs/{id}/service-report         — autosave (debounced 800 ms)
 *   POST  /api/jobs/{id}/service-report/submit  — close/submit
 *   POST  /api/jobs/{id}/photos                 — PhotoUploader
 *   POST  /api/service-report/analyze-water-photo — inside PoolChecklistForm
 *   POST  /api/workstream/events                — telemetry on close
 *
 * The client-side template picker is `getChecklistType(job)` (shared
 * helper at `mobile/src/utils/checklistType.ts`). The BACKEND template
 * is what actually drives the field shapes (readings, catalog, checklist
 * items) via the service-report bootstrap; the client resolver only
 * decides which UI shell to mount around those fields.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Alert,
  Share, Modal, TouchableOpacity,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { usePreventRemove } from "@react-navigation/core";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import * as Clipboard from "expo-clipboard";

import { api, ApiError } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { mapApiError, errorKindIcon } from "@/src/utils/mapApiError";
import { Header } from "@/src/components/widgets";
// Feb-2026 · Phase 1 offline foundation — cache customer on the
// close-out lookup + surface the offline pill in the header.
// Phase M5 — offline apiCache imports removed (recap customer-fetch eliminated).
import OfflineBadge from "@/src/components/OfflineBadge";
import { getChecklistType, ChecklistType } from "@/src/utils/checklistType";
import ServiceReportMediaUploader from "@/src/components/checklist/ServiceReportMediaUploader";
import type { SRMedia } from "@/src/api/serviceReportMedia";
import PhotoUploader from "@/src/components/checklist/PhotoUploader";
import PoolChecklistForm from "@/src/components/checklist/PoolChecklistForm";
import LandscapingChecklistForm from "@/src/components/checklist/LandscapingChecklistForm";
import GenericChecklistForm from "@/src/components/checklist/GenericChecklistForm";
// Phase M5 — VisitRecapModal removed from this screen; recap prompt skipped.
import WaterBodyManager from "@/src/components/checklist/WaterBodyManager";
import { WaterBody, makeEmptyBody, missingRequiredReadings } from "@/src/lib/waterBodies";
import { expandChemistryLabel } from "@/src/lib/expandChemistryLabel";
import { retryWithBackoff } from "@/src/services/retryWithBackoff";
import ChecklistSavePill, { type SavePillState } from "@/src/components/sync/ChecklistSavePill";
import { cacheJobBootstrap, getCachedBootstrap } from "@/src/services/offlineCache";
// Phase 1 Offline Read — hydrator cache for offline-first bootstrap.
import { getCachedJobBootstrap, CK } from "@/src/services/routeHydrator";
import { writeCache } from "@/src/services/readCache";
import * as writeQueue from "@/src/services/writeQueue";
import { submitOffline, cacheServiceReport } from "@/src/services/sync/offlineServiceLog";
import { offlineWrite } from "@/src/services/offlineWrite";
import { capturePhoto, getPhotosForEntity, purgePhotosForEntity, type PendingPhoto as SyncPendingPhoto } from "@/src/services/sync/photoWorker";
import { useOnline } from "@/src/offline";
import VideoMediaUploader from "@/src/components/media/VideoMediaUploader";
import { formatCustomerName } from "@/src/utils/formatCustomerName";

const AUTOSAVE_DEBOUNCE_MS = 800;
// Phase 37 — minimum time the pill stays on "Saving…" so techs actually
// see the transition after a chip tap on the mobile checklist.
const MIN_SAVING_MS = 400;
const PHOTO_CAP = 10;

// Phase 50.B — Return the display names of any reading whose current
// value is more than 2× or less than 0.5× the rolling median of the
// last 4 submitted values for the same customer.
async function _mobileComputeOutlierNames(report: any, job: any): Promise<string[]> {
  const customerId = job?.customer_id || report?.job?.customer_id;
  if (!customerId) return [];
  const readings = report?.chemical_readings || [];
  if (!readings.length) return [];
  const res: any = await api.get(`/service-reports/last-readings?customer_id=${customerId}`);
  const recentMap: Record<string, number[]> = res?.recent_readings || {};
  const outliers: string[] = [];
  for (const r of readings) {
    const val = Number(r?.value);
    if (!isFinite(val) || val <= 0) continue;
    const key = String(r?.key || r?.name || "").toLowerCase();
    const arr = (recentMap[key] || recentMap[r?.key] || recentMap[r?.name] || [])
      .filter((x: number) => isFinite(x));
    if (arr.length < 2) continue;
    const sorted = [...arr].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    const median = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
    if (!median) continue;
    if (val > 2 * median || val < 0.5 * median) {
      outliers.push(r?.name || key);
    }
  }
  return outliers;
}

export default function JobChecklistScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { showToast } = useToast();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();

  const role = user?.role || "";
  const canWrite = role === "admin" || role === "super_admin" || role === "technician";

  const [job, setJob] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  // Phase 44 · Fix C — the autosave debounce timer needs to read the
  // LATEST `report` value at flush time, not the one closed-over when
  // `flushSave` was memoized. Without this ref, a rapid Add-chemical →
  // wait-1500ms sequence PATCHes the pre-Add state and the chemical
  // silently disappears after reload. See HANDOFF.md notes on stale
  // closure state in checklist autosave.
  const reportRef = useRef<any>(null);
  const [loading, setLoading] = useState(true);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [submitting, setSubmitting] = useState(false);
  // P0 429 fix — unified pill state + retry tracking.
  const [pillState, setPillState] = useState<SavePillState>({ kind: "synced" });
  const [closeJobError, setCloseJobError] = useState<string | null>(null);
  const [bootstrapError, setBootstrapError] = useState<unknown>(null);
  const closeJobPayloadRef = useRef<any>(null);
  // P0 Close-Job silent no-op fix — in-tree Modals replace Alert.alert
  // which silently no-ops on iOS 17 + Hermes (detached UIScene bug).
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);
  const [showOutlierWarning, setShowOutlierWarning] = useState(false);
  const [outlierNames, setOutlierNames] = useState<string[]>([]);

  // Phase C1 · Dirty-close guard state.
  const [dirtyCloseOpen, setDirtyCloseOpen] = useState(false);
  const [saveAndClosing, setSaveAndClosing] = useState(false);
  // Stores the prevented navigation action to replay after discard/save.
  const preventedNavRef = useRef<{ data: { action: any } } | null>(null);

  const dirtyRef = useRef(false);
  const savingRef = useRef(false);
  const autosaveTimer = useRef<any>(null);
  // Phase 37 — timestamp of when "Saving…" was first shown, used for the
  // min-hold that keeps the pill visible long enough to be perceived.
  const savingShownAtRef = useRef<number>(0);

  // Phase 40 · Step 1 — track whether the current bootstrap came from
  // the offline cache so the tech sees an honest "Offline mode" banner.
  const [offlineMode, setOfflineMode] = useState(false);

  // Phase 27 · Service-report media state (photos + videos via /api/service-reports/{id}/media)
  const [srPhotos, setSrPhotos] = useState<SRMedia[]>([]);
  const [srVideos, setSrVideos] = useState<SRMedia[]>([]);

  // Phase v · Multi-body service reports — water_bodies[] state.
  const [waterBodies, setWaterBodies] = useState<WaterBody[]>([]);
  const waterBodiesRef = useRef<WaterBody[]>([]);
  // Maps body index → list of missing reading keys for 422 highlight.
  const [highlightBodies, setHighlightBodies] = useState<Record<number, string[]>>({});

  // Phase 40 · Step 2 — live write-queue + connectivity state. Drives the
  // expanded checklist-network-pill (Online / Syncing… / Offline+N / Sync
  // error). `useOnline` subscribes to `@react-native-community/netinfo`.
  const online = useOnline();
  const [queueState, setQueueState] = useState<writeQueue.QueueState>({
    count: 0, syncing: false, lastError: undefined,
  });
  const wasOnlineRef = useRef<boolean>(true);

  useEffect(() => {
    const unsub = writeQueue.subscribe(setQueueState);
    return () => { unsub(); };
  }, []);

  // Auto-flush on offline → online transition. Also flush once on mount
  // in case entries from a previous session are still waiting.
  useEffect(() => {
    if (online && !wasOnlineRef.current) {
      writeQueue.flush().catch(() => {});
    }
    wasOnlineRef.current = online;
  }, [online]);
  useEffect(() => { writeQueue.flush().catch(() => {}); }, []);

  // ── Unified pill derivation ─────────────────────────────────────────
  // Priority: saving > retrying > exhausted > syncing > error > offline > synced
  useEffect(() => {
    // During active save or close-job, saveState drives the pill
    // (retrying/exhausted set directly by retryWithBackoff callbacks).
    if (saveState === "saving") {
      setPillState({ kind: "saving" });
      return;
    }
    // After save success or error, derive from queue + online state
    const queued = queueState.count;
    const isSyncing = queueState.syncing;
    if (isSyncing) {
      setPillState({ kind: "saving" });
    } else if (!online) {
      setPillState({ kind: "offline", queuedCount: queued });
    } else if (queued > 0) {
      setPillState({ kind: "saving" }); // about to drain
    } else if (saveState === "error") {
      // error state without active retry = exhausted
      // (but this is transient; retryWithBackoff sets exhausted directly)
    } else {
      setPillState({ kind: "synced" });
    }
  }, [saveState, online, queueState]);

  // ─── Load ───────────────────────────────────────────────────────────
  //
  // M5 hardening — per-status-code error UX for the bootstrap fetch.
  // 429: retry once after 1s → cache fallback → "Server busy" alert.
  // 401/403: "Please sign in again" → route to login.
  // 5xx: "Something went wrong" with a Retry button.
  // Other: generic message from backend response body.
  // All failures are logged to telemetry (best-effort, no retry storm).
  //
  const _logBootstrapFailure = useCallback(async (
    endpoint: string, status: number | null, message: string,
  ) => {
    try {
      await api.post("/telemetry/mobile-crash", {
        crash: {
          message: `Checklist bootstrap error: ${endpoint} → ${status ?? "network"}: ${message}`,
          stack: new Error().stack?.slice(0, 500) || "",
        },
        context: {
          screen: "checklist",
          job_id: id,
          user_id: user?.id,
          endpoint,
          status,
        },
      });
    } catch {
      // Best-effort — if telemetry itself 429s, drop silently.
    }
  }, [id, user?.id]);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);

    const bootstrap = async () => Promise.all([
      api.get(`/jobs/${id}`),
      api.get(`/jobs/${id}/service-report`),
    ]);

    try {
      const [jobResp, reportResp] = await bootstrap();
      setJob(jobResp);
      setReport(reportResp);
      reportRef.current = reportResp;
      setOfflineMode(false);
      setBootstrapError(null);
      // Cache the bootstrap for later offline access (both stores).
      await cacheJobBootstrap(String(id), { job: jobResp, report: reportResp });
      await writeCache(CK.jobBootstrap(String(id)), { job: jobResp, report: reportResp }).catch(() => {});
      // Phase O3 · Also cache in SQLite for offline service-log.
      await cacheServiceReport(String(id), reportResp).catch(() => {});
    } catch (e: any) {
      const isApiErr = e instanceof ApiError;
      const status: number | null = isApiErr ? e.status : null;
      const msg = e?.message || "Unknown error";
      setBootstrapError(e);

      // Log to telemetry (best-effort)
      _logBootstrapFailure(`/jobs/${id}+service-report`, status, msg);

      // ── 429 — retry once after 1s backoff ──────────────────────────
      if (status === 429) {
        try {
          await new Promise((r) => setTimeout(r, 1000));
          const [jobResp, reportResp] = await bootstrap();
          setJob(jobResp);
          setReport(reportResp);
          reportRef.current = reportResp;
          setOfflineMode(false);
          await cacheJobBootstrap(String(id), { job: jobResp, report: reportResp });
          await cacheServiceReport(String(id), reportResp).catch(() => {});
          setLoading(false);
          return; // retry succeeded
        } catch {
          // retry failed — fall through to cache
        }
        // Try cache fallback — hydrator SQLite first, then AsyncStorage.
        let cached = await getCachedJobBootstrap(String(id)).catch(() => null);
        if (!cached?.report) cached = await getCachedBootstrap(String(id));
        if (cached?.job && cached?.report) {
          setJob(cached.job);
          setReport(cached.report);
          reportRef.current = cached.report;
          setOfflineMode(true);
        } else {
          Alert.alert("Server busy", "Try again in a moment.");
        }
        setLoading(false);
        return;
      }

      // ── 401 / 403 — route to login ────────────────────────────────
      if (status === 401 || status === 403) {
        Alert.alert(
          "Session expired",
          "Please sign in again.",
          [{ text: "Sign in", onPress: () => router.replace("/login") }],
        );
        setLoading(false);
        return;
      }

      // ── 5xx — server error with Retry ──────────────────────────────
      if (status && status >= 500) {
        Alert.alert(
          "Something went wrong",
          "Try again later.",
          [
            { text: "Cancel", style: "cancel" },
            { text: "Retry", onPress: () => load() },
          ],
        );
        setLoading(false);
        return;
      }

      // ── Other — try hydrator + AsyncStorage cache, then clean empty state ──
      let cached = await getCachedJobBootstrap(String(id)).catch(() => null);
      if (!cached?.report) cached = await getCachedBootstrap(String(id));
      if (cached?.job && cached?.report) {
        setJob(cached.job);
        setReport(cached.report);
        reportRef.current = cached.report;
        setOfflineMode(true);
      }
      // If no cache + offline → clean "not cached" state (no red alert).
      // If online + real error → show the backend message.
      else if (status === null) {
        // Network error — offline with no cache.
        // Don't show an alert — the UI will render the "not cached" empty state.
      } else {
        Alert.alert("Unable to open checklist", msg);
      }
    } finally {
      setLoading(false);
    }
  }, [id, _logBootstrapFailure, router]);
  useEffect(() => { load(); }, [load]);

  // Phase 27 — seed service-report media from loaded report.
  useEffect(() => {
    if (!report) return;
    const media: any[] = report.media || [];
    setSrPhotos(media.filter((m: any) => m.kind === "photo"));
    setSrVideos(media.filter((m: any) => m.kind === "video"));
    // Intentionally keyed on report.id — the report object identity
    // changes on every autosave, but seeding is only needed when the
    // active report changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report?.id]);

  // Phase v · Seed water_bodies from report (or create default pool body).
  useEffect(() => {
    if (!report) return;
    const existing: WaterBody[] | undefined = report.water_bodies;
    if (Array.isArray(existing) && existing.length > 0) {
      setWaterBodies(existing);
      waterBodiesRef.current = existing;
    } else if (waterBodies.length === 0) {
      // Auto-seed one pool body from legacy flat readings.
      const seed = makeEmptyBody("pool", 0);
      seed.readings = report.chemical_readings || [];
      seed.chemicals_used = report.chemicals_added || [];
      seed.notes = report.notes || "";
      const initial = [seed];
      setWaterBodies(initial);
      waterBodiesRef.current = initial;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report?.id]);

  // ─── Autosave (debounced) ────────────────────────────────────────────
  //
  // K61.b.2 · Feb-2026 — ``flushSave`` now returns a truthful result
  // envelope ``{ ok, queued?, error? }`` so callers (Save-draft,
  // autosave debounce, close-job pre-flush) can react to the outcome
  // instead of relying on the fire-and-forget catch-and-swallow pattern.
  //
  //   ``ok: true``               — persisted successfully to the server.
  //   ``ok: true,  queued: true``— written to the local write-queue and
  //                                 will sync on reconnect (offline path).
  //   ``ok: false, error: "…"``  — HTTP failure (4xx/5xx) OR an
  //                                 unexpected exception; ``error`` is
  //                                 the humanised message ready to
  //                                 surface to the user.
  //   ``ok: true``               — early-return short-circuits (nothing
  //                                 to save; treated as a benign no-op).
  //
  // Autosave callers can continue to ignore the return.  Save-draft
  // now branches on ``ok`` and NEVER falsely claims success on failure
  // (pre-K61 bug — it always showed an "Saved" alert regardless of
  // whether the PATCH threw).
  type FlushSaveResult = { ok: boolean; queued?: boolean; error?: string };
  const flushSave = useCallback(async (): Promise<FlushSaveResult> => {
    // Read from the ref so a queued autosave timer sees the newest
    // report state — not the one closed over at scheduleAutosave time.
    const current = reportRef.current;
    if (!current || current.submitted_at) return { ok: true };
    if (!dirtyRef.current || savingRef.current) return { ok: true };
    savingRef.current = true;
    if (!savingShownAtRef.current) savingShownAtRef.current = Date.now();
    setSaveState("saving");
    const patchBody: Record<string, any> = {
      chemical_readings: current.chemical_readings,
      chemicals_added: current.chemicals_added,
      checklist_items: current.checklist_items,
      notes: current.notes,
    };
    // Phase v · Include water_bodies when multi-body data exists.
    const bodies = waterBodiesRef.current;
    if (Array.isArray(bodies) && bodies.length > 0) {
      patchBody.water_bodies = bodies;
    }
    try {
      // Phase 40 · Step 2 — offline? Enqueue instead of hitting the wire.
      // The queue flushes with the same X-Idempotency-Key on reconnect so
      // the server can't create a duplicate patch even if the tech
      // triggers several autosaves while disconnected.
      if (!online) {
        await writeQueue.enqueue({
          kind: "patch-service-report",
          jobId: String(id),
          body: patchBody,
        });
        dirtyRef.current = false;
        // Optimistic — the local report state is already the source of
        // truth for the checklist screen; the server will catch up.
        const elapsed = Date.now() - (savingShownAtRef.current || Date.now());
        const holdMs = Math.max(0, MIN_SAVING_MS - elapsed);
        setTimeout(() => {
          setSaveState("saved");
          savingShownAtRef.current = 0;
          setTimeout(() => setSaveState((s) => (s === "saved" ? "idle" : s)), 1200);
        }, holdMs);
        // K61.b.2 · Feb-2026 — offline path is a truthful positive
        // outcome; caller renders "Saved locally, will sync" so the
        // tech knows the write is safe but not yet server-side.
        return { ok: true, queued: true };
      }
      const { data: patched, queued: oqQueued } = await offlineWrite({
        op_type: "service_report.patch",
        entity_id: String(id),
        endpoint: `/jobs/${id}/service-report`,
        method: "PATCH",
        payload: patchBody,
        onlineFn: () => retryWithBackoff(
          () => api.patch(`/jobs/${id}/service-report`, patchBody),
          {
            maxRetries: 5, baseDelayMs: 2000, maxDelayMs: 30000,
            maxTotalWaitMs: 30000,
            onRetryAttempt: (info) => {
              setPillState({
                kind: "retrying", attempt: info.attempt, maxRetries: 5,
                nextDelayMs: info.nextDelayMs, totalElapsedMs: info.totalElapsedMs,
              });
            },
          },
        ),
      });
      if (patched && typeof patched === "object") { setReport(patched); reportRef.current = patched; }
      dirtyRef.current = false;
      const elapsed = Date.now() - (savingShownAtRef.current || Date.now());
      const holdMs = Math.max(0, MIN_SAVING_MS - elapsed);
      setTimeout(() => {
        setSaveState("saved");
        savingShownAtRef.current = 0;
        setTimeout(() => setSaveState((s) => (s === "saved" ? "idle" : s)), 1200);
      }, holdMs);
      // Phase 2 — if offlineWrite fell back to queue (network drop
      // mid-request), return a truthful queued result.
      if (oqQueued) return { ok: true, queued: true };
      // K61.b.2 · Feb-2026 — happy path.
      return { ok: true };
    } catch (e: any) {
      setSaveState("error");
      savingShownAtRef.current = 0;
      // P0 429 fix — set exhausted pill with tap-to-retry action.
      setPillState({
        kind: "exhausted",
        onRetry: () => { scheduleAutosave(); },
      });
      return { ok: false, error: String(e?.message || "Save failed. Try again.") };
    } finally {
      savingRef.current = false;
    }
  }, [id, online]);

  const scheduleAutosave = useCallback(() => {
    dirtyRef.current = true;
    // Phase 37 — flip the pill to "saving" immediately on any edit.
    if (!savingRef.current) {
      savingShownAtRef.current = Date.now();
      setSaveState("saving");
    }
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => { flushSave(); }, AUTOSAVE_DEBOUNCE_MS);
  }, [flushSave]);

  useEffect(() => () => {
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
  }, []);

  // Merge a partial report change and mark dirty so autosave will flush.
  const patchReport = useCallback((patch: Record<string, any>) => {
    setReport((prev: any) => {
      const merged = { ...prev, ...patch };
      // Keep the ref in lock-step with the state so a debounced
      // autosave timer reads the freshest value.
      reportRef.current = merged;
      return merged;
    });
    scheduleAutosave();
  }, [scheduleAutosave]);

  // Phase v · Water bodies change handler — keeps ref in sync + triggers autosave.
  // Sep-2026 · Also mirrors the first pool body's readings into the flat
  // `chemical_readings` array so the Recommended Chemicals card
  // (readingsDict in PoolChecklistForm) stays responsive.
  const handleBodiesChange = useCallback((next: WaterBody[]) => {
    setWaterBodies(next);
    waterBodiesRef.current = next;
    setHighlightBodies({});
    // Mirror structured pool readings → flat chemical_readings for
    // recommendation engine + autosave payload.
    const poolBody = next.find((b) => b.type === "pool");
    if (poolBody) {
      const flat = (poolBody.readings || []).map((r) => ({
        key: r.key,
        name: r.name || r.key,
        value: r.value,
        unit: r.unit,
      }));
      patchReport({ chemical_readings: flat });
    } else {
      scheduleAutosave();
    }
  }, [scheduleAutosave, patchReport]);

  // Feb-2026 · Checklist reclassifier (mobile parity with web
  // ChecklistModal.handleReclassify) — writes `service_type` on the
  // job via PUT /api/jobs/{id} and refetches both job + report so the
  // Chemical Readings section repopulates from the fresh template.
  const handleReclassify = useCallback(async (nextServiceType: string) => {
    if (!id || !nextServiceType) return;
    try { await flushSave(); } catch { /* non-blocking */ }
    await api.put(`/jobs/${id}`, { service_type: nextServiceType });
    const [j, r] = await Promise.all([
      api.get(`/jobs/${id}`),
      api.get(`/jobs/${id}/service-report`),
    ]);
    setJob(j);
    setReport(r);
    reportRef.current = r;
    dirtyRef.current = false;
    setSaveState("idle");
  }, [id, flushSave]);

  // ─── Phase C1 · Dirty-close guard ────────────────────────────────────
  //
  // Intercepts navigation (header ×, Android back, iOS swipe-back) when
  // the checklist form has unsaved changes. Shows a three-button confirm:
  //   • Save & close (primary) — flush save then navigate back
  //   • Discard changes (destructive) — clear dirty, navigate back
  //   • Keep editing (neutral) — dismiss dialog only
  //
  const attemptClose = useCallback(() => {
    if (!dirtyRef.current) {
      router.back();
      return;
    }
    setDirtyCloseOpen(true);
  }, [router]);

  const handleSaveAndClose = useCallback(async () => {
    setSaveAndClosing(true);
    dirtyRef.current = true; // force flush
    const result = await flushSave();
    setSaveAndClosing(false);
    if (result.ok) {
      dirtyRef.current = false;
      setIsDirtyForGuard(false); // immediately unblock navigation
      setDirtyCloseOpen(false);
      // Replay the prevented navigation action if it exists
      setTimeout(() => {
        if (preventedNavRef.current) {
          const { action } = preventedNavRef.current.data;
          preventedNavRef.current = null;
          router.dispatch(action);
        } else {
          router.back();
        }
      }, 50);
    } else {
      showToast("Couldn't save your changes — please check your connection and try again.");
      // Keep dialog open, keep dirty
    }
  }, [flushSave, router, showToast]);

  const handleDiscard = useCallback(() => {
    dirtyRef.current = false;
    setIsDirtyForGuard(false); // immediately unblock navigation
    setDirtyCloseOpen(false);
    setTimeout(() => {
      if (preventedNavRef.current) {
        const { action } = preventedNavRef.current.data;
        preventedNavRef.current = null;
        router.dispatch(action);
      } else {
        router.back();
      }
    }, 50);
  }, [router]);

  const handleKeepEditing = useCallback(() => {
    preventedNavRef.current = null;
    setDirtyCloseOpen(false);
  }, []);

  // Intercept back navigation (Android back button, iOS swipe-back, programmatic).
  // `usePreventRemove` gates on `dirtyRef.current` — only prevents when dirty.
  // We use a state mirror because the hook needs a reactive boolean.
  const [isDirtyForGuard, setIsDirtyForGuard] = useState(false);
  // Keep the reactive state in sync with the ref. We update it on every
  // scheduleAutosave (dirty=true) and after successful flush (dirty=false).
  useEffect(() => {
    const interval = setInterval(() => {
      setIsDirtyForGuard(dirtyRef.current);
    }, 500);
    return () => clearInterval(interval);
  }, []);

  usePreventRemove(isDirtyForGuard, (e) => {
    // Store the prevented action so we can replay it after save/discard
    preventedNavRef.current = e;
    setDirtyCloseOpen(true);
  });

  // ─── Save draft (explicit) ───────────────────────────────────────────
  //
  // K61.b.2 · Feb-2026 — Save-draft now branches on the ``flushSave``
  // result envelope.  Pre-K61 this handler unconditionally showed
  // "Saved" — even when the PATCH threw — because ``flushSave`` used
  // to swallow errors internally.  That lied to the tech and hid data
  // loss when the server 4xx'd a checklist payload.
  //
  //   ok && queued  →  "Saved locally, will sync"   (offline)
  //   ok            →  "Saved · Draft saved."       (persisted server-side)
  //   !ok           →  "Save failed · <error>"      (never mis-labels success)
  //
  const saveDraft = async () => {
    dirtyRef.current = true;
    const result = await flushSave();
    if (result.ok) {
      if (result.queued) {
        Alert.alert(
          "Saved locally",
          "You're offline — the draft is queued and will sync when your device reconnects.",
        );
      } else {
        showToast("Draft saved.");
      }
    } else {
      Alert.alert("Save failed", result.error || "Try again.");
    }
  };

  // ─── Close job ───────────────────────────────────────────────────────
  // P0 fix — replaced Alert.alert with in-tree Modals to prevent the
  // iOS 17 + Hermes silent no-op where Alert.alert returns without
  // displaying on detached UIScene. Now every tap produces a visible
  // outcome: either the confirm dialog, the outlier warning, or the
  // spinner.
  const closeJob = async () => {
    if (!report || submitting) return;
    // Phase 50.B — outlier "Recheck?" confirmation. Hard-capped at 3s
    // so a network hang never blocks the close flow. Advisory only.
    let outliers: string[] = [];
    try {
      outliers = await Promise.race([
        _mobileComputeOutlierNames(report, job),
        new Promise<string[]>((_, rej) =>
          setTimeout(() => rej(new Error("outlier_timeout")), 3000),
        ),
      ]);
    } catch { /* fail-open: outlier check is advisory */ }
    if (outliers.length > 0) {
      setOutlierNames(outliers);
      setShowOutlierWarning(true);
      return;
    }
    setShowCloseConfirm(true);
  };

  // Extracted from the former Alert.alert("Close job?") onPress callback.
  // Called by the in-tree confirm dialog's "Close job" button.
  const doCloseJob = async () => {
    setShowCloseConfirm(false);
    setShowOutlierWarning(false);
    setSubmitting(true);
    try {
      // 1) Final PATCH — flush any pending edits.
      dirtyRef.current = true;
      const flushed = await flushSave();
      if (!flushed.ok) {
        Alert.alert(
          "Save failed",
          `${flushed.error || "Could not save your latest edits."}\n\nJob was not closed — please try again.`,
        );
        setSubmitting(false);
        return;
      }

      // 2) Submit / close.
      if (!online) {
        const current = reportRef.current;
        await submitOffline(String(id), current || report);
        Alert.alert(
          "Saved — will sync when online",
          "You're offline — the job will close automatically when your device reconnects.",
          [{ text: "OK", onPress: () => router.replace("/(app)/schedule/calendar") }],
        );
        return;
      }
      // P0 429 fix — wrap submit in retryWithBackoff.
      setPillState({ kind: "saving" });
      const submitted: any = await retryWithBackoff(
        () => api.post(`/jobs/${id}/service-report/submit`, {}),
        {
          maxRetries: 5, baseDelayMs: 2000, maxDelayMs: 30000,
          maxTotalWaitMs: 30000,
          onRetryAttempt: (info) => {
            setPillState({
              kind: "retrying", attempt: info.attempt, maxRetries: 5,
              nextDelayMs: info.nextDelayMs, totalElapsedMs: info.totalElapsedMs,
            });
          },
        },
      );

      // 3) Fire workstream event (best-effort).
      const template: ChecklistType = getChecklistType(job);
      const chemsCount = (report.chemicals_added || []).length;
      const photosCount = (report.photos || []).length;
      try {
        await api.post("/workstream/events", {
          type: "job.completed",
          payload: {
            job_id: id,
            customer_name: job?.customer_name,
            tech_name: user?.name || user?.email,
            service_type: job?.service_type,
            chemicals_added_count: chemsCount,
            photos_count: photosCount,
            template,
          },
          related_ref: { type: "job", id: String(id) },
        });
      } catch (e: any) {
        Alert.alert("Job closed", `Workstream event failed: ${e?.message || "unknown"}`);
      }

      // 4) Navigate to schedule — recap dialog removed (Phase M5).
      //    Clear dirty state so the navigation guard doesn't block.
      dirtyRef.current = false;
      setIsDirtyForGuard(false);
      const invId = submitted?.invoice_id
        ? ` · Invoice #${String(submitted.invoice_id).slice(0, 8)}` : "";
      Alert.alert("Job closed", `Report submitted${invId}.`, [
        { text: "OK", onPress: () => router.replace("/(app)/schedule/calendar") },
      ]);
    } catch (e: any) {
      const isApiErr = e instanceof ApiError;
      const rawDetail: any = isApiErr ? e.detail : null;
      // P0 429 fix — retries exhausted on 429 → error dialog.
      if (isApiErr && e.status === 429) {
        closeJobPayloadRef.current = { jobId: id, report: reportRef.current || report, job };
        setPillState({ kind: "exhausted", onRetry: () => setCloseJobError(null) });
        setCloseJobError(
          "The server is temporarily busy (rate-limited). Your job data has been saved locally. Please try closing the job again in a moment."
        );
        try {
          await writeQueue.enqueue({
            kind: "submit-service-report",
            jobId: String(id),
            body: {},
          });
        } catch (_qErr) { /* best effort */ }
      } else {
        const isChemistryGate =
          isApiErr && e.status === 422 &&
          rawDetail && typeof rawDetail === "object" &&
          (rawDetail as any).detail === "chemistry_core_readings_missing";
        if (isChemistryGate) {
          const missingLabels: string[] = Array.isArray(rawDetail.missing_labels)
            ? rawDetail.missing_labels
            : [];
          const bodyHighlights: Record<number, string[]> = {};
          const bodies = waterBodiesRef.current;
          for (let bi = 0; bi < bodies.length; bi++) {
            const b = bodies[bi];
            if (b.type === "pool") {
              const missing = missingRequiredReadings(b);
              if (missing.length > 0) bodyHighlights[bi] = missing;
            }
          }
          setHighlightBodies(bodyHighlights);
          const expanded = missingLabels.length > 0
            ? missingLabels.map(expandChemistryLabel).join(", ")
            : Object.values(bodyHighlights).flat().map(expandChemistryLabel).join(", ");
          Alert.alert(
            "Missing required readings",
            `Please fill in: ${expanded || "required chemistry fields"}.`,
          );
        } else if (isApiErr) {
          Alert.alert("Close failed", e.message || `Request failed (${e.status})`);
        } else {
          Alert.alert("Close failed", e?.message || "Try again.");
        }
      }
    } finally {
      setSubmitting(false);
    }
  };

  // ─── Render ──────────────────────────────────────────────────────────
  if (!canWrite) {
    return (
      <View style={styles.centered} testID="checklist-forbidden">
        <Ionicons name="lock-closed-outline" size={40} color={colors.muted} />
        <Text style={styles.forbiddenText}>You don&apos;t have permission to open this checklist.</Text>
      </View>
    );
  }

  if (loading) {
    return (
      <View style={styles.centered} testID="checklist-loading">
        <ActivityIndicator size="large" color={colors.brand} />
      </View>
    );
  }

  if (!report || !job) {
    const mapped = bootstrapError ? mapApiError(bootstrapError) : null;
    const icon = mapped ? errorKindIcon(mapped.kind) : "cloud-offline-outline";
    const title = mapped ? mapped.title : (!online ? "Not cached for offline" : "Unable to load checklist.");
    const body = mapped ? mapped.message : (!online ? "Connect to Wi-Fi or cellular once to enable offline access for this job." : "Check your connection and try again.");
    return (
      <View style={styles.centered} testID="checklist-error">
        <Ionicons name={icon as any} size={48} color={colors.muted} />
        <Text style={[styles.forbiddenText, { marginTop: spacing.md }]}>
          {title}
        </Text>
        <Text style={{ fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", marginTop: spacing.sm, paddingHorizontal: spacing.lg }} testID="checklist-not-cached-msg">
          {body}
        </Text>
        <Pressable style={{ marginTop: spacing.lg, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, backgroundColor: colors.brand, borderRadius: radius.md }} onPress={() => router.back()} testID="checklist-go-back-btn">
          <Text style={{ fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" }}>Go back</Text>
        </Pressable>
      </View>
    );
  }

  const locked = !!report.submitted_at;
  const clientType: ChecklistType = getChecklistType(job);
  const backendKind: string = report.template || "generic";
  // Feb-2026 · Checklist reclassifier — mirrors ChecklistModal's rule:
  // admins/managers can always retag; techs only when the job is
  // theirs (matches routers/jobs.py::update_job:925 403 boundary).
  // `role` is already declared at line 89 (component top scope) — reuse
  // it here rather than shadowing (fixes the eas-export SyntaxError
  // from the prior ticket).
  const canEditServiceType: boolean = !locked && (
    role === "admin" || role === "super_admin" || role === "manager" ||
    (role === "technician" && !!user?.technician_id
      && user.technician_id === job.technician_id)
  );

  return (
    <View style={styles.root}>
      <Header
        title="Job Checklist"
        back
        right={
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <OfflineBadge testID="checklist-header-offline-badge" />
            {!locked && (
              <Pressable onPress={attemptClose} hitSlop={10} testID="checklist-header-close-btn">
                <Ionicons name="close" size={24} color={colors.onSurface} />
              </Pressable>
            )}
          </View>
        }
      />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 160 + insets.bottom }}>
        <View style={styles.hero} testID="checklist-hero">
          <Text style={styles.heroLabel}>
            {clientType} · backend:{backendKind}{locked ? " · LOCKED" : ""}
          </Text>
          <Text style={styles.heroTitle}>
            {job.title || job.service_type || "Service"}
          </Text>
          <Text style={styles.heroSub}>
            {formatCustomerName(job)} · {job.address || ""}
          </Text>
          {/* P0 429 fix — single unified save pill. Never show two contradictory pills. */}
          <ChecklistSavePill state={pillState} testID="checklist-save-pill" />

          {/* Phase 22 — Share Visit pill. Visible once report is locked + has public_uuid. */}
          {locked && report.public_uuid ? (
            <Pressable
              style={styles.shareVisitPill}
              testID="svc-report-share-visit"
              onPress={async () => {
                const base = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/+$/, "");
                const url = `${base}/portal/service/${report.public_uuid}`;
                await Clipboard.setStringAsync(url);
                Alert.alert(
                  "Link copied",
                  "Link copied — you can text this to the customer.",
                  [
                    { text: "OK" },
                    {
                      text: "Share…",
                      onPress: () => Share.share({ url, message: url }).catch(() => {}),
                    },
                  ],
                );
              }}
            >
              <Ionicons name="share-outline" size={12} color="#fff" />
              <Text style={styles.shareVisitText}>Share visit</Text>
            </Pressable>
          ) : null}
        </View>

        {/* Phase 27 — Unified service-report media (photos + videos via /api/service-reports/{id}/media) */}
        {report?.id && (
          <View style={styles.card} testID="checklist-sr-media-card">
            <Text style={styles.cardTitle}>Visit Media</Text>
            <ServiceReportMediaUploader
              reportId={report.id}
              photos={srPhotos}
              videos={srVideos}
              onPhotosChange={setSrPhotos}
              onVideosChange={setSrVideos}
              readonly={locked}
            />
          </View>
        )}

        {/* Template-specific form */}
        <View style={styles.card} testID={`checklist-form-${clientType}`}>
          {/* Phase v · Multi-body water bodies (pool type only). */}
          {clientType === "pool" && (
            <View testID="checklist-water-bodies-section">
              <WaterBodyManager
                bodies={waterBodies}
                locked={locked}
                highlightBodies={highlightBodies}
                onChange={handleBodiesChange}
              />
            </View>
          )}
          {clientType === "pool" && (
            <PoolChecklistForm
              jobId={String(id)}
              customerId={job?.customer_id || null}
              locked={locked}
              readings={report.chemical_readings || []}
              readingFields={report.chemical_reading_fields || []}
              chemicalsAdded={report.chemicals_added || []}
              chemicalsCatalog={report.chemicals_catalog || []}
              chemicalUnits={report.chemical_units || ["gal", "lbs", "oz", "tabs"]}
              checklistItems={report.checklist_items || []}
              notes={report.notes || ""}
              observations={report.observations || {}}
              onChange={patchReport}
              template={backendKind}
              canEditServiceType={canEditServiceType}
              onReclassify={handleReclassify}
            />
          )}
          {clientType === "landscaping" && (
            <LandscapingChecklistForm
              locked={locked}
              checklistItems={report.checklist_items || []}
              notes={report.notes || ""}
              onChange={patchReport}
            />
          )}
          {clientType === "generic" && (
            <GenericChecklistForm
              locked={locked}
              checklistItems={report.checklist_items || []}
              workPerformed={report.work_performed || ""}
              notes={report.notes || ""}
              onChange={(patch) => {
                // The service-report PATCH shape only accepts notes / readings /
                // chemicals / checklist_items — fold `work_performed` into a
                // marker inside `notes` so we don't invent a new field.
                if ("work_performed" in patch) {
                  const wp = patch.work_performed || "";
                  const currentNotes = report.notes || "";
                  const marker = "[Work Performed]";
                  let mergedNotes = currentNotes;
                  const rx = new RegExp(`${marker.replace(/[\[\]]/g, "\\$&")}[\\s\\S]*?(?=\\n\\n|$)`, "");
                  if (rx.test(mergedNotes)) {
                    mergedNotes = mergedNotes.replace(rx, `${marker}\n${wp}`);
                  } else {
                    mergedNotes = wp
                      ? `${marker}\n${wp}${currentNotes ? "\n\n" + currentNotes : ""}`
                      : currentNotes;
                  }
                  patchReport({ work_performed: wp, notes: mergedNotes });
                  return;
                }
                patchReport(patch);
              }}
            />
          )}
        </View>

        {/* Phase M4 — Internal Photos (very bottom of scrollable content).
            Internal-only — bound to job.photos, never surfaced to customer portal. */}
        <View style={styles.card} testID="checklist-photos-card">
          <Text style={styles.cardTitle}>Internal Photos</Text>
          <PhotoUploader
            jobId={String(id)}
            photos={report.photos || []}
            onPhotosChange={(next) => setReport({ ...report, photos: next })}
            max={PHOTO_CAP}
            disabled={locked}
          />
        </View>

        {/* Phase M4 — Internal Videos (very bottom of scrollable content).
            Internal-only — bound to job.videos, never surfaced to customer portal. */}
        <View style={styles.card} testID="checklist-videos-card">
          <Text style={styles.cardTitle}>Internal Videos</Text>
          <VideoMediaUploader
            entityKind="job"
            entityId={String(id)}
            existingVideos={job.videos || []}
            onUploaded={(v) => setJob((j: any) => ({ ...j, videos: [...(j.videos || []), v] }))}
            onDeleted={(vid) => setJob((j: any) => ({ ...j, videos: (j.videos || []).filter((vv: any) => vv.id !== vid) }))}
            onPatched={(v) => setJob((j: any) => ({ ...j, videos: (j.videos || []).map((vv: any) => (vv.id === v.id ? v : vv)) }))}
            readonly={locked}
          />
        </View>
      </ScrollView>

      {!locked && (
        <View style={[styles.footer, { paddingBottom: insets.bottom + spacing.md }]}>
          <Pressable
            style={styles.draftBtn}
            onPress={saveDraft}
            testID="checklist-save-draft"
            disabled={submitting}
          >
            <Ionicons name="save-outline" size={16} color={colors.brand} />
            <Text style={styles.draftBtnText}>Save draft</Text>
          </Pressable>
          <Pressable
            style={[styles.closeBtn, submitting && { opacity: 0.6 }]}
            onPress={closeJob}
            disabled={submitting}
            testID="checklist-close-job"
          >
            {submitting
              ? <ActivityIndicator size="small" color="#fff" />
              : <Ionicons name="shield-checkmark-outline" size={16} color="#fff" />}
            <Text style={styles.closeBtnText}>
              {submitting ? "Closing…" : "Close job"}
            </Text>
          </Pressable>
        </View>
      )}
      {/* Phase 39 · Step 2 — Visit Recap prompt (mobile). */}
      {/* P0 429 fix — job close error dialog (retries exhausted) */}
      <Modal visible={!!closeJobError} transparent animationType="fade" testID="job-close-error-dialog">
        <View style={styles.errorDialogOverlay}>
          <View style={styles.errorDialogCard}>
            <Ionicons name="alert-circle" size={36} color="#DC2626" />
            <Text style={styles.errorDialogTitle}>Could not close job</Text>
            <Text style={styles.errorDialogMessage}>{closeJobError}</Text>
            <View style={styles.errorDialogActions}>
              <TouchableOpacity
                style={styles.errorDialogDismiss}
                onPress={() => setCloseJobError(null)}
                testID="job-close-error-dismiss"
              >
                <Text style={styles.errorDialogDismissText}>Dismiss</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.errorDialogRetry}
                onPress={() => {
                  setCloseJobError(null);
                  setPillState({ kind: "synced" });
                  // P0 fix — was `handleClose()` (undefined). Now calls doCloseJob.
                  doCloseJob();
                }}
                testID="job-close-error-retry"
              >
                <Text style={styles.errorDialogRetryText}>Try again</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* P0 fix — In-tree close-job confirmation (replaces Alert.alert) */}
      <Modal visible={showCloseConfirm} transparent animationType="fade" testID="close-job-confirm-dialog">
        <View style={styles.errorDialogOverlay}>
          <View style={styles.errorDialogCard}>
            <Ionicons name="shield-checkmark" size={36} color={colors.brand} />
            <Text style={styles.errorDialogTitle}>Close job?</Text>
            <Text style={styles.errorDialogMessage}>Customer will see the final report.</Text>
            <View style={styles.errorDialogActions}>
              <TouchableOpacity
                style={styles.errorDialogDismiss}
                onPress={() => setShowCloseConfirm(false)}
                testID="close-job-cancel-btn"
              >
                <Text style={styles.errorDialogDismissText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.errorDialogRetry}
                onPress={doCloseJob}
                testID="close-job-confirm-btn"
              >
                <Text style={styles.errorDialogRetryText}>Close job</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* P0 fix — In-tree outlier warning (replaces Alert.alert) */}
      <Modal visible={showOutlierWarning} transparent animationType="fade" testID="close-job-outlier-dialog">
        <View style={styles.errorDialogOverlay}>
          <View style={styles.errorDialogCard}>
            <Ionicons name="warning" size={36} color="#D97706" />
            <Text style={styles.errorDialogTitle}>One of your readings looks off</Text>
            <Text style={styles.errorDialogMessage}>{outlierNames.join(", ")} — proceed anyway?</Text>
            <View style={styles.errorDialogActions}>
              <TouchableOpacity
                style={styles.errorDialogDismiss}
                onPress={() => { setShowOutlierWarning(false); setOutlierNames([]); }}
                testID="close-job-outlier-recheck-btn"
              >
                <Text style={styles.errorDialogDismissText}>Let me recheck</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.errorDialogRetry, { backgroundColor: "#DC2626" }]}
                onPress={() => { setShowOutlierWarning(false); setShowCloseConfirm(true); }}
                testID="close-job-outlier-proceed-btn"
              >
                <Text style={styles.errorDialogRetryText}>Proceed anyway</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Phase C1 · Dirty-close guard confirm dialog */}
      <Modal visible={dirtyCloseOpen} transparent animationType="fade" testID="checklist-dirty-close-dialog">
        <View style={styles.errorDialogOverlay}>
          <View style={styles.errorDialogCard}>
            <Ionicons name="alert-circle-outline" size={36} color={colors.brand} />
            <Text style={styles.errorDialogTitle} testID="checklist-dirty-close-title">
              Save before closing?
            </Text>
            <Text style={styles.errorDialogMessage} testID="checklist-dirty-close-body">
              You have unsaved changes on this checklist. Save now, or discard them?
            </Text>
            <View style={styles.dirtyCloseActions}>
              {/* Save & close — primary */}
              <TouchableOpacity
                style={[styles.dirtyCloseSaveBtn, saveAndClosing && { opacity: 0.7 }]}
                onPress={handleSaveAndClose}
                disabled={saveAndClosing}
                testID="checklist-save-and-close"
              >
                {saveAndClosing ? (
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <ActivityIndicator size="small" color="#fff" />
                    <Text style={styles.dirtyCloseSaveBtnText}>Saving…</Text>
                  </View>
                ) : (
                  <Text style={styles.dirtyCloseSaveBtnText}>Save &amp; close</Text>
                )}
              </TouchableOpacity>
              {/* Discard changes — destructive */}
              <TouchableOpacity
                style={[styles.dirtyCloseDiscardBtn, saveAndClosing && { opacity: 0.4 }]}
                onPress={handleDiscard}
                disabled={saveAndClosing}
                accessibilityHint="Chemistry values entered since your last save will be lost."
                testID="checklist-discard-confirm-btn"
              >
                <Text style={styles.dirtyCloseDiscardBtnText}>Discard changes</Text>
              </TouchableOpacity>
              {/* Keep editing — neutral */}
              <TouchableOpacity
                style={styles.dirtyCloseKeepBtn}
                onPress={handleKeepEditing}
                testID="checklist-discard-keep-editing"
              >
                <Text style={styles.dirtyCloseKeepBtnText}>Keep editing</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg },
  forbiddenText: {
    fontFamily: font.semibold, color: colors.muted, marginTop: spacing.md,
    textAlign: "center",
  },
  hero: {
    backgroundColor: colors.brand, borderRadius: radius.lg, padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  heroLabel: {
    fontFamily: font.bold, fontSize: fontSize.xs, color: "#fff",
    opacity: 0.9, letterSpacing: 1, textTransform: "uppercase",
  },
  heroTitle: {
    fontFamily: font.bold, fontSize: fontSize.xl, color: "#fff",
    marginTop: 4,
  },
  heroSub: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: "#fff",
    opacity: 0.9, marginTop: 4,
  },
  saveState: {
    fontFamily: font.semibold, color: "#fff", opacity: 0.85,
    marginTop: 8, fontSize: fontSize.xs,
  },
  autosavePill: {
    marginTop: 10,
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.pill,
    backgroundColor: "rgba(255,255,255,0.20)",
  },
  autosavePillSaving: { backgroundColor: "rgba(255,255,255,0.30)" },
  autosavePillSaved:  { backgroundColor: "rgba(22,163,74,0.90)" },
  autosavePillError:  { backgroundColor: "rgba(220,38,38,0.90)" },
  autosavePillText: {
    fontFamily: font.bold,
    fontSize: 11,
    color: "#FFFFFF",
  },
  networkPill: {
    marginTop: 6,
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  networkPillOnline: { backgroundColor: "rgba(22,163,74,0.90)" },
  networkPillOffline: { backgroundColor: "rgba(180,83,9,0.95)" },
  networkPillSyncing: { backgroundColor: "rgba(37,99,235,0.95)" },
  networkPillError: { backgroundColor: "rgba(220,38,38,0.95)" },
  networkPillText: {
    fontFamily: font.bold, fontSize: 11, color: "#FFFFFF",
  },
  shareVisitPill: {
    marginTop: 6,
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.pill,
    backgroundColor: "rgba(255,255,255,0.25)",
    borderWidth: 1,
    borderColor: "rgba(255,255,255,0.4)",
  },
  shareVisitText: {
    fontFamily: font.bold, fontSize: 11, color: "#FFFFFF",
  },
  card: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.md,
  },
  cardTitle: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  footer: {
    position: "absolute", bottom: 0, left: 0, right: 0,
    padding: spacing.md, backgroundColor: colors.surface,
    borderTopWidth: 1, borderTopColor: colors.border,
    flexDirection: "row", gap: spacing.sm,
  },
  draftBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 12, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.brand, backgroundColor: colors.surface,
  },
  draftBtnText: { fontFamily: font.bold, color: colors.brand, fontSize: fontSize.base },
  closeBtn: {
    flex: 2, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 12, borderRadius: radius.md,
    backgroundColor: colors.brand,
  },
  closeBtnText: { fontFamily: font.bold, color: "#fff", fontSize: fontSize.base },
  // P0 429 fix — error dialog styles
  errorDialogOverlay: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.5)", justifyContent: "center", padding: 24,
  },
  errorDialogCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl,
    alignItems: "center",
  },
  errorDialogTitle: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    marginTop: spacing.sm, marginBottom: spacing.xs,
  },
  errorDialogMessage: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
    textAlign: "center", lineHeight: 20, marginBottom: spacing.lg,
  },
  errorDialogActions: {
    flexDirection: "row", gap: spacing.sm, width: "100%",
  },
  errorDialogDismiss: {
    flex: 1, paddingVertical: 12, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, alignItems: "center",
  },
  errorDialogDismissText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.muted },
  errorDialogRetry: {
    flex: 1, paddingVertical: 12, borderRadius: radius.md,
    backgroundColor: colors.brand, alignItems: "center",
  },
  errorDialogRetryText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  // Phase C1 · Dirty-close guard dialog styles
  dirtyCloseActions: { gap: spacing.sm, width: "100%" },
  dirtyCloseSaveBtn: {
    paddingVertical: 12, borderRadius: radius.md,
    backgroundColor: colors.brand, alignItems: "center",
  },
  dirtyCloseSaveBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  dirtyCloseDiscardBtn: {
    paddingVertical: 12, borderRadius: radius.md,
    backgroundColor: "#DC2626", alignItems: "center",
  },
  dirtyCloseDiscardBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  dirtyCloseKeepBtn: {
    paddingVertical: 12, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, alignItems: "center",
  },
  dirtyCloseKeepBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.muted },
});
