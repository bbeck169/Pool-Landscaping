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
  Share,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import * as Clipboard from "expo-clipboard";

import { api, ApiError } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
// Feb-2026 · Phase 1 offline foundation — cache customer on the
// close-out lookup + surface the offline pill in the header.
import {
  writeThroughCustomer, readCachedCustomer,
} from "@/src/lib/offline/apiCache";
import OfflineBadge from "@/src/components/OfflineBadge";
import { getChecklistType, ChecklistType } from "@/src/utils/checklistType";
import ServiceReportMediaUploader from "@/src/components/checklist/ServiceReportMediaUploader";
import type { SRMedia } from "@/src/api/serviceReportMedia";
import PhotoUploader from "@/src/components/checklist/PhotoUploader";
import PoolChecklistForm from "@/src/components/checklist/PoolChecklistForm";
import LandscapingChecklistForm from "@/src/components/checklist/LandscapingChecklistForm";
import GenericChecklistForm from "@/src/components/checklist/GenericChecklistForm";
import VisitRecapModal from "@/src/components/checklist/VisitRecapModal";
import WaterBodyManager from "@/src/components/checklist/WaterBodyManager";
import { WaterBody, makeEmptyBody, missingRequiredReadings } from "@/src/lib/waterBodies";
// K61.c · Feb-2026 — expand chemistry-abbreviation labels (FC, TA,
// CYA, …) to human-readable full names when surfacing the "Missing
// required readings" alert.  See ``@/src/lib/expandChemistryLabel``.
import { expandChemistryLabel } from "@/src/lib/expandChemistryLabel";
import { cacheJobBootstrap, getCachedBootstrap } from "@/src/services/offlineCache";
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
  const router = useRouter();
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
  // Phase 39 · Step 2 — Visit Recap modal state, mirrors web.
  const [recapOpen, setRecapOpen] = useState(false);
  const [recapCustomer, setRecapCustomer] = useState<any>(null);

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
      // Cache the bootstrap for later offline access.
      await cacheJobBootstrap(String(id), { job: jobResp, report: reportResp });
      // Phase O3 · Also cache in SQLite for offline service-log.
      await cacheServiceReport(String(id), reportResp).catch(() => {});
    } catch (e: any) {
      const isApiErr = e instanceof ApiError;
      const status: number | null = isApiErr ? e.status : null;
      const msg = e?.message || "Unknown error";

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
        // Try cache fallback
        const cached = await getCachedBootstrap(String(id));
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

      // ── Other — try cache, then generic alert with body message ────
      const cached = await getCachedBootstrap(String(id));
      if (cached?.job && cached?.report) {
        setJob(cached.job);
        setReport(cached.report);
        reportRef.current = cached.report;
        setOfflineMode(true);
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
      const { data: patched } = await offlineWrite({
        op_type: "service_report.patch",
        entity_id: String(id),
        endpoint: `/jobs/${id}/service-report`,
        method: "PATCH",
        payload: patchBody,
        onlineFn: () => api.patch(`/jobs/${id}/service-report`, patchBody),
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
      // K61.b.2 · Feb-2026 — happy path.
      return { ok: true };
    } catch (e: any) {
      setSaveState("error");
      savingShownAtRef.current = 0;
      // K61.b.2 · Feb-2026 — surface the humanised message to the
      // caller so Save-draft can render a truthful error toast.
      // Never falsely claim success.  The message defaults through
      // ``api.ts`` (fetch-based ``ApiError``) or ``ApiNetworkError``
      // → both attach a readable string to ``e.message``.
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
  const handleBodiesChange = useCallback((next: WaterBody[]) => {
    setWaterBodies(next);
    waterBodiesRef.current = next;
    setHighlightBodies({});
    scheduleAutosave();
  }, [scheduleAutosave]);

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
        Alert.alert("Saved", "Draft saved.");
      }
    } else {
      Alert.alert("Save failed", result.error || "Try again.");
    }
  };

  // ─── Close job ───────────────────────────────────────────────────────
  const closeJob = async () => {
    if (!report || submitting) return;
    // Phase 50.B — outlier "Recheck?" confirmation before the regular
    // Close-job dialog. Fail-open on any error so we never trap the tech.
    try {
      const outliers = await _mobileComputeOutlierNames(report, job);
      if (outliers.length > 0) {
        const proceed = await new Promise<boolean>((resolve) => {
          Alert.alert(
            "One of your readings looks off",
            `${outliers.join(", ")} — proceed anyway?`,
            [
              { text: "Let me recheck", style: "cancel", onPress: () => resolve(false) },
              { text: "Proceed anyway", style: "destructive", onPress: () => resolve(true) },
            ],
            { cancelable: true, onDismiss: () => resolve(false) }
          );
        });
        if (!proceed) return;
      }
    } catch { /* non-blocking */ }
    Alert.alert(
      "Close job?",
      "Customer will see the final report.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Close job", style: "destructive",
          onPress: async () => {
            setSubmitting(true);
            try {
              // 1) Final PATCH — flush any pending edits.
              //
              // K61.b.2 · Feb-2026 — respect ``flushSave``'s result.
              // If the pre-flush PATCH failed, do NOT proceed to
              // submit — the submit would either 4xx on stale server
              // state OR silently succeed with pre-flush data.  Bail
              // out with a truthful error toast and let the tech
              // retry after fixing whatever broke the PATCH.
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
                // Phase O3 — Offline: enqueue service_report.upsert through
                // the SQLite sync queue (survives force-quit).
                const current = reportRef.current;
                await submitOffline(String(id), current || report);
                Alert.alert(
                  "Submitted (pending sync)",
                  "You're offline — the job will close automatically when your device reconnects.",
                  [{ text: "OK", onPress: () => router.replace("/(app)/schedule/calendar") }],
                );
                return;
              }
              const submitted: any = await api.post(
                `/jobs/${id}/service-report/submit`, {}
              );

              // 3) Fire workstream event (best-effort — do not roll back on failure).
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

              // 4) Navigate back — but first prompt the tech to send the
              //    visit recap. The recap modal handles its own close.
              try {
                if (job?.customer_id) {
                  const cust: any = await api.get(`/customers/${job.customer_id}`);
                  writeThroughCustomer(cust).catch(() => {});
                  setRecapCustomer({
                    id: cust?.id, name: cust?.name,
                    email: cust?.email, phone: cust?.phone,
                    alert_phone: cust?.alert_phone,
                  });
                } else {
                  setRecapCustomer({ name: formatCustomerName(job) });
                }
              } catch {
                // Offline — try the SQLite read cache before we
                // fall through to the job's denormalised
                // ``customer_name``.
                const cached = job?.customer_id
                  ? await readCachedCustomer(job.customer_id).catch(() => null)
                  : null;
                setRecapCustomer(cached ? {
                  id: cached.id, name: cached.name,
                  email: cached.email, phone: cached.phone,
                  alert_phone: cached.alert_phone,
                } : { name: formatCustomerName(job) });
              }
              setRecapOpen(true);
            } catch (e: any) {
              // K61.a.2 + K61.c · Feb-2026 — inspect the structured
              // ``ApiError`` shape rather than fishing for the pre-K61
              // axios-shaped ``e.response.data.detail`` fields (which
              // never exist on the fetch-based client and made the
              // whole branch dead code).  Structured chemistry-gate
              // detection: ``err.status === 422 && err.detail?.detail
              // === "chemistry_core_readings_missing"``.
              //
              // Missing-labels are surfaced BOTH visually (per-body
              // ``highlightBodies`` for the ChemistryReadings section)
              // AND textually (single Alert listing the labels).
              // Labels get run through the K60 chemistry-label
              // expander so techs see "Cyanuric Acid" instead of
              // "CYA" in the alert copy.
              const isApiErr = e instanceof ApiError;
              const rawDetail: any = isApiErr ? e.detail : null;
              const isChemistryGate =
                isApiErr && e.status === 422 &&
                rawDetail && typeof rawDetail === "object" &&
                (rawDetail as any).detail === "chemistry_core_readings_missing";
              if (isChemistryGate) {
                const missingLabels: string[] = Array.isArray(rawDetail.missing_labels)
                  ? rawDetail.missing_labels
                  : [];
                // Map missing reading labels back to body indices for
                // inline field highlighting.  Pre-K61 code already
                // wired up ``highlightBodies`` via
                // ``missingRequiredReadings`` per body — this call
                // was in place but never fired because the outer
                // ``if`` was dead code.
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
                // Expand any short-form labels ("CYA" → "Cyanuric
                // Acid").  Backend already returns most as readable
                // strings — expander is idempotent on those.
                const expanded = missingLabels.length > 0
                  ? missingLabels.map(expandChemistryLabel).join(", ")
                  : Object.values(bodyHighlights).flat().map(expandChemistryLabel).join(", ");
                Alert.alert(
                  "Missing required readings",
                  `Please fill in: ${expanded || "required chemistry fields"}.`,
                );
              } else if (isApiErr) {
                // Non-chemistry HTTP failure — surface the real
                // backend reason (already humanised via api.ts's
                // detail-flattening), not "Something went wrong".
                Alert.alert("Close failed", e.message || `Request failed (${e.status})`);
              } else {
                // ApiNetworkError / unexpected — fall through to the
                // generic message string.
                Alert.alert("Close failed", e?.message || "Try again.");
              }
            } finally {
              setSubmitting(false);
            }
          },
        },
      ]
    );
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
    return (
      <View style={styles.centered} testID="checklist-error">
        <Text style={styles.forbiddenText}>Unable to load checklist.</Text>
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
      <Header title="Job Checklist" right={<OfflineBadge testID="checklist-header-offline-badge" />} />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 160 }}>
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
          <View
            testID="checklist-autosave-pill"
            style={[
              styles.autosavePill,
              saveState === "saving" && styles.autosavePillSaving,
              saveState === "saved" && styles.autosavePillSaved,
              saveState === "error" && styles.autosavePillError,
            ]}
          >
            <Ionicons
              name={
                saveState === "saving" ? "sync"
                : saveState === "saved" ? "checkmark-circle"
                : saveState === "error" ? "warning"
                : "ellipse-outline"
              }
              size={11}
              color="#FFFFFF"
            />
            <Text style={styles.autosavePillText} testID="checklist-save-state">
              {saveState === "saving" ? "Saving…"
               : saveState === "saved" ? "Saved"
               : saveState === "error" ? "Save error — will retry"
               : "Ready"}
            </Text>
          </View>

          {/* Phase 40 · Step 2 — expanded network pill. Priority order:
                1. syncing (any queued entry being flushed right now)
                2. sync error (server rejected an entry — tap to retry)
                3. offline + queue count OR offline+cached bootstrap
                4. online + synced (steady state). */}
          {(() => {
            const queued = queueState.count;
            const isSyncing = queueState.syncing;
            const isSyncError = !!queueState.lastError && !isSyncing && online;
            let pillStyle: any = styles.networkPillOnline;
            let label = "Online · Synced";
            let icon: any = "cloud-done-outline";
            let testState = "online";
            let onPress: (() => void) | undefined;
            if (isSyncing) {
              pillStyle = styles.networkPillSyncing;
              label = queued > 0 ? `Syncing… (${queued})` : "Syncing…";
              icon = "sync";
              testState = "syncing";
            } else if (isSyncError) {
              pillStyle = styles.networkPillError;
              label = "Sync error — retry";
              icon = "alert-circle-outline";
              testState = "error";
              onPress = () => { writeQueue.flush().catch(() => {}); };
            } else if (!online) {
              pillStyle = styles.networkPillOffline;
              label = queued > 0
                ? `Offline · ${queued} queued`
                : (offlineMode ? "Offline · cached" : "Offline");
              icon = "cloud-offline-outline";
              testState = "offline";
            } else if (queued > 0) {
              // Online but queue not yet drained — likely just reconnected.
              pillStyle = styles.networkPillSyncing;
              label = `Syncing… (${queued})`;
              icon = "sync";
              testState = "syncing";
            }
            const PillTag: any = onPress ? Pressable : View;
            return (
              <PillTag
                style={[styles.networkPill, pillStyle]}
                testID="checklist-network-pill"
                onPress={onPress}
                accessibilityRole={onPress ? "button" : undefined}
              >
                <Ionicons name={icon} size={11} color="#FFFFFF" />
                <Text
                  style={styles.networkPillText}
                  testID={`checklist-network-pill-state-${testState}`}
                >
                  {label}
                </Text>
              </PillTag>
            );
          })()}

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

        {/* Photos — always visible */}
        <View style={styles.card} testID="checklist-photos-card">
          <Text style={styles.cardTitle}>Photos</Text>
          <PhotoUploader
            jobId={String(id)}
            photos={report.photos || []}
            onPhotosChange={(next) => setReport({ ...report, photos: next })}
            max={PHOTO_CAP}
            disabled={locked}
          />
        </View>

        {/* Videos — Phase 5B */}
        <View style={styles.card} testID="checklist-videos-card">
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
      </ScrollView>

      {!locked && (
        <View style={styles.footer}>
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
      <VisitRecapModal
        visible={recapOpen && !!report?.id}
        serviceReportId={report?.id || null}
        customer={recapCustomer}
        onClose={() => {
          setRecapOpen(false);
          const invId = report?.invoice_id
            ? ` · Invoice #${String(report.invoice_id).slice(0, 8)}` : "";
          Alert.alert("Job closed", `Report submitted${invId}.`, [
            { text: "OK", onPress: () => router.replace("/(app)/schedule/calendar") },
          ]);
        }}
      />
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
});
