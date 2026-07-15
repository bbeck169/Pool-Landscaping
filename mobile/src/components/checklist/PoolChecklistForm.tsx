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
import React, { useState } from "react";
import {
  View, Text, TextInput, Pressable, StyleSheet, Alert, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type Reading = {
  key?: string; name: string; unit?: string; value: number | string | null;
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
    jobId, locked, readings, chemicalsAdded, chemicalsCatalog, chemicalUnits,
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

  const updReading = (idx: number, val: string) => {
    const next = readings.map((r, i) =>
      i === idx
        ? { ...r, value: val === "" ? null : parseFloat(val) }
        : r
    );
    onChange({ chemical_readings: next });
  };

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
      {/* Chemical Readings */}
      <Text style={styles.sectionTitle}>Chemical Readings</Text>
      <View style={styles.grid}>
        {readings.map((r, i) => (
          <View key={r.key || r.name} style={styles.readingCell}>
            <Text style={styles.readingLabel}>
              {r.name}{r.unit ? ` (${r.unit})` : ""}
            </Text>
            <TextInput
              keyboardType="decimal-pad"
              editable={!locked}
              value={r.value == null ? "" : String(r.value)}
              onChangeText={(v) => updReading(i, v)}
              style={styles.input}
              placeholder="—"
              placeholderTextColor={colors.muted}
              testID={`pool-reading-${r.key || r.name}`}
            />
          </View>
        ))}
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

      {/* Chemicals Added */}
      <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>
        Chemicals Added
      </Text>
      {chemicalsAdded.map((c, i) => (
        <View key={c.id || i} style={styles.chemRow} testID={`pool-chem-row-${i}`}>
          <TextInput
            editable={!locked}
            value={c.name}
            placeholder="Chemical"
            placeholderTextColor={colors.muted}
            onChangeText={(v) => updChem(i, { name: v })}
            style={[styles.input, { flex: 3 }]}
            testID={`pool-chem-name-${i}`}
          />
          <TextInput
            editable={!locked}
            keyboardType="decimal-pad"
            value={String(c.amount || "")}
            placeholder="Qty"
            placeholderTextColor={colors.muted}
            onChangeText={(v) => updChem(i, { amount: v })}
            style={[styles.input, { flex: 2 }]}
            testID={`pool-chem-amount-${i}`}
          />
          <TextInput
            editable={!locked}
            value={c.unit || ""}
            placeholder="unit"
            placeholderTextColor={colors.muted}
            onChangeText={(v) => updChem(i, { unit: v })}
            style={[styles.input, { flex: 2 }]}
            testID={`pool-chem-unit-${i}`}
          />
          {!locked && (
            <Pressable onPress={() => rmChem(i)} testID={`pool-chem-rm-${i}`}>
              <Ionicons name="trash-outline" size={20} color={colors.error} />
            </Pressable>
          )}
        </View>
      ))}
      {!locked && (
        <Pressable style={styles.addChemBtn} onPress={addChem} testID="pool-chem-add">
          <Ionicons name="add" size={16} color={colors.brand} />
          <Text style={styles.addChemText}>Add chemical</Text>
        </Pressable>
      )}
      {chemicalsCatalog.length > 0 && (
        <Text style={styles.hint}>
          Catalog: {chemicalsCatalog.slice(0, 6).map((c) => c.name).join(", ")}
          {chemicalsCatalog.length > 6 ? "…" : ""}
        </Text>
      )}

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
