/**
 * Phase 31 · Phase 56.16 rewrite — LandscapingChecklistForm (mobile).
 *
 * Phase 56.16 changes:
 * - Per-item optional note removed (was cluttering the mobile UX).
 * - Notes split into TWO fields:
 *     • Job Notes (Internal — admin/tech only)  → `internal_notes`
 *     • Customer Notes (visible to customer)    → `customer_notes`
 * - Fallback labels aligned to the canonical 10-item ordered list.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";

type ChecklistItem = { id: string; label: string; checked: boolean; notes?: string };

export type LandscapingChecklistFormProps = {
  locked: boolean;
  checklistItems: ChecklistItem[];
  notes: string;               // legacy — kept for backwards compat
  internalNotes?: string;
  customerNotes?: string;
  onChange: (patch: Partial<{
    checklist_items: ChecklistItem[];
    notes: string;
    internal_notes: string;
    customer_notes: string;
  }>) => void;
};

const FALLBACK_LABELS = [
  "Sprayed or Pulled Weeds",
  "Checked Irrigation",
  "Trimmed Bushes",
  "Mowed Grass",
  "Edged Grass",
  "Blow Property",
  "Raked Rocks",
  "Locked Gate",
  "Trimmed Trees",
  "Irrigation Repair",
];

export default function LandscapingChecklistForm(
  props: LandscapingChecklistFormProps
) {
  const { locked, checklistItems, notes, internalNotes, customerNotes, onChange } = props;

  const items: ChecklistItem[] = checklistItems.length
    ? checklistItems
    : FALLBACK_LABELS.map((label, i) => ({
        id: `fallback-${i}`, label, checked: false,
      }));

  const toggleCheck = (idx: number) => {
    const next = items.map((c, i) => (i === idx ? { ...c, checked: !c.checked } : c));
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
        </View>
      ))}

      <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>
        Job Notes <Text style={styles.subtle}>(Internal — not visible to customer)</Text>
      </Text>
      <AppTextInput
        multiline
        numberOfLines={3}
        editable={!locked}
        style={styles.textarea}
        value={internalNotes || notes || ""}
        placeholder="Private notes for admins + dispatchers…"
        placeholderTextColor={colors.muted}
        onChangeText={(v) => onChange({ internal_notes: v })}
        testID="landscaping-internal-notes"
      />

      <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>
        Customer Notes <Text style={styles.subtle}>(visible to customer)</Text>
      </Text>
      <AppTextInput
        multiline
        numberOfLines={3}
        editable={!locked}
        style={styles.textarea}
        value={customerNotes || ""}
        placeholder="Anything the customer should see on their service report…"
        placeholderTextColor={colors.muted}
        onChangeText={(v) => onChange({ customer_notes: v })}
        testID="landscaping-customer-notes"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  sectionTitle: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  subtle: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
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
  textarea: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, minHeight: 90, textAlignVertical: "top",
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
    backgroundColor: colors.surface,
  },
});
