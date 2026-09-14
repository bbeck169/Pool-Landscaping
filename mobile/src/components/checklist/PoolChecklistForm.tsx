/**
 * Phase 31 · Step 2a — PoolChecklistForm (mobile).
 *
 * Backend-driven pool form. Renders the fields returned by the
 * bootstrap service-report GET:
 *   • chemical_reading_fields  → numeric inputs (pH, Free Cl, Total Alk, etc.)
 *   • chemicals_catalog        → repeatable "chemicals added" rows
 *   • checklist_items          → grooming checklist
 *   • notes                    → free-text
 *
 * "Analyze water photo" opens the image picker, uploads the photo via
 * `POST /api/jobs/{id}/photos` to obtain a public URL, then calls
 * `POST /api/service-report/analyze-water-photo` and surfaces the AI
 * recommendations. It does NOT auto-fill readings — the endpoint
 * returns clarity/issues/recommendations, not numeric values, so
 * silently filling would be dishonest. If the response contains
 * `mocked: true` or an error, the `reason` string is shown as-is.
 */
import React, { useState, useEffect, useMemo, useCallback } from "react";
import {
  View, Text, TextInput, Pressable, StyleSheet, Alert, ActivityIndicator, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
// K60 · Feb-2026 — expand short-form chemistry labels (FC, TA, CYA, …)
// to full names on the display surface.  Data keys unchanged.
import ChemicalDropdownStack, { snapRecommendationToPreset } from "./ChemicalDropdownStack";
import ChemicalPickerSheet from "./ChemicalPickerSheet";
// Phase 44 · Fix 5 — `react-native-draggable-flatlist` uses
// `setPointerCapture` on web which throws inside the RN-Web synthetic
// event target. Gate the drag list to native only; on web we render a
// plain map() of rows with no drag handle (same rows/checkbox
// semantics, just no reorder). Techs on real devices — the target
// audience — keep the drag UX; Expo Web keeps the checklist
// functional.
import DraggableFlatList, { RenderItemParams, ScaleDecorator } from "react-native-draggable-flatlist";
const DRAG_REORDER_ENABLED = Platform.OS !== "web";

// Phase 37 — canonical testid key (parity with web PoolChecklistForm.jsx).
const _NAME_TO_CANONICAL: Record<string, string> = {
  "free chlorine": "free_chlorine",
  "total chlorine": "total_chlorine",
  "combined chlorine": "combined_chlorine",    // kept for historic data reads
  "chlorine": "free_chlorine",
  "ph": "ph",
  "ph level": "ph",
  "total alkalinity": "total_alkalinity",
  "alkalinity": "total_alkalinity",
  "calcium hardness": "calcium_hardness",
  "cyanuric acid": "cyanuric_acid",
  "cya": "cyanuric_acid",
  "cyanuric": "cyanuric_acid",
  "salt": "salt",
  "total dissolved solids": "tds",
  "tds": "tds",
  "phosphates": "phosphates",
  "phosphate": "phosphates",
  "water temp": "water_temp",
  "water temperature": "water_temp",
  "temperature": "water_temp",
  "filter psi": "filter_psi",
  "psi": "filter_psi",
  // Short-form abbreviations (backend template defaults)
  "fc": "free_chlorine",
  "tc": "total_chlorine",
  "cc": "combined_chlorine",                    // kept for historic data reads
  "ta": "total_alkalinity",
  "ch": "calcium_hardness",
  "po4": "phosphates",
  "water_temp": "water_temp",
};
export function canonicalReadingKey(r: { key?: string; name?: string }): string {
  const name = String(r?.name || "").toLowerCase().trim();
  if (_NAME_TO_CANONICAL[name]) return _NAME_TO_CANONICAL[name];
  const rawKey = String(r?.key || r?.name || "").toLowerCase().trim();
  if (_NAME_TO_CANONICAL[rawKey]) return _NAME_TO_CANONICAL[rawKey];
  return rawKey.replace(/[\s()]+/g, "_").replace(/[^a-z0-9_]/g, "");
}

// Feb-2026 · Unification — Re-export ReadingChipRow as ReadingInputRow
// so callers can import the canonical component name used by the web.
export { default as ReadingInputRow } from "./ReadingChipRow";

type Reading = {
  key?: string; name: string; unit?: string; value: number | string | null;
  step?: number | string; min?: number; max?: number;
};
type ChemAdded = {
  id?: string; name: string; amount: string | number; unit: string;
};
type CatalogEntry = {
  name: string; default_unit?: string;
  common_units?: string[]; amount_options?: string[];
};
type ChecklistItem = { id: string; label: string; checked: boolean; notes?: string };

export type PoolChecklistFormProps = {
  jobId: string;
  customerId?: string | null;
  locked: boolean;
  readings: Reading[];
  readingFields: any[];
  chemicalsAdded: ChemAdded[];
  chemicalsCatalog: CatalogEntry[];
  chemicalUnits: string[];
  checklistItems: ChecklistItem[];
  notes: string;
  // Phase 56.7 mobile parity — internal notes textarea (private, admin
  // + tech only) exposed on wizard step 6. Optional so legacy callers
  // that haven't been updated to the wizard shell keep working.
  internalNotes?: string;
  // Phase 56.10 — visible-algae observation from the report doc.
  observations?: { visible_algae?: "none" | "light" | "heavy" };
  // Phase 56.7 — when set (1..6), only render the section matching
  // that step. `null` (default) ⇒ render everything (legacy scroll).
  wizardStep?: number | null;
  // Feb-2026 · Checklist reclassifier — parity with the web branch. See
  // frontend/src/components/checklist/PoolChecklistForm.jsx.
  template?: string | null;
  canEditServiceType?: boolean;
  onReclassify?: ((nextServiceType: string) => Promise<void> | void) | null;
  onChange: (patch: Partial<{
    chemical_readings: Reading[];
    chemicals_added: ChemAdded[];
    checklist_items: ChecklistItem[];
    notes: string;
    internal_notes: string;
    observations: any;
  }>) => void;
};

export default function PoolChecklistForm(props: PoolChecklistFormProps) {
  const {
    jobId, customerId, locked, readings, chemicalsAdded, chemicalsCatalog, chemicalUnits,
    checklistItems, notes, onChange,
  } = props;
  const internalNotes = props.internalNotes || "";
  const wizardStep = props.wizardStep ?? null;
  // Feb-2026 · Checklist reclassifier — busy flag between picker tap
  // and parent PATCH+refetch (see props.onReclassify).
  const [reclassifyBusy, setReclassifyBusy] = useState(false);
  // Helper: `inStep(n)` returns true when we're either in wizard mode
  // on step `n` or when wizard mode is off. Keeps section guards to a
  // single readable check downstream.
  const inStep = (n: number) => wizardStep === null || wizardStep === n;

  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<null | {
    mocked?: boolean;
    reason?: string;
    clarity?: string | null;
    issues?: string[];
    recommendations?: string[];
    overall_assessment?: string | null;
  }>(null);

  const addChem = () => {
    const next = [
      ...chemicalsAdded,
      { id: Math.random().toString(36).slice(2), name: "", amount: "", unit: chemicalUnits[0] || "lbs" },
    ];
    onChange({ chemicals_added: next });
  };
  const updChem = (idx: number, patch: Partial<ChemAdded>) => {
    const next = chemicalsAdded.map((c, i) => (i === idx ? { ...c, ...patch } : c));
    onChange({ chemicals_added: next });
  };
  const rmChem = (idx: number) => {
    onChange({ chemicals_added: chemicalsAdded.filter((_, i) => i !== idx) });
  };

  const toggleCheck = (idx: number) => {
    const next = checklistItems.map((c, i) =>
      i === idx ? { ...c, checked: !c.checked } : c
    );
    onChange({ checklist_items: next });
  };

  // Phase 31 · Step 2c — drag-reorder. The DraggableFlatList calls
  // `onDragEnd({ data })` with the full re-ordered array; we hand it
  // straight to `onChange` so the parent's autosave (1500ms debounce)
  // picks it up, PATCHes the service report with `X-Idempotency-Key`,
  // and — when offline — queues the same mutation via the existing
  // `writeQueue.ts`. No new queue plumbing needed.
  const reorderChecklist = useCallback(
    (data: ChecklistItem[]) => {
      // Skip no-op reorders so we don't spam the autosave.
      const same = data.length === checklistItems.length
        && data.every((d, i) => d.id === checklistItems[i]?.id);
      if (same) return;
      onChange({ checklist_items: data });
    },
    [checklistItems, onChange],
  );

  // Phase 31 · Step 2c — quick-add sheet visibility.
  const [pickerOpen, setPickerOpen] = useState(false);

  // Phase 34e — dose recommendations (mobile mirror of web).
  // Phase 56.10 — extended with `category` (`routine` / `ordering_note`
  // / `algae_remediation`) and `guidance_note` (multi-sentence tips
  // for algae rows: brush, filter run, backwash).
  type Rec = {
    chemical: string; quantity: number; unit: string;
    reason: string; urgency: string; reading_key: string;
    category?: "routine" | "ordering_note" | "algae_remediation";
    guidance_note?: string | null;
  };
  const [recs, setRecs] = useState<null | {
    recommendations: Rec[]; mocked: boolean; reason?: string | null;
    source?: string; pool_gallons?: number | null;
  }>(null);
  const [recsLoading, setRecsLoading] = useState(false);

  const readingsDict = useMemo(() => {
    const acc: Record<string, any> = {};
    for (const r of readings) {
      const key = (r.key || r.name) as string;
      if (!key) continue;
      if (r.value != null && r.value !== "") acc[key] = r.value;
    }
    return acc;
  }, [readings]);

  const fetchRecommendations = useCallback(async () => {
    if (locked) return;
    setRecsLoading(true);
    try {
      const res: any = await api.post("/service-report/recommend-chemicals", {
        job_id: jobId,
        readings: readingsDict,
        use_llm_phrasing: true,
        // Phase 56.10 — algae remediation branch trigger.
        visible_algae: props.observations?.visible_algae || "none",
      });
      setRecs(res);
    } catch (e) {
      // Silent — recommendations are advisory.
    } finally {
      setRecsLoading(false);
    }
  }, [jobId, readingsDict, locked, props.observations?.visible_algae]);

  useEffect(() => {
    if (locked) return;
    if (Object.keys(readingsDict).length === 0) { setRecs(null); return; }
    const h = setTimeout(fetchRecommendations, 800);
    return () => clearTimeout(h);
  }, [readingsDict, locked, fetchRecommendations]);

  const addChemFromRec = (r: Rec) => {
    if (locked) return;
    // Phase 37 — snap to the closest preset in the matching chemical
    // dropdown row (parity with web). Falls back to a raw row entry if
    // the chemical isn't part of the configured dropdown catalog.
    const snapped = snapRecommendationToPreset(r.chemical, r.quantity);
    if (snapped) {
      const { type, option, snappedFrom } = snapped;
      const existingIdx = chemicalsAdded.findIndex(
        (c: any) => String(c?.chemical || c?.name || "").toLowerCase() === type.name.toLowerCase()
      );
      const entry: any = {
        chemical: type.name,
        name: type.name,
        quantity: option.quantity,
        amount: String(option.quantity),
        unit: type.unit,
        raw_label: option.label,
        source: "recommendation",
        reading_key: r.reading_key,
        snapped_from: snappedFrom,
      };
      const next = [...chemicalsAdded];
      if (existingIdx >= 0) next[existingIdx] = { ...next[existingIdx], ...entry };
      else next.push(entry);
      onChange({ chemicals_added: next });
      return;
    }
    const next: ChemAdded[] = [
      ...chemicalsAdded,
      {
        id: Math.random().toString(36).slice(2),
        name: r.chemical,
        amount: String(r.quantity ?? ""),
        unit: r.unit || (chemicalUnits[0] || "oz"),
      },
    ];
    onChange({ chemicals_added: next });
  };

  const analyzeWater = async () => {
    if (locked) return;
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) { Alert.alert("Permission needed"); return; }
    const pick = await ImagePicker.launchImageLibraryAsync({ quality: 0.6, base64: true });
    if (pick.canceled || !pick.assets?.length) return;
    const a: any = pick.assets[0];
    const dataUrl = `data:${a.mimeType || "image/jpeg"};base64,${a.base64}`;
    setAnalyzing(true);
    setAnalysis(null);
    try {
      // Step 1 — upload as a job photo to obtain a public URL the AI can fetch.
      const uploaded = await api.post(`/jobs/${jobId}/photos`, {
        data: dataUrl, label: `water-analysis-${new Date().toISOString()}`,
      });
      const latest = (uploaded?.photos || []).slice(-1)[0];
      const photoUrl = latest?.url || latest?.data;
      if (!photoUrl) throw new Error("Uploaded photo did not return a URL.");
      // Step 2 — call the AI endpoint.
      const currentReadings = readings.reduce((acc: Record<string, any>, r) => {
        if (r.value != null && r.value !== "") acc[(r.key || r.name) as string] = r.value;
        return acc;
      }, {});
      const result = await api.post("/service-report/analyze-water-photo", {
        photo_url: photoUrl,
        current_readings: Object.keys(currentReadings).length ? currentReadings : null,
        job_id: jobId,
      }, 45000);
      setAnalysis(result);
    } catch (e: any) {
      Alert.alert("Analysis failed", e?.message || "Try again.");
    } finally { setAnalyzing(false); }
  };

  return (
    <View testID="pool-checklist-form">
      {/* Feb-2026 · Checklist reclassifier — inline picker mirrors the
          web empty-state block. Trigger conditions match web: the
          backend template must be "generic" AND readingFields must be
          empty. */}
      {(props.readingFields as any || []).length === 0 && props.template === "generic" ? (
        <View style={styles.reclassifyCard} testID="pool-service-type-picker-block">
          <Text style={styles.reclassifyTitle}>
            This job isn&apos;t classified as Pool or Landscape
          </Text>
          <Text style={styles.reclassifyBody}>
            Set its Service Type to enable chemical readings.
          </Text>
          {props.canEditServiceType && props.onReclassify ? (
            <View style={styles.reclassifyRow} testID="pool-service-type-picker">
              {[
                { value: "Pool Service",      label: "Pool Service" },
                { value: "Landscape Service", label: "Landscape Service" },
                { value: "Other",             label: "Other" },
              ].map((opt) => (
                <Pressable
                  key={opt.value}
                  disabled={reclassifyBusy || locked}
                  onPress={async () => {
                    if (reclassifyBusy || locked) return;
                    setReclassifyBusy(true);
                    try { await props.onReclassify!(opt.value); }
                    finally { setReclassifyBusy(false); }
                  }}
                  style={[
                    styles.reclassifyChip,
                    (locked || reclassifyBusy) && { opacity: 0.6 },
                  ]}
                  testID={`pool-service-type-set-${opt.value.toLowerCase().replace(/\s+/g, "-")}`}
                >
                  <Text style={styles.reclassifyChipText}>{opt.label}</Text>
                </Pressable>
              ))}
              {reclassifyBusy ? (
                <Text style={styles.reclassifyBusyText} testID="pool-service-type-picker-busy">
                  Applying…
                </Text>
              ) : null}
            </View>
          ) : (
            <Text style={styles.reclassifyReadonly} testID="pool-service-type-readonly-hint">
              Ask an admin to set Service Type.
            </Text>
          )}
        </View>
      ) : null}

      {/* Phase 34d-follow-b — "Analyze water photo" button removed per user
          request. Backend endpoint retained for other flows. */}

      {analysis && (
        <View style={styles.analysisCard} testID="pool-analysis-card">
          {analysis.mocked && (
            <Text style={styles.mockedBanner}>
              AI mocked · {analysis.reason || "no reason provided"}
            </Text>
          )}
          {analysis.overall_assessment && (
            <Text style={styles.analysisBody}>
              {analysis.overall_assessment}
            </Text>
          )}
          {(analysis.recommendations || []).length > 0 && (
            <>
              <Text style={styles.analysisHeader}>Recommendations</Text>
              {analysis.recommendations!.map((r, i) => (
                <Text key={i} style={styles.analysisItem}>• {r}</Text>
              ))}
            </>
          )}
          {(analysis.issues || []).length > 0 && (
            <>
              <Text style={styles.analysisHeader}>Issues</Text>
              {analysis.issues!.map((r, i) => (
                <Text key={i} style={styles.analysisItem}>• {r}</Text>
              ))}
            </>
          )}
          <Text style={styles.analysisFoot}>
            Readings are NOT auto-filled — enter values you observed on the meter.
          </Text>
        </View>
      )}

      {/* Phase 56.10-mobile — Visible algae toggle group.
          Mirrors the web `pool-visible-algae-card` behavior. Sits
          directly below chemical readings so the observation is
          captured in the same wizard "step" (readings). Persisted to
          `service_report.observations.visible_algae` via the existing
          `patchReport` autosave — no new endpoint. */}
      <View style={styles.algaeCard} testID="mobile-visible-algae-card">
        <Text style={styles.algaeTitle}>Visible algae on walls</Text>
        <View style={styles.algaeToggleRow}>
          {(["none", "light", "heavy"] as const).map((opt) => {
            const current = (props.observations?.visible_algae || "none").toLowerCase();
            const active = current === opt;
            const palette = {
              none:  { bg: "#FFFFFF", fg: colors.onSurface, border: colors.border },
              light: { bg: "#FEF3C7", fg: "#92400E",       border: "#FCD34D" },
              heavy: { bg: "#FEE2E2", fg: "#991B1B",       border: "#FCA5A5" },
            }[opt];
            return (
              <Pressable
                key={opt}
                disabled={locked}
                onPress={() => onChange({
                  observations: {
                    ...(props.observations || {}),
                    visible_algae: opt,
                  },
                })}
                style={[
                  styles.algaeToggleBtn,
                  {
                    backgroundColor: active ? palette.bg : "transparent",
                    borderColor: active ? palette.border : colors.border,
                    opacity: locked ? 0.6 : 1,
                  },
                ]}
                testID={`mobile-visible-algae-toggle-${opt}`}
              >
                <Text
                  style={[
                    styles.algaeToggleText,
                    { color: active ? palette.fg : colors.muted },
                  ]}
                >
                  {opt.charAt(0).toUpperCase() + opt.slice(1)}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <Text style={styles.algaeHint}>
          Triggers an algae remediation dosing plan below when set to
          Light or Heavy.
        </Text>
      </View>

      {/* Phase 34e — Recommended Chemicals card */}
      <View style={styles.recCard} testID="pool-recommendations-card">
        <View style={styles.recHeader}>
          <Text style={styles.recTitle}>Recommended Chemicals</Text>
          {!locked && (
            <Pressable
              onPress={fetchRecommendations}
              disabled={recsLoading || Object.keys(readingsDict).length === 0}
              style={styles.recRefreshBtn}
              testID="pool-recommendations-refresh"
            >
              {recsLoading
                ? <ActivityIndicator size="small" color={colors.brand} />
                : <Ionicons name="refresh" size={13} color={colors.brand} />}
              <Text style={styles.recRefreshText}>Refresh</Text>
            </Pressable>
          )}
        </View>

        {recs?.mocked ? (
          <View style={styles.recBanner} testID="pool-gallons-missing-banner">
            <Ionicons name="warning-outline" size={14} color="#92400E" />
            <Text style={styles.recBannerText} testID="pool-recommendations-mocked-reason">
              {recs.reason} — set pool volume on the customer profile.
            </Text>
          </View>
        ) : Object.keys(readingsDict).length === 0 ? (
          <Text style={styles.recHint}>
            Enter chemical readings above to see dosing recommendations.
          </Text>
        ) : recs && recs.recommendations && recs.recommendations.length === 0 ? (
          <View style={styles.recAllGood} testID="pool-recommendations-empty">
            <Ionicons name="checkmark-circle" size={14} color="#059669" />
            <Text style={styles.recAllGoodText}>
              All readings look good — no chemicals needed.
            </Text>
          </View>
        ) : recs && recs.recommendations ? (
          <View>
            {/* Phase 56.10-mobile · ordering-note callout — high-pH
                guard rendered as a yellow banner at the TOP of the
                step-2 recommendations list, BEFORE routine + algae
                rows. Mirrors the web ordering-note behavior. */}
            {recs.recommendations
              .filter((r) => r.category === "ordering_note")
              .map((r, i) => (
                <View
                  key={`ord-${i}`}
                  style={styles.orderingNoteCard}
                  testID="mobile-algae-ordering-note"
                >
                  <Ionicons name="warning" size={14} color="#B45309" />
                  <Text style={styles.orderingNoteText}>{r.reason}</Text>
                </View>
              ))}

            {/* Routine rows (unchanged pre-56.10 behavior). Any row
                without a category is treated as routine to preserve
                back-compat with older payload shapes. */}
            {recs.recommendations
              .filter((r) => !r.category || r.category === "routine")
              .map((r, i) => (
              <View
                key={`${r.chemical}-${i}`}
                style={styles.recRow}
                testID="pool-recommendation-row"
              >
                <Ionicons
                  name={r.urgency === "immediate" ? "warning" : "flask-outline"}
                  size={14}
                  color={r.urgency === "immediate" ? "#92400E" : colors.brand}
                  style={{ marginTop: 2 }}
                />
                <View style={{ flex: 1 }}>
                  <Text style={styles.recRowTitle}>
                    {r.quantity > 0 ? `${r.quantity} ${r.unit} ` : ""}{r.chemical}
                  </Text>
                  <Text style={styles.recRowReason}>{r.reason}</Text>
                </View>
                {!locked && r.quantity > 0 && (
                  <Pressable
                    onPress={() => addChemFromRec(r)}
                    style={styles.recAddBtn}
                    testID="pool-recommendation-add-btn"
                  >
                    <Text style={styles.recAddBtnText}>Add</Text>
                  </Pressable>
                )}
              </View>
            ))}

            {/* Phase 56.10-mobile · Algae Protocol sub-section —
                renders when the payload contains any
                `category: "algae_remediation"` entry. Red-tinted card
                with a warning icon; each row exposes multi-sentence
                guidance (brush, filter run, backwash) as bullet
                points. Matches web `pool-algae-protocol-card`. */}
            {recs.recommendations.some((r) => r.category === "algae_remediation") && (
              <View style={styles.algaeProtocolCard} testID="mobile-algae-protocol-card">
                <View style={styles.algaeProtocolHeader}>
                  <Ionicons name="warning" size={14} color="#991B1B" />
                  <Text style={styles.algaeProtocolTitle}>Algae Protocol</Text>
                </View>
                {recs.recommendations
                  .filter((r) => r.category === "algae_remediation")
                  .map((r, i) => (
                    <View
                      key={`algae-${r.chemical}-${i}`}
                      style={styles.algaeProtocolRow}
                      testID="mobile-algae-remediation-row"
                    >
                      <Ionicons
                        name="warning"
                        size={14}
                        color="#B91C1C"
                        style={{ marginTop: 2 }}
                      />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.algaeProtocolChem}>
                          {r.quantity > 0 ? `${r.quantity} ${r.unit} ` : ""}
                          {r.chemical}
                        </Text>
                        <Text style={styles.algaeProtocolReason}>{r.reason}</Text>
                        {r.guidance_note
                          ? r.guidance_note
                              .split(/(?<=\.)\s+/)
                              .filter(Boolean)
                              .map((line, j) => (
                                <View
                                  key={j}
                                  style={styles.algaeGuidanceRow}
                                  testID="mobile-algae-guidance-bullet"
                                >
                                  <Text style={styles.algaeGuidanceBullet}>•</Text>
                                  <Text style={styles.algaeGuidanceText}>{line}</Text>
                                </View>
                              ))
                          : null}
                      </View>
                      {!locked && r.quantity > 0 && (
                        <Pressable
                          onPress={() => addChemFromRec(r)}
                          style={styles.algaeAddBtn}
                          testID="mobile-algae-remediation-add-btn"
                        >
                          <Text style={styles.algaeAddBtnText}>Add</Text>
                        </Pressable>
                      )}
                    </View>
                  ))}
              </View>
            )}
          </View>
        ) : recsLoading ? (
          <Text style={styles.recHint}>Calculating…</Text>
        ) : null}
      </View>

      {/* Chemicals Added — Phase 37 stacked dropdown rows */}
      <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>
        Chemicals Added
      </Text>
      <ChemicalDropdownStack
        chemicalsAdded={chemicalsAdded as any}
        locked={locked}
        onChange={onChange as any}
        jobId={jobId}
      />

      {/* Phase 31 · Step 2c — quick-add sheet trigger. Complements the
          preset-based dropdown above with a stepper-driven flow for the
          "I just poured X of Y" case where the tech knows the exact
          quantity and doesn't want to hunt for a preset. */}
      <Pressable
        onPress={() => !locked && setPickerOpen(true)}
        style={styles.quickAddBtn}
        disabled={locked}
        testID="chem-picker-open"
        accessibilityRole="button"
        accessibilityLabel="Open quick-add chemical picker"
      >
        <Ionicons name="add-circle-outline" size={18} color={colors.brand} />
        <Text style={styles.quickAddText}>Quick add chemical</Text>
      </Pressable>
      <ChemicalPickerSheet
        visible={pickerOpen}
        onClose={() => setPickerOpen(false)}
        chemicalsAdded={chemicalsAdded}
        onChange={onChange as any}
        locked={locked}
      />

      {/* Checklist */}
      <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>Checklist</Text>
      {DRAG_REORDER_ENABLED ? (
        <DraggableFlatList
          data={checklistItems}
          keyExtractor={(c) => c.id}
          onDragEnd={({ data }) => reorderChecklist(data as ChecklistItem[])}
          scrollEnabled={false}
          activationDistance={12}
          containerStyle={{ marginBottom: 0 }}
          testID="pool-checklist-draggable"
          renderItem={({ item: c, drag, isActive, getIndex }: RenderItemParams<ChecklistItem>) => {
            const i = getIndex() ?? 0;
            return (
              <ScaleDecorator>
                <View
                  style={[
                    styles.checkRow,
                    c.checked && styles.checkRowOn,
                    isActive && styles.checkRowDragging,
                  ]}
                  testID={`pool-check-${c.id}`}
                >
                  <Pressable
                    onLongPress={locked ? undefined : drag}
                    disabled={locked}
                    hitSlop={8}
                    style={styles.dragHandle}
                    testID={`pool-check-${c.id}-drag`}
                    accessibilityLabel={`Reorder ${c.label}`}
                  >
                    <Ionicons name="reorder-three-outline" size={20} color={colors.muted} />
                  </Pressable>
                  <Pressable
                    style={styles.checkTapZone}
                    onPress={() => !locked && toggleCheck(i)}
                    disabled={locked}
                  >
                    <Ionicons
                      name={c.checked ? "checkbox" : "square-outline"}
                      size={22}
                      color={c.checked ? colors.success : colors.muted}
                    />
                    <Text style={styles.checkText}>{c.label}</Text>
                  </Pressable>
                </View>
              </ScaleDecorator>
            );
          }}
        />
      ) : (
        // Web fallback — plain rows, no drag handle. Preserves the
        // Phase 40 tap-to-toggle UX without the setPointerCapture
        // crash from `react-native-draggable-flatlist` on RN-Web.
        checklistItems.map((c, i) => (
          <Pressable
            key={c.id}
            style={[styles.checkRow, c.checked && styles.checkRowOn]}
            onPress={() => !locked && toggleCheck(i)}
            disabled={locked}
            testID={`pool-check-${c.id}`}
          >
            <Ionicons
              name={c.checked ? "checkbox" : "square-outline"}
              size={22}
              color={c.checked ? colors.success : colors.muted}
            />
            <Text style={styles.checkText}>{c.label}</Text>
          </Pressable>
        ))
      )}

      {/* Notes */}
      <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>Notes</Text>
      <TextInput
        multiline
        numberOfLines={4}
        editable={!locked}
        style={styles.textarea}
        value={notes || ""}
        placeholder="Anything the customer or dispatcher should know…"
        placeholderTextColor={colors.muted}
        onChangeText={(v) => onChange({ notes: v })}
        testID="pool-notes"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  // Feb-2026 · Checklist reclassifier — inline picker card shown in
  // the Chemical Readings section when the report's backend template
  // is "generic" and there are no reading fields to render.
  reclassifyCard: {
    marginBottom: spacing.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: "#FCD34D",
    borderRadius: radius.md,
    backgroundColor: "#FEF3C7",
  },
  reclassifyTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: "#92400E",
    marginBottom: 4,
  },
  reclassifyBody: {
    fontFamily: font.regular,
    fontSize: 11,
    color: "#92400E",
    marginBottom: spacing.sm,
  },
  reclassifyRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 6,
  },
  reclassifyChip: {
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: 999,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    backgroundColor: "#fff",
  },
  reclassifyChipText: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.onSurface,
  },
  reclassifyBusyText: {
    fontFamily: font.regular,
    fontSize: 11,
    color: "#92400E",
    marginLeft: 4,
  },
  reclassifyReadonly: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    fontStyle: "italic",
  },
  // Phase 56.10-mobile — Visible algae toggle card + Algae Protocol
  // sub-section rendered in Recommended Chemicals. Colors mirror the
  // web PoolChecklistForm palette (yellow-tinted for light / red for
  // heavy) so parity is preserved at a glance.
  algaeCard: {
    marginTop: spacing.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
  },
  algaeTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  algaeToggleRow: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  algaeToggleBtn: {
    borderWidth: 1.5,
    borderRadius: 999,
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
  },
  algaeToggleText: {
    fontFamily: font.bold,
    fontSize: 11,
  },
  algaeHint: {
    marginTop: spacing.sm,
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
  },
  orderingNoteCard: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 6,
    padding: spacing.sm,
    borderWidth: 1.5,
    borderColor: "#F59E0B",
    borderRadius: radius.sm,
    backgroundColor: "#FEF3C7",
    marginBottom: spacing.sm,
  },
  orderingNoteText: {
    flex: 1,
    fontFamily: font.bold,
    fontSize: 11,
    color: "#92400E",
    lineHeight: 15,
  },
  algaeProtocolCard: {
    marginTop: spacing.sm,
    padding: spacing.sm,
    borderWidth: 1.5,
    borderColor: "#FCA5A5",
    borderRadius: radius.sm,
    backgroundColor: "#FEF2F2",
  },
  algaeProtocolHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: spacing.sm,
  },
  algaeProtocolTitle: {
    fontFamily: font.bold,
    fontSize: 13,
    color: "#991B1B",
  },
  algaeProtocolRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: "#FFFFFF",
    borderWidth: 1,
    borderColor: "#FECACA",
    borderRadius: radius.sm,
    padding: spacing.sm,
    marginBottom: spacing.xs,
  },
  algaeProtocolChem: {
    fontFamily: font.bold,
    fontSize: 13,
    color: "#0F172A",
  },
  algaeProtocolReason: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 2,
  },
  algaeGuidanceRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 4,
    marginTop: 2,
  },
  algaeGuidanceBullet: {
    fontFamily: font.bold,
    fontSize: 11,
    color: "#7F1D1D",
    lineHeight: 15,
  },
  algaeGuidanceText: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: 11,
    color: "#7F1D1D",
    lineHeight: 15,
  },
  algaeAddBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
    backgroundColor: "#B91C1C",
    borderRadius: radius.sm,
  },
  algaeAddBtnText: {
    fontFamily: font.bold,
    fontSize: 11,
    color: "#FFFFFF",
  },
  recCard: {
    marginTop: spacing.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
  },
  recHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  recTitle: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  recRefreshBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.sm, paddingVertical: 4,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    backgroundColor: colors.surface,
  },
  recRefreshText: { fontFamily: font.semibold, fontSize: 11, color: colors.brand },
  recHint: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  recBanner: {
    flexDirection: "row", alignItems: "flex-start", gap: 6,
    backgroundColor: "#FEF3C7", borderColor: "#F59E0B", borderWidth: 1,
    padding: spacing.sm, borderRadius: radius.sm,
  },
  recBannerText: { flex: 1, fontFamily: font.medium, fontSize: 11, color: "#92400E" },
  recAllGood: { flexDirection: "row", alignItems: "center", gap: 6 },
  recAllGoodText: { fontFamily: font.semibold, fontSize: 12, color: "#059669" },
  recRow: {
    flexDirection: "row", alignItems: "flex-start", gap: spacing.sm,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.sm, padding: spacing.sm, marginBottom: spacing.xs,
  },
  recRowTitle: { fontFamily: font.bold, fontSize: 13, color: colors.onSurface },
  recRowReason: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  recAddBtn: {
    paddingHorizontal: spacing.md, paddingVertical: 4,
    backgroundColor: colors.brand, borderRadius: radius.sm,
  },
  recAddBtnText: { fontFamily: font.bold, fontSize: 11, color: "#fff" },
  sectionTitle: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  readingCell: { width: "48%" },
  readingLabel: {
    fontFamily: font.bold, fontSize: fontSize.xs, color: colors.muted,
    textTransform: "uppercase", marginBottom: 4,
  },
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
  analyzeBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 8, marginTop: spacing.md, paddingVertical: 12,
    borderRadius: radius.md, backgroundColor: colors.brand,
  },
  analyzeBtnText: { fontFamily: font.bold, color: "#fff", fontSize: fontSize.base },
  analysisCard: {
    marginTop: spacing.md, padding: spacing.md, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  mockedBanner: {
    fontFamily: font.bold, fontSize: fontSize.xs, color: "#92400E",
    backgroundColor: "#FEF3C7", paddingHorizontal: 8, paddingVertical: 4,
    borderRadius: 6, marginBottom: spacing.sm, alignSelf: "flex-start",
  },
  analysisHeader: {
    fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface,
    marginTop: spacing.sm, marginBottom: 4,
  },
  analysisBody: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface,
  },
  analysisItem: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface,
    marginBottom: 2,
  },
  analysisFoot: {
    fontFamily: font.semibold, fontSize: fontSize.xs, color: colors.muted,
    marginTop: spacing.sm, fontStyle: "italic",
  },
  chemRow: {
    flexDirection: "row", gap: spacing.xs, alignItems: "center",
    marginBottom: spacing.sm,
  },
  addChemBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 10, borderRadius: radius.md,
    borderWidth: 2, borderStyle: "dashed", borderColor: colors.brand,
  },
  addChemText: {
    fontFamily: font.bold, color: colors.brand, fontSize: fontSize.sm,
  },
  hint: {
    fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted,
    marginTop: 4,
  },
  checkRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, marginBottom: spacing.xs,
    backgroundColor: colors.surface,
  },
  checkRowOn: { borderColor: colors.success, backgroundColor: "#F0FDF4" },
  checkRowDragging: {
    borderColor: colors.brand,
    // Subtle lift + shadow while a row is being dragged so the tech can
    // see which item is under their finger. Shadow tokens borrow from
    // the sheet elevation used elsewhere in the app.
    ...(Platform.OS === "web"
      ? { boxShadow: "0 8px 24px rgba(0,0,0,0.18)" as any }
      : { elevation: 8 }),
  },
  checkText: {
    flex: 1, fontFamily: font.semibold, fontSize: fontSize.base,
    color: colors.onSurface,
  },
  checkTapZone: {
    flex: 1, flexDirection: "row", alignItems: "center", gap: spacing.sm,
  },
  dragHandle: {
    width: 28, height: 28, alignItems: "center", justifyContent: "center",
  },
  quickAddBtn: {
    marginTop: spacing.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.sm,
    borderWidth: 1, borderColor: colors.brand, borderRadius: radius.md,
    borderStyle: "dashed",
    paddingVertical: spacing.sm, paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
  },
  quickAddText: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand,
  },
});
