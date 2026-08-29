/**
 * Ship 2 · Customer Delete UX overhaul — 3-button modal for mobile.
 *
 * Port of /frontend/src/components/customers/CustomerDeleteModal.jsx
 *
 * Three actions:
 *   [Cancel]  [Soft Delete]  [Hard Delete + ShieldAlert]
 *
 * Props:
 *   visible     – boolean
 *   customerName – display name for the modal copy
 *   busyMode    – null | "soft" | "hard"
 *   onCancel    – () => void
 *   onSoftDelete – () => Promise<void>
 *   onHardDelete – () => Promise<void>
 */
import React from "react";
import { View, Text, Modal, StyleSheet, TouchableOpacity, ScrollView } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type Props = {
  visible: boolean;
  customerName?: string;
  busyMode?: "soft" | "hard" | null;
  onCancel: () => void;
  onSoftDelete: () => void;
  onHardDelete: () => void;
};

export default function CustomerDeleteModal({
  visible,
  customerName,
  busyMode = null,
  onCancel,
  onSoftDelete,
  onHardDelete,
}: Props) {
  const name = customerName || "this customer";
  const disabled = Boolean(busyMode);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onCancel}
      testID="customer-delete-modal"
    >
      <View style={s.overlay}>
        <View style={s.card}>
          {/* Header */}
          <View style={s.header}>
            <View style={s.headerLeft}>
              <Ionicons name="alert-circle" size={20} color="#B91C1C" />
              <Text style={s.title} testID="customer-delete-title">
                Delete {name}?
              </Text>
            </View>
            <TouchableOpacity
              onPress={onCancel}
              disabled={disabled}
              hitSlop={12}
              testID="customer-delete-close-x"
            >
              <Ionicons name="close" size={18} color={colors.onSurface} />
            </TouchableOpacity>
          </View>

          {/* Body */}
          <ScrollView style={s.body} bounces={false}>
            <Text style={s.bodyText} testID="customer-delete-body">
              Pick how you'd like to remove this customer:
            </Text>

            <View style={s.bulletRow}>
              <Text style={s.bullet}>{"\u2022"}</Text>
              <Text style={s.bulletText}>
                <Text style={s.bold}>Soft Delete</Text> — archives {name} and
                hides them from active lists. Jobs, invoices, reports, and
                history are preserved. An admin can Restore them from the
                Customers page.
              </Text>
            </View>

            <View style={s.bulletRow}>
              <Text style={s.bullet}>{"\u2022"}</Text>
              <Text style={s.bulletText}>
                <Text style={[s.bold, { color: "#B91C1C" }]}>Hard Delete</Text> —
                permanently removes the customer row. Jobs, invoices, and
                service reports are{" "}
                <Text style={s.bold}>not</Text> cascaded — they stay in place
                with the customer's snapshotted name (or "Unknown Customer" if
                the snapshot is missing). Blocked if the customer has any
                unpaid invoice.
              </Text>
            </View>
          </ScrollView>

          {/* Footer buttons */}
          <View style={s.footer}>
            <TouchableOpacity
              style={[s.btn, s.cancelBtn]}
              onPress={onCancel}
              disabled={disabled}
              testID="customer-delete-cancel-btn"
            >
              <Text style={[s.btnText, s.cancelBtnText]}>Cancel</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[s.btn, s.softBtn, disabled && s.btnDisabled]}
              onPress={onSoftDelete}
              disabled={disabled}
              testID="customer-delete-soft-btn"
            >
              <Text style={[s.btnText, s.softBtnText]}>
                {busyMode === "soft" ? "Soft-deleting\u2026" : "Soft Delete"}
              </Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[s.btn, s.hardBtn, disabled && s.btnDisabled]}
              onPress={onHardDelete}
              disabled={disabled}
              testID="customer-delete-hard-btn"
            >
              <Ionicons name="shield" size={14} color="#fff" style={{ marginRight: 4 }} />
              <Text style={[s.btnText, s.hardBtnText]}>
                {busyMode === "hard" ? "Hard-deleting\u2026" : "Hard Delete"}
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: "rgba(15, 23, 42, 0.55)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.lg,
  },
  card: {
    width: "100%",
    maxWidth: 440,
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    overflow: "hidden",
    elevation: 8,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.25,
    shadowRadius: 12,
  },
  header: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flex: 1,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: "#991B1B",
    flex: 1,
  },
  body: {
    padding: 20,
    maxHeight: 280,
  },
  bodyText: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    lineHeight: 22,
    marginBottom: 12,
  },
  bulletRow: {
    flexDirection: "row",
    marginBottom: 10,
    paddingLeft: 4,
  },
  bullet: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
    marginRight: 8,
    lineHeight: 22,
  },
  bulletText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    lineHeight: 22,
    flex: 1,
  },
  bold: {
    fontFamily: font.bold,
  },
  footer: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "flex-end",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  btn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: radius.md,
    minHeight: 38,
  },
  btnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
  },
  btnDisabled: {
    opacity: 0.5,
  },
  cancelBtn: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cancelBtnText: {
    color: colors.onSurface,
  },
  softBtn: {
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FCA5A5",
  },
  softBtnText: {
    color: "#991B1B",
  },
  hardBtn: {
    backgroundColor: "#B91C1C",
  },
  hardBtnText: {
    color: "#FFFFFF",
    fontFamily: font.bold,
  },
});
