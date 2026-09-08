/**
 * Phase 18B follow-up — Mobile Service Report.
 * Auto-loaded after clock-in. Autosaves every 5s. Photo cap 10 (server-enforced).
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, Alert } from 'react-native';
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { writeCache, readCache } from "@/src/services/readCache";
// Feb-2026 · Chemistry required-readings gate — mirror of backend
// helper (see ``backend/services/chemistry_gate.py``).
import { missingCoreReadings } from "@/utils/chemistryGate";
import { expandChemistryLabel } from "@/src/lib/expandChemistryLabel";
import { canonicalReadingKey } from "@/src/components/checklist/PoolChecklistForm";
import ReadingChipRow from "@/src/components/checklist/ReadingChipRow";
import { formatCustomerName } from "@/src/utils/formatCustomerName";

// Feb-2026 · Required-reading keys — covers all canonical/alias forms.
// Mirrors the Set in PoolChecklistForm.tsx.
const REQUIRED_READING_KEYS = new Set<string>([
  "free_chlorine", "total_chlorine",
  "alkalinity", "total_alkalinity",
  "ph", "cyanuric_acid", "cya",
]);

const AUTOSAVE_MS = 5000;
const PHOTO_CAP = 10;

export default function ServiceReportScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [report, setReport] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [saveState, setSaveState] = useState<"idle"|"saving"|"saved"|"error">("idle");
  const dirtyRef = useRef(false);
  const savingRef = useRef(false);

  const [picker, setPicker] = useState<null | {
    title: string; options: string[]; current: string; onSelect: (v: string) => void;
  }>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setBusy(true);
    try {
      const data = await api.get(`/jobs/${id}/service-report`);
      setReport(data);
      writeCache(`service-report:${id}`, data).catch(() => {});
    } catch {
      const cached = await readCache<any>(`service-report:${id}`);
      if (cached) setReport(cached);
    }
    finally { setBusy(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const patchSave = useCallback(async () => {
    if (!dirtyRef.current || savingRef.current || !report || report.submitted_at) return;
    savingRef.current = true;
    setSaveState("saving");
    try {
      await api.request?.(`/jobs/${id}/service-report`, {
        method: "PATCH",
        body: JSON.stringify({
          chemical_readings: report.chemical_readings,
          chemicals_added: report.chemicals_added,
          checklist_items: report.checklist_items,
          notes: report.notes,
          observations: report.observations,
        }),
      });
      dirtyRef.current = false;
      setSaveState("saved");
      setTimeout(() => setSaveState((s) => (s === "saved" ? "idle" : s)), 1500);
    } catch (e) {
      // Fallback: PUT is idempotent enough; but api.put isn't set up for this path.
      // Best-effort: POST to submit is separate — do nothing here.
      setSaveState("error");
    } finally {
      savingRef.current = false;
    }
  }, [id, report]);

  // Fallback PATCH via fetch since api client doesn't expose patch.
  const patchViaFetch = async (bodyObj: any) => {
    const base = process.env.EXPO_PUBLIC_BACKEND_URL;
    const { TOKEN_KEY } = await import("@/src/api");
    const { storage } = await import("@/src/utils/storage");
    const token = await storage.secureGet<string>(TOKEN_KEY, "");
    const r = await fetch(`${base}/api/jobs/${id}/service-report`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(bodyObj),
    });
    if (!r.ok) throw new Error((await r.text()) || `PATCH failed ${r.status}`);
    return r.json();
  };

  useEffect(() => {
    const t = setInterval(async () => {
      if (!dirtyRef.current || savingRef.current || !report || report.submitted_at) return;
      savingRef.current = true;
      setSaveState("saving");
      try {
        await patchViaFetch({
          chemical_readings: report.chemical_readings,
          chemicals_added: report.chemicals_added,
          checklist_items: report.checklist_items,
          notes: report.notes,
          observations: report.observations,
        });
        dirtyRef.current = false;
        setSaveState("saved");
        setTimeout(() => setSaveState((s) => (s === "saved" ? "idle" : s)), 1500);
      } catch { setSaveState("error"); }
      finally { savingRef.current = false; }
    }, AUTOSAVE_MS);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report?.notes, report?.chemical_readings, report?.chemicals_added, report?.checklist_items, report?.observations]);

  const markDirty = () => { dirtyRef.current = true; };

  const addPhoto = async (fromCamera: boolean) => {
    if (!report) return;
    if ((report.photos?.length || 0) >= PHOTO_CAP) {
      Alert.alert("Photo cap", "10 photos max per job.");
      return;
    }
    const perm = fromCamera
      ? await ImagePicker.requestCameraPermissionsAsync()
      : await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) { Alert.alert("Permission needed"); return; }
    const pick = fromCamera
      ? await ImagePicker.launchCameraAsync({ quality: 0.6, base64: true })
      : await ImagePicker.launchImageLibraryAsync({ quality: 0.6, base64: true });
    if (pick.canceled || !pick.assets?.length) return;
    const a: any = pick.assets[0];
    const dataUrl = `data:${a.mimeType || "image/jpeg"};base64,${a.base64}`;
    try {
      const updated = await api.post(`/jobs/${id}/photos`, {
        data: dataUrl, label: `svc-${new Date().toISOString()}`,
      });
      setReport({ ...report, photos: updated.photos || [] });
    } catch (e: any) {
      Alert.alert("Upload failed", e?.message || "Try again.");
    }
  };

  const removePhoto = async (pid: string) => {
    if (!report) return;
    try {
      const updated = await api.del(`/jobs/${id}/photos/${pid}`);
      setReport({ ...report, photos: updated.photos || [] });
    } catch (e: any) { Alert.alert("Delete failed", e?.message || ""); }
  };

  const updChem = (idx: number, val: string) => {
    const next = [...report.chemical_readings];
    next[idx] = { ...next[idx], value: val === "" ? null : parseFloat(val),
                  ts: new Date().toISOString() };
    setReport({ ...report, chemical_readings: next });
    markDirty();
  };
  const toggleCheck = (idx: number) => {
    const next = [...report.checklist_items];
    next[idx] = { ...next[idx], checked: !next[idx].checked };
    setReport({ ...report, checklist_items: next });
    markDirty();
  };

  const submitAndClockOut = async () => {
    // Feb-2026 · Client mirror of the backend gate.  Same rules as
    // ``services/chemistry_gate.py`` so we never let a submit slip
    // past that the API would then 422.
    const missing = missingCoreReadings(report?.chemical_readings || []);
    if (missing.length > 0) {
      Alert.alert(
        "Cannot submit yet",
        `Missing required chemistry readings: ${missing.join(", ")}.`,
      );
      return;
    }
    Alert.alert("Submit report", "Submit this report and clock out?", [
      { text: "Cancel", style: "cancel" },
      { text: "Submit", onPress: async () => {
          try {
            await patchViaFetch({
              chemical_readings: report.chemical_readings,
              chemicals_added: report.chemicals_added,
              checklist_items: report.checklist_items,
              notes: report.notes,
              observations: report.observations,
            });
            const submitted: any = await api.post(`/jobs/${id}/service-report/submit`, {});
            try { await api.post("/workforce/clock-out", {}); } catch {}
            if (submitted?.invoice_id) {
              const iid = String(submitted.invoice_id).slice(0, 8);
              Alert.alert("Auto-invoiced",
                          `Report submitted · Invoice #${iid} created`,
                          [{ text: "OK", onPress: () => router.replace("/(app)/today") }]);
            } else {
              router.replace("/(app)/today");
            }
          } catch (e: any) {
            // Feb-2026 · Surface the backend 422 (chemistry gate)
            // as a friendly warning instead of a generic error so
            // the tech knows exactly which fields to fill.
            const detail = e?.response?.data?.detail || e?.detail;
            if (
              detail && typeof detail === "object"
              && detail.detail === "chemistry_core_readings_missing"
            ) {
              const missed = (detail.missing_labels || detail.missing_fields || []).join(", ");
              Alert.alert(
                "Cannot submit yet",
                `Missing required chemistry readings: ${missed}.`,
              );
            } else {
              Alert.alert("Submit failed", e?.message || "");
            }
          }
        }}
    ]);
  };

  if (busy && !report) return (
    <View style={styles.center}><ActivityIndicator size="large" color={colors.brand}/></View>
  );
  if (!report) return (
    <View style={styles.center}><Text style={styles.err}>Unable to load report.</Text></View>
  );
  const isPool = report.template === "pool";
  const locked = !!report.submitted_at;
  const photos = report.photos || [];
  const remaining = PHOTO_CAP - photos.length;
  const job = report.job || {};

  return (
    <View style={styles.root}>
      <Header title="Service Report"/>
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 200 }}>
        <View style={styles.hero}>
          <Text style={styles.heroLabel}>{report.template} template{locked ? " · LOCKED" : ""}</Text>
          <Text style={styles.heroTitle}>{job.title || job.service_type || "Service"}</Text>
          <Text style={styles.heroSub}>{formatCustomerName(job)} · {job.address || ""}</Text>
          {job.gate_code && (
            <View style={styles.gate}>
              <Ionicons name="key-outline" size={12} color="#92400E"/>
              <Text style={styles.gateText}>{job.gate_code}</Text>
            </View>
          )}
          <Text style={styles.saveState}>
            {saveState === "saving" ? "Saving…"
              : saveState === "saved" ? "Saved"
              : saveState === "error" ? "Save error"
              : "Ready"}
          </Text>
        </View>

        {/* Photos */}
        <SectionCard title="Photos" subtitle={`${photos.length} / ${PHOTO_CAP}`}
                     testID="svc-report-photos">
          <View style={styles.photoGrid}>
            {photos.map((p: any) => (
              <View key={p.id} style={styles.photoCell}>
                <Image source={{ uri: p.data || p.url }} style={styles.photoImg} contentFit="cover"/>
                {!locked && (
                  <Pressable style={styles.photoDel} onPress={() => removePhoto(p.id)}
                             testID={`svc-photo-del-${p.id}`}>
                    <Ionicons name="close" size={12} color="#fff"/>
                  </Pressable>
                )}
              </View>
            ))}
            {!locked && remaining > 0 && (
              <View style={styles.photoCell}>
                <Pressable style={styles.photoAdd} onPress={() => addPhoto(true)}
                           testID="svc-photo-camera">
                  <Ionicons name="camera-outline" size={22} color={colors.muted}/>
                  <Text style={styles.photoAddText}>Camera</Text>
                </Pressable>
              </View>
            )}
            {!locked && remaining > 0 && (
              <View style={styles.photoCell}>
                <Pressable style={styles.photoAdd} onPress={() => addPhoto(false)}
                           testID="svc-photo-library">
                  <Ionicons name="images-outline" size={22} color={colors.muted}/>
                  <Text style={styles.photoAddText}>Library</Text>
                </Pressable>
              </View>
            )}
          </View>
        </SectionCard>

        {/* Chemical Readings — pool only — unified canonical block (Feb-2026) */}
        {isPool && (
          <SectionCard title="Chemical Readings" testID="svc-report-readings">
            <View>
              {(report.chemical_readings || []).map((r: any, i: number) => {
                const key = canonicalReadingKey(r);
                return (
                  <ReadingChipRow
                    key={key}
                    readingKey={key}
                    label={expandChemistryLabel(r.name)}
                    unit={r.unit}
                    value={r.value}
                    locked={locked}
                    required={REQUIRED_READING_KEYS.has(key)}
                    onChange={(v) => updChem(i, String(v ?? ""))}
                  />
                );
              })}
            </View>
          </SectionCard>
        )}

        {/* Visible-algae toggle — pool only (Phase 56.10 web parity, Feb 2026). */}
        {isPool && (
          <SectionCard title="Visible Algae" testID="svc-report-algae"
            subtitle="Trigger AI algae remediation dosing">
            <View style={styles.algaeRow}>
              {[
                { value: "none",  label: "None",  bg: colors.surface,       fg: colors.onSurface, border: colors.border },
                { value: "light", label: "Light", bg: "#FEF3C7",             fg: "#92400E",         border: "#FCD34D" },
                { value: "heavy", label: "Heavy", bg: "#FEE2E2",             fg: "#991B1B",         border: "#FCA5A5" },
              ].map((opt) => {
                const current = ((report.observations || {}).visible_algae || "none").toLowerCase();
                const active = current === opt.value;
                return (
                  <Pressable
                    key={opt.value}
                    disabled={locked}
                    onPress={() => {
                      markDirty();
                      setReport({
                        ...report,
                        observations: { ...(report.observations || {}), visible_algae: opt.value },
                      });
                    }}
                    style={[
                      styles.algaeBtn,
                      {
                        backgroundColor: active ? opt.bg : colors.surfaceSecondary,
                        borderColor: active ? opt.border : colors.border,
                        opacity: locked ? 0.5 : 1,
                      },
                    ]}
                    testID={`svc-algae-${opt.value}`}
                  >
                    <Text style={[styles.algaeBtnLabel, { color: active ? opt.fg : colors.muted, fontWeight: active ? "700" : "500" }]}>
                      {opt.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
            <Text style={styles.algaeHint}>
              Toggling Light or Heavy adds algae-remediation doses to the AI recommendation on the web wizard.
            </Text>
          </SectionCard>
        )}

        {/* Chemicals Added — pool only */}
        {isPool && (
          <SectionCard title="Chemicals Added" testID="svc-report-chems"
            subtitle={`${(report.chemicals_added || []).length} added`}>
            {(report.chemicals_added || []).map((c: any, i: number) => {
              const entry = (report.chemicals_catalog || []).find((k: any) => k.name === c.name);
              const amountOpts: string[] = entry?.amount_options || [];
              const unitOpts: string[] = (entry?.common_units?.length
                ? entry.common_units
                : (report.chemical_units || ["gal", "lbs", "oz", "tabs"]));
              return (
                <View key={c.id || i} style={styles.chemRow} testID={`svc-chem-row-${i}`}>
                  <Pressable style={[styles.selectBox, { flex: 3 }]}
                    onPress={() => !locked && setPicker({
                      title: "Chemical",
                      options: (report.chemicals_catalog || []).map((k: any) => k.name),
                      current: c.name,
                      onSelect: (v) => {
                        const en = (report.chemicals_catalog || []).find((k: any) => k.name === v);
                        const next = [...report.chemicals_added];
                        next[i] = { ...next[i], name: v, unit: en?.default_unit || next[i].unit };
                        setReport({ ...report, chemicals_added: next });
                        markDirty(); setPicker(null);
                      },
                    })}
                    testID={`svc-chem-name-${i}`}>
                    <Text style={c.name ? styles.selectValue : styles.selectPlaceholder}>
                      {c.name || "Select chemical…"}
                    </Text>
                    <Ionicons name="chevron-down" size={15} color={colors.muted}/>
                  </Pressable>
                  <Pressable style={[styles.selectBox, { flex: 2 }]}
                    onPress={() => !locked && setPicker({
                      title: "Amount",
                      options: amountOpts.length ? amountOpts : ["0.5","1","1.5","2","2.5","3"],
                      current: String(c.amount || ""),
                      onSelect: (v) => {
                        const next = [...report.chemicals_added];
                        next[i] = { ...next[i], amount: v };
                        setReport({ ...report, chemicals_added: next });
                        markDirty(); setPicker(null);
                      },
                    })}
                    testID={`svc-chem-amount-${i}`}>
                    <Text style={c.amount ? styles.selectValue : styles.selectPlaceholder}>
                      {c.amount || "—"}
                    </Text>
                    <Ionicons name="chevron-down" size={15} color={colors.muted}/>
                  </Pressable>
                  <Pressable style={[styles.selectBox, { flex: 2 }]}
                    onPress={() => !locked && setPicker({
                      title: "Unit",
                      options: unitOpts,
                      current: c.unit || "",
                      onSelect: (v) => {
                        const next = [...report.chemicals_added];
                        next[i] = { ...next[i], unit: v };
                        setReport({ ...report, chemicals_added: next });
                        markDirty(); setPicker(null);
                      },
                    })}
                    testID={`svc-chem-unit-${i}`}>
                    <Text style={c.unit ? styles.selectValue : styles.selectPlaceholder}>
                      {c.unit || "unit"}
                    </Text>
                    <Ionicons name="chevron-down" size={15} color={colors.muted}/>
                  </Pressable>
                  {!locked && (
                    <Pressable onPress={() => {
                        const next = report.chemicals_added.filter((_: any, x: number) => x !== i);
                        setReport({ ...report, chemicals_added: next });
                        markDirty();
                      }}
                      testID={`svc-chem-remove-${i}`}>
                      <Ionicons name="trash-outline" size={20} color={colors.error}/>
                    </Pressable>
                  )}
                </View>
              );
            })}
            {!locked && (
              <Pressable
                onPress={() => {
                  const next = [...(report.chemicals_added || []),
                    { id: Math.random().toString(36).slice(2), name: "", amount: "", unit: "lbs" }];
                  setReport({ ...report, chemicals_added: next });
                  markDirty();
                }}
                style={styles.addChemBtn}
                testID="svc-add-chemical">
                <Ionicons name="add" size={16} color={colors.brand}/>
                <Text style={styles.addChemText}>Add another chemical</Text>
              </Pressable>
            )}
          </SectionCard>
        )}

        {/* Checklist */}
        <SectionCard title="Checklist" testID="svc-report-checklist">
          {(report.checklist_items || []).map((c: any, i: number) => (
            <Pressable key={c.id}
                       style={[styles.checkRow, c.checked && styles.checkRowOn]}
                       onPress={() => !locked && toggleCheck(i)}
                       testID={`svc-check-${c.id}`}>
              <Ionicons name={c.checked ? "checkbox" : "square-outline"}
                        size={22} color={c.checked ? colors.success : colors.muted}/>
              <Text style={styles.checkText}>{c.label}</Text>
            </Pressable>
          ))}
        </SectionCard>

        {/* Notes */}
        <SectionCard title="Notes" testID="svc-report-notes">
          <TextInput
            multiline numberOfLines={4}
            editable={!locked}
            style={styles.textarea}
            value={report.notes || ""}
            placeholder="Anything the customer or dispatcher should know…"
            placeholderTextColor={colors.muted}
            onChangeText={(v) => { setReport({ ...report, notes: v }); markDirty(); }}
            testID="svc-report-notes-input"
          />
        </SectionCard>
      </ScrollView>

      {!locked && (
        <View style={styles.footer}>
          {(() => {
            const missing = missingCoreReadings(report?.chemical_readings || []);
            const gateOk = missing.length === 0;
            return (
              <>
                {!gateOk && (
                  <Text
                    style={{
                      color: "#78350F",
                      backgroundColor: "#FEF3C7",
                      borderColor: "#FDE68A",
                      borderWidth: 1,
                      borderRadius: 8,
                      paddingHorizontal: 10,
                      paddingVertical: 6,
                      marginBottom: 8,
                      fontSize: fontSize.sm,
                    }}
                    testID="chem-gate-missing-hint"
                  >
                    Missing: {missing.join(", ")}
                  </Text>
                )}
                <Pressable
                  style={[
                    styles.submitBtn,
                    !gateOk && { opacity: 0.5, backgroundColor: colors.muted },
                  ]}
                  onPress={submitAndClockOut}
                  disabled={!gateOk}
                  testID="svc-report-submit"
                >
                  <Ionicons name="shield-checkmark-outline" size={18} color="#fff"/>
                  <Text style={styles.submitBtnText}>Submit & Clock Out</Text>
                </Pressable>
              </>
            );
          })()}
        </View>
      )}
    </View>
  );
}

function SectionCard({ title, subtitle, children, testID }: any) {
  return (
    <View style={styles.card} testID={testID}>
      <View style={styles.cardHead}>
        <Text style={styles.cardTitle}>{title}</Text>
        {subtitle && <Text style={styles.cardSub}>{subtitle}</Text>}
      </View>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  err: { fontFamily: font.semibold, color: colors.error },
  hero: {
    backgroundColor: colors.brand,
    borderRadius: radius.lg,
    padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  heroLabel: { fontFamily: font.bold, fontSize: fontSize.xs, color: "#fff",
    opacity: 0.9, letterSpacing: 1, textTransform: "uppercase" },
  heroTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: "#fff",
    marginTop: 4 },
  heroSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: "#fff",
    opacity: 0.9, marginTop: 4 },
  gate: { flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#FEF3C7", alignSelf: "flex-start",
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8, marginTop: 8 },
  gateText: { fontFamily: "SpaceMono" as any || font.bold, color: "#92400E",
    fontSize: fontSize.sm },
  saveState: { fontFamily: font.semibold, color: "#fff", opacity: 0.85,
    marginTop: 8, fontSize: fontSize.xs },
  card: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.md,
  },
  cardHead: { flexDirection: "row", justifyContent: "space-between",
    alignItems: "center", marginBottom: spacing.sm },
  cardTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  cardSub: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  photoGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  photoCell: { width: "31%", aspectRatio: 1 },
  photoImg: { width: "100%", height: "100%", borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary },
  photoDel: { position: "absolute", top: 4, right: 4,
    backgroundColor: "rgba(0,0,0,0.7)", borderRadius: 12,
    padding: 4, alignItems: "center", justifyContent: "center" },
  photoAdd: { flex: 1, borderRadius: radius.md, borderWidth: 2,
    borderColor: colors.border, borderStyle: "dashed",
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceSecondary },
  photoAddText: { fontFamily: font.bold, fontSize: fontSize.xs,
    color: colors.muted, marginTop: 4, textTransform: "uppercase" },
  // readingGrid + readingCell removed — Feb 2026 chemistry unification.
  //   Readings now use the canonical ReadingChipRow component.
  readingLabel: { fontFamily: font.bold, fontSize: fontSize.xs,
    color: colors.muted, textTransform: "uppercase", marginBottom: 4 },
  algaeRow: { flexDirection: "row", gap: spacing.sm, marginBottom: 6 },
  algaeBtn: {
    flex: 1, paddingVertical: 12, borderRadius: radius.md,
    borderWidth: 1, alignItems: "center", justifyContent: "center",
  },
  algaeBtnLabel: { fontFamily: font.medium, fontSize: fontSize.sm },
  algaeHint: { fontFamily: font.regular, fontSize: 11,
    color: colors.muted, marginTop: 4, lineHeight: 15 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.sm, paddingVertical: 10,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  textarea: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, minHeight: 100, textAlignVertical: "top",
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  checkRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, marginBottom: spacing.xs,
  },
  checkRowOn: { borderColor: colors.success, backgroundColor: "#F0FDF4" },
  checkText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base,
    color: colors.onSurface },
  footer: {
    position: "absolute", bottom: 0, left: 0, right: 0,
    padding: spacing.md, backgroundColor: colors.surface,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  submitBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.sm, backgroundColor: colors.brand, borderRadius: radius.md,
    paddingVertical: 14,
  },
  submitBtnText: { fontFamily: font.bold, color: "#fff", fontSize: fontSize.lg },
  selectBox: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.sm, paddingVertical: 10,
    backgroundColor: colors.surface,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
  },
  selectValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  selectPlaceholder: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  chemRow: {
    flexDirection: "row", gap: spacing.xs, alignItems: "center",
    marginBottom: spacing.sm,
  },
  addChemBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 10, borderRadius: radius.md,
    borderWidth: 2, borderStyle: "dashed", borderColor: colors.brand,
    marginTop: spacing.sm,
  },
  addChemText: { fontFamily: font.bold, color: colors.brand, fontSize: fontSize.sm },
  pickerBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)" },
  pickerSheet: {
    position: "absolute", bottom: 0, left: 0, right: 0,
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20, borderTopRightRadius: 20,
    paddingBottom: 30,
  },
  pickerHead: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  pickerTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  pickerRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: 14,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  pickerRowOn: { backgroundColor: colors.brandTertiary },
  pickerRowText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  pickerRowTextOn: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
});
