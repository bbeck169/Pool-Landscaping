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
  View, Text, TextInput, Pressable, StyleSheet, Alert, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import ReadingChipRow from "./ReadingChipRow";
import ChemicalDropdownStack, { snapRecommendationToPreset } from "./ChemicalDropdownStack";

// Phase 37 — canonical testid key (parity with web PoolChecklistForm.jsx).
const _NAME_TO_CANONICAL: Record<string, string> = {
  "free chlorine": "free_chlorine",
  "total chlorine": "total_chlorine",
  "combined chlorine": "combined_chlorine",
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
};
function canonicalReadingKey(r: { key?: string; name?: string }): string {
  const name = String(r?.name || "").toLowerCase().trim();
  if (_NAME_TO_CANONICAL[name]) return _NAME_TO_CANONICAL[name];
  const rawKey = String(r?.key || r?.name || "").toLowerCase().trim();
  if (_NAME_TO_CANONICAL[rawKey]) return _NAME_TO_CANONICAL[rawKey];
  return rawKey.replace(/[\s()]+/g, "_").replace(/[^a-z0-9_]/g, "");
}

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
  onChange: (patch: Partial<{
    chemical_readings: Reading[];
    chemicals_added: ChemAdded[];
    checklist_items: ChecklistItem[];
    notes: string;
  }>) => void;
};

export default function PoolChecklistForm(props: PoolChecklistFormProps) {
  const {
    jobId, customerId, locked, readings, chemicalsAdded, chemicalsCatalog, chemicalUnits,
    checklistItems, notes, onChange,
  } = props;

  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<null | {
    mocked?: boolean;
    reason?: string;
    clarity?: string | null;
    issues?: string[];
    recommendations?: string[];
    overall_assessment?: string | null;
  }>(null);

  const updReading = (idx: number, val: number | null) => {
    const next = readings.map((r, i) =>
      i === idx ? { ...r, value: val } : r
    );
    onChange({ chemical_readings: next });
  };

  // Phase 36b — previously-tested values per customer (parity with web).
  const [lastReadings, setLastReadings] = useState<Record<string, { value: number | null; at?: string | null }>>({});
  useEffect(() => {
    if (!customerId) return;
    let alive = true;
    api.get(`/service-reports/last-readings?customer_id=${customerId}`)
      .then((r: any) => { if (alive) setLastReadings(r?.readings || {}); })
      .catch(() => {});
    return () => { alive = false; };
  }, [customerId]);

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

  // Phase 34e — dose recommendations (mobile mirror of web).
  type Rec = {
    chemical: string; quantity: number; unit: string;
    reason: string; urgency: string; reading_key: string;
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
      });
      setRecs(res);
    } catch (e) {
      // Silent — recommendations are advisory.
    } finally {
      setRecsLoading(false);
    }
  }, [jobId, readingsDict, locked]);

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
      {/* Chemical Readings — Phase 36b chip UI (parity with web) */}
      <Text style={styles.sectionTitle}>Chemical Readings</Text>
      <View>
        {readings.map((r, i) => {
          // Phase 37 — canonical snake_case key for testid parity with web.
          const key = canonicalReadingKey(r);
          const prev = lastReadings[key]
            || lastReadings[(r.key as string) || ""]
            || lastReadings[r.name];
          return (
            <ReadingChipRow
              key={key}
              readingKey={key}
              label={r.name}
              unit={r.unit}
              value={r.value}
              step={r.step}
              min={r.min}
              max={r.max}
              locked={locked}
              previous={prev || null}
              onChange={(v) => updReading(i, v)}
            />
          );
        })}
      </View>

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
            {recs.recommendations.map((r, i) => (
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
      />

      {/* Checklist */}
      <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>Checklist</Text>
      {checklistItems.map((c, i) => (
        <Pressable
          key={c.id}
          style={[styles.checkRow, c.checked && styles.checkRowOn]}
          onPress={() => !locked && toggleCheck(i)}
          testID={`pool-check-${c.id}`}
        >
          <Ionicons
            name={c.checked ? "checkbox" : "square-outline"}
            size={22}
            color={c.checked ? colors.success : colors.muted}
          />
          <Text style={styles.checkText}>{c.label}</Text>
        </Pressable>
      ))}

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
  },
  checkRowOn: { borderColor: colors.success, backgroundColor: "#F0FDF4" },
  checkText: {
    flex: 1, fontFamily: font.semibold, fontSize: fontSize.base,
    color: colors.onSurface,
  },
});
