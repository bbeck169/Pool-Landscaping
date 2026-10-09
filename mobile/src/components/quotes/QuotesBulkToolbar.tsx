/**
 * Phase 4b · Feb-2026 — Quotes bulk-action bar (mobile).
 * Mirror of web `frontend/src/components/quotes/QuotesBulkToolbar.jsx`
 * (f61449679). Mobile deviation: rendered as a sticky FOOTER (thumb
 * reach) instead of the web's sticky bar above the table.
 *
 * Visible only when 1+ quotes are selected. Delete is confirmed first.
 * Role gating + API calls live in the parent screen.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { showConfirm } from "@/src/components/ConfirmModal";

/** Same copy as web `_toastBulkOutcome`. */
export function bulkOutcomeMessage(verb: string, succeeded?: string[], skipped?: any[]) {
  const s = succeeded?.length || 0;
  const k = skipped?.length || 0;
  if (s === 0 && k === 0) return { message: `No ${verb} action taken.`, tone: "info" as const };
  const message = k === 0 ? `${s} ${verb}` : `${s} ${verb}, ${k} skipped (ineligible)`;
  return { message, tone: s > 0 ? ("success" as const) : ("info" as const) };
}

const plural = (n: number) => `${n} quote${n === 1 ? "" : "s"}`;

function Btn({ label, icon, bg, onPress, disabled, testID }: any) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [s.btn, { backgroundColor: bg }, (pressed || disabled) && { opacity: disabled ? 0.5 : 0.8 }]}
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={label}
    >
      <Ionicons name={icon} size={14} color="#FFFFFF" />
      <Text style={s.btnText}>{label}</Text>
    </Pressable>
  );
}

export default function QuotesBulkToolbar({ selectedCount, busy = false, onAccept, onDecline, onDelete, onClear }: {
  selectedCount: number;
  busy?: boolean;
  onAccept: () => void;
  onDecline: () => void;
  onDelete: () => void;
  onClear: () => void;
}) {
  if (!selectedCount || selectedCount <= 0) return null;
  const confirmDelete = () =>
    showConfirm({
      title: `Delete ${plural(selectedCount)}?`,
      message: "This cannot be undone. Quotes already converted to an invoice will be skipped.",
      confirmLabel: "Delete",
      confirmStyle: "destructive",
      onConfirm: onDelete,
    });
  return (
    <View style={s.bar} testID="quotes-bulk-toolbar" accessibilityRole="toolbar" accessibilityLabel="Quotes bulk actions">
      <View style={s.topRow}>
        <Text style={s.count} testID="quotes-bulk-count">{plural(selectedCount)} selected</Text>
        {busy ? <ActivityIndicator size="small" color="#FFFFFF" /> : null}
        <Pressable onPress={onClear} hitSlop={10} style={s.clear} testID="quotes-bulk-clear" accessibilityLabel="Clear selection">
          <Ionicons name="close" size={18} color="#CBD5E1" />
        </Pressable>
      </View>
      <View style={s.actions}>
        <Btn label="Accept" icon="checkmark" bg="#059669" onPress={onAccept} disabled={busy} testID="quotes-bulk-accept" />
        <Btn label="Decline" icon="close" bg="#DC2626" onPress={onDecline} disabled={busy} testID="quotes-bulk-decline" />
        <Btn label="Delete" icon="trash-outline" bg="#7F1D1D" onPress={confirmDelete} disabled={busy} testID="quotes-bulk-delete" />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  bar: {
    position: "absolute", left: 12, right: 12, bottom: 16,
    backgroundColor: "#1E293B", borderRadius: 12, padding: 12, gap: 10,
    shadowColor: "#000", shadowOpacity: 0.25, shadowRadius: 10, shadowOffset: { width: 0, height: 4 }, elevation: 8,
  },
  topRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  count: { flex: 1, color: "#FFFFFF", fontSize: 14, fontWeight: "700" },
  clear: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  actions: { flexDirection: "row", gap: 8 },
  btn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4,
    minHeight: 44, borderRadius: 8,
  },
  btnText: { color: "#FFFFFF", fontSize: 13, fontWeight: "700" },
});
