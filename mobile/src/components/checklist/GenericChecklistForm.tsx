/**
 * Phase 31 · Step 2a — GenericChecklistForm (mobile).
 *
 * Fallback form for any job that isn't pool or landscaping. Two
 * textareas + optional checklist items surfaced from the backend
 * template (GENERIC_CHECKLIST_DEFAULT in service_reports.py) so the
 * tech still has a structured checkbox surface when the template ships
 * default items.
 *
 * "Work performed" is persisted in `report.field_report.work_performed`
 * via the notes-adjacent shape — but since the service-report PATCH
 * only accepts `notes` / `chemical_readings` / `chemicals_added` /
 * `checklist_items`, we concatenate work-performed into `notes` on
 * change. This keeps to the "no invented endpoints" rule.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";

type ChecklistItem = { id: string; label: string; checked: boolean; notes?: string };

export type GenericChecklistFormProps = {
  locked: boolean;
  checklistItems: ChecklistItem[];
  workPerformed: string;
  notes: string;
  onChange: (patch: Partial<{
    checklist_items: ChecklistItem[];
    work_performed: string;
    notes: string;
  }>) => void;
};

export default function GenericChecklistForm(props: GenericChecklistFormProps) {
  const { locked, checklistItems, workPerformed, notes, onChange } = props;

  const toggleCheck = (idx: number) => {
    const next = checklistItems.map((c, i) =>
      i === idx ? { ...c, checked: !c.checked } : c
    );
    onChange({ checklist_items: next });
  };

  return (
    <View testID="generic-checklist-form">
      <Text style={styles.sectionTitle}>Work Performed</Text>
      <AppTextInput
        multiline
        numberOfLines={5}
        editable={!locked}
        style={styles.textarea}
        value={workPerformed || ""}
        placeholder="Describe what was done for the customer…"
        placeholderTextColor={colors.muted}
        onChangeText={(v) => onChange({ work_performed: v })}
        testID="generic-work-performed"
      />

      {checklistItems.length > 0 && (
        <>
          <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>
            Checklist
          </Text>
          {checklistItems.map((c, i) => (
            <Pressable
              key={c.id}
              style={[styles.checkRow, c.checked && styles.checkRowOn]}
              onPress={() => !locked && toggleCheck(i)}
              testID={`generic-check-${c.id}`}
            >
              <Ionicons
                name={c.checked ? "checkbox" : "square-outline"}
                size={22}
                color={c.checked ? colors.success : colors.muted}
              />
              <Text style={styles.checkText}>{c.label}</Text>
            </Pressable>
          ))}
        </>
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
        onChangeText={(v) => onChange({ notes: v })}
        testID="generic-notes"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  sectionTitle: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    marginBottom: spacing.sm,
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
  checkText: {
    flex: 1, fontFamily: font.semibold, fontSize: fontSize.base,
    color: colors.onSurface,
  },
});
