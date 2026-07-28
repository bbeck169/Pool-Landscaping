/**
 * Shared BulkSelectToolkit for mobile admin surfaces.
 *
 * Provides: useBulkSelect hook, BulkActionBar (bottom sheet), BulkConfirmModal
 *
 * Usage:
 *   const { selected, count, allSelected, indeterminate, toggleAll, toggleOne, clear } = useBulkSelect(visibleIds);
 *   <BulkActionBar count={count} onClear={clear} actions={[...]} />
 *   <BulkConfirmModal open={x} title="Delete 3 items?" description="..." onConfirm={fn} onClose={fn} />
 */
import React, { useMemo, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, Pressable, Modal, TouchableOpacity,
  Animated,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

// ── Hook ────────────────────────────────────────────────

export function useBulkSelect(visibleIds: string[]) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggleOne = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setSelected((prev) => {
      if (prev.size === visibleIds.length) return new Set();
      return new Set(visibleIds);
    });
  }, [visibleIds]);

  const clear = useCallback(() => setSelected(new Set()), []);

  const count = selected.size;
  const allSelected = visibleIds.length > 0 && count === visibleIds.length;
  const indeterminate = count > 0 && !allSelected;

  return { selected, count, allSelected, indeterminate, toggleAll, toggleOne, clear };
}

// ── Checkbox ────────────────────────────────────────────

type CheckboxProps = { checked: boolean; indeterminate?: boolean; onPress: () => void; testID?: string };
export function BulkCheckbox({ checked, indeterminate, onPress, testID }: CheckboxProps) {
  return (
    <Pressable onPress={onPress} hitSlop={8} testID={testID} style={s.checkbox}>
      <View style={[s.checkBox, checked && s.checkBoxActive, indeterminate && s.checkBoxActive]}>
        {checked ? (
          <Ionicons name="checkmark" size={14} color="#fff" />
        ) : indeterminate ? (
          <View style={s.indeterminateDash} />
        ) : null}
      </View>
    </Pressable>
  );
}

// ── Action Bar ──────────────────────────────────────────

export type BulkAction = {
  key: string;
  label: string;
  icon?: string;
  tone?: "danger" | "primary" | "default";
  onPress: () => void;
};

type ActionBarProps = {
  count: number;
  onClear: () => void;
  actions: BulkAction[];
};

export function BulkActionBar({ count, onClear, actions }: ActionBarProps) {
  const insets = useSafeAreaInsets();
  if (count === 0) return null;

  return (
    <View style={[s.bar, { paddingBottom: insets.bottom + 8 }]} testID="bulk-action-bar">
      <View style={s.barInner}>
        <View style={s.barLeft}>
          <Text style={s.barCount} testID="bulk-action-bar-count">{count} selected</Text>
          <Pressable onPress={onClear} hitSlop={8} testID="bulk-clear-selection">
            <Text style={s.barClear}>Clear</Text>
          </Pressable>
        </View>
        <View style={s.barActions}>
          {actions.map((a) => {
            const isDanger = a.tone === "danger";
            return (
              <TouchableOpacity
                key={a.key}
                style={[s.barBtn, isDanger && s.barBtnDanger]}
                onPress={a.onPress}
                testID={a.key}
              >
                {a.icon ? <Ionicons name={a.icon as any} size={16} color={isDanger ? "#fff" : colors.brand} /> : null}
                <Text style={[s.barBtnText, isDanger && { color: "#fff" }]}>{a.label}</Text>
              </TouchableOpacity>
            );
          })}
        </View>
      </View>
    </View>
  );
}

// ── Confirm Modal ───────────────────────────────────────

type ConfirmProps = {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onClose: () => void;
  loading?: boolean;
};

export function BulkConfirmModal({
  open, title, description, confirmLabel, onConfirm, onClose, loading,
}: ConfirmProps) {
  return (
    <Modal visible={open} transparent animationType="fade" onRequestClose={onClose}>
      <View style={s.modalOverlay}>
        <View style={s.modalCard} testID="bulk-delete-confirm-modal">
          <Text style={s.modalTitle}>{title}</Text>
          <Text style={s.modalDesc}>{description}</Text>
          <View style={s.modalBtns}>
            <Pressable style={s.modalCancel} onPress={onClose} testID="bulk-delete-cancel">
              <Text style={s.modalCancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[s.modalConfirm, loading && { opacity: 0.6 }]}
              onPress={onConfirm}
              disabled={loading}
              testID="bulk-delete-confirm-btn"
            >
              <Text style={s.modalConfirmText}>{confirmLabel || "Confirm"}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

// ── Styles ──────────────────────────────────────────────

const s = StyleSheet.create({
  checkbox: { padding: 4 },
  checkBox: {
    width: 22, height: 22, borderRadius: 4, borderWidth: 2,
    borderColor: colors.border, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface,
  },
  checkBoxActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  indeterminateDash: { width: 10, height: 2, backgroundColor: "#fff", borderRadius: 1 },

  bar: {
    position: "absolute", bottom: 0, left: 0, right: 0,
    backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border,
    shadowColor: "#000", shadowOpacity: 0.1, shadowOffset: { width: 0, height: -4 },
    shadowRadius: 12, elevation: 10, zIndex: 50,
  },
  barInner: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  barLeft: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  barCount: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  barClear: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  barActions: { flexDirection: "row", gap: spacing.sm },
  barBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
  },
  barBtnDanger: { backgroundColor: colors.error },
  barBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },

  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", alignItems: "center", justifyContent: "center", paddingHorizontal: spacing.xl },
  modalCard: { width: "100%", maxWidth: 380, backgroundColor: colors.surface, borderRadius: 16, padding: spacing.xl },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginBottom: spacing.sm },
  modalDesc: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, lineHeight: 22, marginBottom: spacing.xl },
  modalBtns: { flexDirection: "row", gap: spacing.md, justifyContent: "flex-end" },
  modalCancel: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  modalCancelText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  modalConfirm: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md, backgroundColor: colors.error },
  modalConfirmText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
});
