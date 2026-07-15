/**
 * Phase 31 · Step 2a — LandscapingChecklistForm (mobile).
 *
 * Renders the grooming checklist for landscaping jobs. Items are
 * backend-driven via `report.checklist_items` (backed by
 * LANDSCAPE_CHECKLIST_DEFAULT in service_reports.py) with a hardcoded
 * fallback for the (unlikely) empty-template case.
 */
import React from "react";
import { View, Text, Pressable, TextInput, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type ChecklistItem = { id: string; label: string; checked: boolean; notes?: string };

export type LandscapingChecklistFormProps = {
  locked: boolean;
  checklistItems: ChecklistItem[];
  notes: string;
  onChange: (patch: Partial<{ checklist_items: ChecklistItem[]; notes: string }>) => void;
};

// Fallback used only if the bootstrap GET somehow returns zero items.
const FALLBACK_LABELS = [
  "Mow all turf areas",
  "Edge sidewalks and driveways",
  "Blow all hard surfaces",
  "Trim shrubs/hedges as needed",
  "Pull/spray visible weeds",
  "Fertilize where scheduled",
  "Empty and haul debris",
  "Notes for customer",
];

export default function LandscapingChecklistForm(
  props: LandscapingChecklistFormProps
) {
  const { locked, checklistItems, notes, onChange } = props;

  const items: ChecklistItem[] = checklistItems.length
    ? checklistItems
    : FALLBACK_LABELS.map((label, i) => ({
        id: `fallback-${i}`, label, checked: false,
      }));

  const toggleCheck = (idx: number) => {
    const next = items.map((c, i) => (i === idx ? { ...c, checked: !c.checked } : c));
    onChange({ checklist_items: next });
  };

  const updNote = (idx: number, v: string) => {
    const next = items.map((c, i) => (i === idx ? { ...c, notes: v } : c));
    onChange({ checklist_items: next });
  };

  return (
    <View testID="landscaping-checklist-form">
      <Text style={styles.sectionTitle}>Grooming Checklist</Text>
      {items.map((c, i) => (
        <View key={c.id} style={styles.itemBlock}>
          <Pressable
            style={[styles.checkRow, c.checked && styles.checkRowOn]}
            onPress={() => !locked && toggleCheck(i)}
            testID={`landscaping-check-${c.id}`}
          >
            <Ionicons
              name={c.checked ? "checkbox" : "square-outline"}
              size={22}
              color={c.checked ? colors.success : colors.muted}
            />
            <Text style={styles.checkText}>{c.label}</Text>
          </Pressable>
          <TextInput
            editable={!locked}
            value={c.notes || ""}
            placeholder="Notes (optional)"
            placeholderTextColor={colors.muted}
            onChangeText={(v) => updNote(i, v)}
            style={styles.noteInput}
            testID={`landscaping-note-${c.id}`}
          />
        </View>
      ))}
      <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>Job Notes</Text>
      <TextInput
        multiline
        numberOfLines={4}
        editable={!locked}
        style={styles.textarea}
        value={notes || ""}
        placeholder="Anything the customer or dispatcher should know…"
        placeholderTextColor={colors.muted}
        onChangeText={(v) => onChange({ notes: v })}
        testID="landscaping-notes"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  sectionTitle: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  itemBlock: { marginBottom: spacing.md },
  checkRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border,
  },
  checkRowOn: { borderColor: colors.success, backgroundColor: "#F0FDF4" },
  checkText: {
    flex: 1, fontFamily: font.semibold, fontSize: fontSize.base,
    color: colors.onSurface,
  },
  noteInput: {
    marginTop: 6,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.sm, paddingVertical: 8,
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  textarea: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, minHeight: 100, textAlignVertical: "top",
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
    backgroundColor: colors.surface,
  },
});
