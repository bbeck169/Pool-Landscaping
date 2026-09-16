/**
 * Phase MI1.1-mobile — Multi-industry checklist renderer (React Native).
 *
 * Mirror of `frontend/src/components/checklist/IndustryChecklistForm.jsx`.
 *
 * Props: `{ industry, locked, checklistItems, notes, onChange }`.
 * `onChange` is patch-based: `onChange({ checklist_items?, notes? })`.
 *
 * Fetches template from `GET /api/checklists/industry/{industry}` on mount,
 * merges with the report's persisted `checklistItems`, and renders a checkbox
 * row per item with required-asterisk support + a Notes textarea.
 */
import React, { useEffect, useMemo, useState } from "react";
import { View, Text, Pressable, StyleSheet, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";
import type { IndustrySlug } from "@/src/lib/deriveIndustry";

export const INDUSTRY_LABELS: Record<string, string> = {
  pool: "Pool",
  landscaping: "Landscaping",
  hvac: "HVAC",
  pest_control: "Pest Control",
  cleaning: "Cleaning",
  solar: "Solar",
  handyman: "Handyman",
};

type ChecklistRow = {
  id: string;
  key: string;
  label: string;
  required: boolean;
  checked: boolean;
  notes: string;
};

/**
 * Merge template items (admin-controlled order + labels) with the report's
 * persisted checklist_items so completed state is preserved across re-renders.
 */
function mergeTemplateAndReport(
  templateItems: any[],
  reportItems: any[],
): ChecklistRow[] {
  const byKey = new Map<string, any>();
  (reportItems || []).forEach((r) => {
    const k = String(r.key || r.label || "").toLowerCase();
    if (k) byKey.set(k, r);
  });
  return (templateItems || []).map((t, idx) => {
    const k = String(t.key || t.label || "").toLowerCase();
    const prev = byKey.get(k) || byKey.get(String(t.label || "").toLowerCase());
    return {
      id: prev?.id || t.key || `item-${idx}`,
      key: t.key,
      label: t.label,
      required: !!t.required,
      checked: !!prev?.checked,
      notes: prev?.notes || "",
    };
  });
}

type Props = {
  industry: IndustrySlug;
  locked: boolean;
  checklistItems: any[];
  notes: string;
  onChange: (patch: Record<string, any>) => void;
};

export default function IndustryChecklistForm({
  industry,
  locked,
  checklistItems,
  notes,
  onChange,
}: Props) {
  const [template, setTemplate] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setError("");
    setTemplate(null);
    api.get(`/checklists/industry/${industry}`)
      .then((body) => { if (!cancelled) setTemplate(body); })
      .catch((e) => { if (!cancelled) setError(e?.message || "Failed to load"); });
    return () => { cancelled = true; };
  }, [industry]);

  const items: any[] = useMemo(() => template?.items || [], [template]);
  const merged = useMemo(
    () => mergeTemplateAndReport(items, checklistItems),
    [items, checklistItems],
  );

  const toggle = (idx: number) => {
    if (locked) return;
    const next = merged.map((row, i) =>
      i === idx ? { ...row, checked: !row.checked } : row,
    );
    onChange({ checklist_items: next });
  };

  const setItemNote = (idx: number, note: string) => {
    if (locked) return;
    const next = merged.map((row, i) =>
      i === idx ? { ...row, notes: note } : row,
    );
    onChange({ checklist_items: next });
  };

  // ── Loading state ────────────────────────────────────────────────────
  if (error) {
    return (
      <View style={styles.emptyBox} testID="industry-checklist-error">
        <Text style={[styles.emptyText, { color: colors.error }]}>{error}</Text>
      </View>
    );
  }
  if (!template) {
    return (
      <View style={styles.loadingBox} testID="industry-checklist-loading">
        <ActivityIndicator size="small" color={colors.brand} />
        <Text style={styles.emptyText}>Loading checklist…</Text>
      </View>
    );
  }
  if (!items.length) {
    return (
      <View style={styles.emptyBox} testID="industry-checklist-empty">
        <Text style={styles.emptyText}>No checklist items configured for this industry yet.</Text>
      </View>
    );
  }

  // ── Render ───────────────────────────────────────────────────────────
  return (
    <View testID={`industry-checklist-${industry}`}>
      <Text style={styles.sectionTitle}>
        {INDUSTRY_LABELS[industry] || "Checklist"}
      </Text>

      {merged.map((row, idx) => (
        <Pressable
          key={row.id}
          style={[styles.checkRow, row.checked && styles.checkRowOn]}
          onPress={() => toggle(idx)}
          disabled={locked}
          testID={`industry-check-${row.key}`}
        >
          <Ionicons
            name={row.checked ? "checkbox" : "square-outline"}
            size={22}
            color={row.checked ? "#059669" : colors.muted}
          />
          <Text style={styles.checkLabel}>
            {row.label}
            {row.required ? (
              <Text style={styles.requiredAsterisk}> *</Text>
            ) : null}
          </Text>
        </Pressable>
      ))}

      {/* Per-item notes for checked rows */}
      {merged.map((row, idx) =>
        row.checked && !locked ? (
          <AppTextInput
            key={`note-${row.id}`}
            value={row.notes || ""}
            placeholder="Optional note"
            onChangeText={(v: string) => setItemNote(idx, v)}
            style={styles.itemNoteInput}
            testID={`industry-check-note-${row.key}`}
          />
        ) : null,
      )}

      <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>Notes</Text>
      <AppTextInput
        multiline
        numberOfLines={4}
        editable={!locked}
        style={styles.textarea}
        value={notes || ""}
        placeholder="Anything the customer or dispatcher should know…"
        placeholderTextColor={colors.muted}
        onChangeText={(v: string) => onChange({ notes: v })}
        testID={`industry-checklist-notes-${industry}`}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  sectionTitle: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  loadingBox: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
  },
  emptyBox: {
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
  },
  emptyText: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
  },
  checkRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, marginBottom: spacing.xs,
  },
  checkRowOn: { borderColor: "#059669", backgroundColor: "#D1FAE5" },
  checkLabel: {
    flex: 1, fontFamily: font.semibold, fontSize: fontSize.base,
    color: colors.onSurface,
  },
  requiredAsterisk: { color: "#DC2626" },
  itemNoteInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.sm, marginBottom: spacing.xs,
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface,
  },
  textarea: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, minHeight: 100, textAlignVertical: "top",
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
    backgroundColor: colors.surface,
  },
});
