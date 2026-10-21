/**
 * TD-82 · Bulk "Change status" picker for jobs (web JobsList
 * `STATUS_OPTIONS` dropdown → bottom sheet; mobile `BulkActionBar` has
 * no dropdown support). Selecting fires immediately — web has no confirm
 * for status changes (operator T3).
 */
import React from "react";
import { Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Sheet, StatusChip } from "@/src/components/ui";
import { colors, spacing, font, fontSize } from "@/src/theme";

/** 1:1 with web `pages/jobs/JobsList.jsx` STATUS_OPTIONS. */
export const JOB_BULK_STATUS_OPTIONS = [
  { value: "active", label: "Active" },
  { value: "pending", label: "Pending" },
  { value: "scheduled", label: "Scheduled" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
  { value: "canceled", label: "Canceled" },
];

type Props = { visible: boolean; count: number; onSelect: (status: string) => void; onClose: () => void };

export default function JobStatusPickerSheet({ visible, count, onSelect, onClose }: Props) {
  return (
    <Sheet visible={visible} onClose={onClose} title={`Change status · ${count} job${count === 1 ? "" : "s"}`} testID="bulk-status-sheet">
      {JOB_BULK_STATUS_OPTIONS.map((o) => (
        <Pressable
          key={o.value} onPress={() => onSelect(o.value)} testID={`bulk-status-option-${o.value}`}
          style={({ pressed }) => [s.row, pressed && { opacity: 0.7 }]}
        >
          <Text style={s.label}>{o.label}</Text>
          <StatusChip status={o.value} />
          <Ionicons name="chevron-forward" size={16} color={colors.muted} />
        </Pressable>
      ))}
    </Sheet>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 52, paddingHorizontal: spacing.lg, borderTopWidth: 1, borderTopColor: colors.divider },
  label: { flex: 1, fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
});
