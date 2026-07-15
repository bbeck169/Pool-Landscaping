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
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { getChecklistType, ChecklistType } from "@/src/utils/checklistType";
import PhotoUploader from "@/src/components/checklist/PhotoUploader";
import PoolChecklistForm from "@/src/components/checklist/PoolChecklistForm";
import LandscapingChecklistForm from "@/src/components/checklist/LandscapingChecklistForm";
import GenericChecklistForm from "@/src/components/checklist/GenericChecklistForm";
import VisitRecapModal from "@/src/components/checklist/VisitRecapModal";
import { cacheJobBootstrap, getCachedBootstrap } from "@/src/services/offlineCache";

const AUTOSAVE_DEBOUNCE_MS = 800;
// Phase 37 — minimum time the pill stays on "Saving…" so techs actually
// see the transition after a chip tap on the mobile checklist.
const MIN_SAVING_MS = 400;
const PHOTO_CAP = 10;

export default function JobChecklistScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();

  const role = user?.role || "";
  const canWrite = role === "admin" || role === "super_admin" || role === "technician";

  const [job, setJob] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
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

  // ─── Load ───────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const [jobResp, reportResp] = await Promise.all([
        api.get(`/jobs/${id}`),
        api.get(`/jobs/${id}/service-report`),
      ]);
      setJob(jobResp);
      setReport(reportResp);
      setOfflineMode(false);
      // Cache the bootstrap for later offline access.
      await cacheJobBootstrap(String(id), { job: jobResp, report: reportResp });
    } catch (e: any) {
      // Phase 40 · Try to fall back to cache before surfacing the error.
      const cached = await getCachedBootstrap(String(id));
      if (cached?.job && cached?.report) {
        setJob(cached.job);
        setReport(cached.report);
        setOfflineMode(true);
      } else {
        Alert.alert("Unable to open checklist", e?.message || "Try again.");
      }
    } finally {
      setLoading(false);
    }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  // ─── Autosave (debounced) ────────────────────────────────────────────
  const flushSave = useCallback(async () => {
    if (!report || report.submitted_at) return;
    if (!dirtyRef.current || savingRef.current) return;
    savingRef.current = true;
    if (!savingShownAtRef.current) savingShownAtRef.current = Date.now();
    setSaveState("saving");
    try {
      const patched = await api.patch(`/jobs/${id}/service-report`, {
        chemical_readings: report.chemical_readings,
        chemicals_added: report.chemicals_added,
        checklist_items: report.checklist_items,
        notes: report.notes,
      });
      if (patched && typeof patched === "object") setReport(patched);
      dirtyRef.current = false;
      const elapsed = Date.now() - (savingShownAtRef.current || Date.now());
      const holdMs = Math.max(0, MIN_SAVING_MS - elapsed);
      setTimeout(() => {
        setSaveState("saved");
        savingShownAtRef.current = 0;
        setTimeout(() => setSaveState((s) => (s === "saved" ? "idle" : s)), 1200);
      }, holdMs);
    } catch (e) {
      setSaveState("error");
      savingShownAtRef.current = 0;
    } finally {
      savingRef.current = false;
    }
  }, [id, report]);

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
    setReport((prev: any) => ({ ...prev, ...patch }));
    scheduleAutosave();
  }, [scheduleAutosave]);

  // ─── Save draft (explicit) ───────────────────────────────────────────
  const saveDraft = async () => {
    dirtyRef.current = true;
    await flushSave();
    Alert.alert("Saved", "Draft saved.");
  };

  // ─── Close job ───────────────────────────────────────────────────────
  const closeJob = async () => {
    if (!report || submitting) return;
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
              dirtyRef.current = true;
              await flushSave();

              // 2) Submit / close.
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
                  setRecapCustomer({
                    id: cust?.id, name: cust?.name,
                    email: cust?.email, phone: cust?.phone,
                    alert_phone: cust?.alert_phone,
                  });
                } else {
                  setRecapCustomer({ name: job?.customer_name });
                }
              } catch { setRecapCustomer({ name: job?.customer_name }); }
              setRecapOpen(true);
            } catch (e: any) {
              Alert.alert("Close failed", e?.message || "Try again.");
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
        <Text style={styles.forbiddenText}>You don't have permission to open this checklist.</Text>
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

  return (
    <View style={styles.root}>
      <Header title="Job Checklist" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 160 }}>
        <View style={styles.hero} testID="checklist-hero">
          <Text style={styles.heroLabel}>
            {clientType} · backend:{backendKind}{locked ? " · LOCKED" : ""}
          </Text>
          <Text style={styles.heroTitle}>
            {job.title || job.service_type || "Service"}
          </Text>
          <Text style={styles.heroSub}>
            {job.customer_name || "—"} · {job.address || ""}
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

          {/* Phase 40 · Step 1 — network pill. Distinct from the autosave
              pill: the autosave is per-field; this reflects the whole
              screen's connection state. Only two states shipped in Step 1
              (Online · Synced, Offline · cached). Step 2 will add
              "Syncing…" and "N queued" once the write queue lands. */}
          <View
            style={[
              styles.networkPill,
              offlineMode ? styles.networkPillOffline : styles.networkPillOnline,
            ]}
            testID="checklist-network-pill"
          >
            <Ionicons
              name={offlineMode ? "cloud-offline-outline" : "cloud-done-outline"}
              size={11}
              color="#FFFFFF"
            />
            <Text style={styles.networkPillText}>
              {offlineMode ? "Offline · cached" : "Online · Synced"}
            </Text>
          </View>
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

        {/* Template-specific form */}
        <View style={styles.card} testID={`checklist-form-${clientType}`}>
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
              onChange={patchReport}
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
  networkPillText: {
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
