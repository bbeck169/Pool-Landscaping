/**
 * OptimizeRoutePreview — Feb-2026 · dumb controlled modal.
 *
 * Renders the "Reorders N stops. Estimated: X mi saved, Y min saved."
 * summary + Apply/Cancel actions. Role-aware Apply copy is decided by
 * the parent (this component only surfaces the labels + emits events).
 *
 *   • ``visible``          — show/hide toggle
 *   • ``stopsAffected``    — N in the copy
 *   • ``milesSaved``       — X (rounded 1 dp for display)
 *   • ``minutesSaved``     — Y (rounded to whole minute for display)
 *   • ``role``             — "admin" | "technician" | ...   ⇒ Apply copy
 *   • ``fallbackOrigin``   — true when GPS denied; renders the note
 *   • ``busy``             — disables buttons while the API call flies
 *   • ``onApply``          — parent submits /request or /apply
 *   • ``onCancel``         — closes without an API call
 */
import React from "react";
import { View, Text, StyleSheet, Pressable, Modal, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export interface OptimizeRoutePreviewProps {
  visible: boolean;
  stopsAffected: number;
  milesSaved: number;
  minutesSaved: number;
  role?: string;
  fallbackOrigin?: boolean;
  busy?: boolean;
  onApply: () => void;
  onCancel: () => void;
  testID?: string;
}

export default function OptimizeRoutePreview({
  visible, stopsAffected, milesSaved, minutesSaved,
  role, fallbackOrigin = false, busy = false,
  onApply, onCancel, testID,
}: OptimizeRoutePreviewProps) {
  const isAdmin = (role || "").toLowerCase() === "admin" || (role || "").toLowerCase() === "super_admin";
  const applyLabel = busy ? "Working…" : isAdmin ? "Apply" : "Request approval";

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onCancel}
    >
      <View style={s.backdrop}>
        <View style={s.card} testID={testID || "optimize-route-preview-modal"}>
          <View style={s.header}>
            <Ionicons name="navigate-circle-outline" size={22} color={colors.brand} />
            <Text style={s.title}>Optimize route</Text>
          </View>
          <Text style={s.body} testID="optimize-route-preview-summary">
            Reorders {stopsAffected} stops. Estimated:{" "}
            <Text style={s.strong}>{milesSaved.toFixed(1)} miles saved</Text>,{" "}
            <Text style={s.strong}>{Math.round(minutesSaved)} min saved</Text>.
          </Text>
          {fallbackOrigin ? (
            <View style={s.note} testID="optimize-route-preview-fallback-note">
              <Ionicons name="information-circle-outline" size={14} color="#78350F" />
              <Text style={s.noteText}>
                Location permission not granted — using first pending stop
                as starting point.
              </Text>
            </View>
          ) : null}
          <View style={s.actions}>
            <Pressable
              onPress={onCancel}
              disabled={busy}
              style={[s.btn, s.cancelBtn, busy && { opacity: 0.5 }]}
              testID="optimize-route-preview-cancel"
            >
              <Text style={s.cancelLabel}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={onApply}
              disabled={busy}
              style={[s.btn, s.applyBtn, busy && { opacity: 0.7 }]}
              testID="optimize-route-preview-apply"
            >
              {busy ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <Ionicons name="checkmark" size={14} color="#fff" />
              )}
              <Text style={s.applyLabel}>{applyLabel}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.5)",
    alignItems: "center", justifyContent: "center", paddingHorizontal: 24,
  },
  card: {
    width: "100%", maxWidth: 400,
    backgroundColor: colors.surface, borderRadius: 16,
    padding: 20, gap: spacing.md,
  },
  header: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  body: { fontFamily: font.regular, fontSize: fontSize.base,
           color: colors.onSurface, lineHeight: 22 },
  strong: { fontFamily: font.bold, color: colors.onSurface },
  note: {
    flexDirection: "row", alignItems: "flex-start", gap: 6,
    padding: spacing.sm, borderRadius: radius.md,
    backgroundColor: "#FEF3C7", borderWidth: 1, borderColor: "#FCD34D",
  },
  noteText: { flex: 1, fontFamily: font.medium,
               fontSize: fontSize.xs, color: "#78350F", lineHeight: 16 },
  actions: { flexDirection: "row", gap: spacing.sm, justifyContent: "flex-end" },
  btn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingHorizontal: spacing.md, height: 40, borderRadius: radius.md,
  },
  cancelBtn: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
  },
  cancelLabel: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  applyBtn: { backgroundColor: colors.brand, minWidth: 140 },
  applyLabel: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});
