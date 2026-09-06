/**
 * Ship 2 · Inline Restore pill for soft-deleted customers.
 *
 * Port of /frontend/src/components/customers/RestoreCustomerButton.jsx
 *
 * Renders a small cyan "Restore" pill. Tapping opens a confirmation
 * modal (bottom sheet style) which calls PATCH /customers/{cid}/restore.
 */
import React, { useState } from "react";
import {
  View, Text, TouchableOpacity, Modal, StyleSheet, ActivityIndicator, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type Props = {
  customer: { id: string; name?: string; anonymized_at?: string | null };
  onRestored: (res: any) => void;
  onError: (msg: string) => void;
  disabled?: boolean;
};

export default function RestoreCustomerButton({ customer, onRestored, onError, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const wasAnonymized = Boolean(customer?.anonymized_at);

  const confirm = async () => {
    setBusy(true);
    try {
      const res = await api.patch(`/customers/${customer.id}/restore`, {});
      setOpen(false);
      onRestored?.(res);
    } catch (err: any) {
      onError?.(err?.message || "Failed to restore customer");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <TouchableOpacity
        style={[s.pill, (disabled || busy) && s.pillDisabled]}
        onPress={() => { if (!disabled && !busy) setOpen(true); }}
        disabled={disabled || busy}
        testID={`restore-customer-btn-${customer.id}`}
        hitSlop={8}
      >
        {busy ? (
          <ActivityIndicator size={12} color="#0EA5E9" />
        ) : (
          <Ionicons name="refresh" size={12} color="#0EA5E9" />
        )}
        <Text style={s.pillText}>{busy ? "Restoring\u2026" : "Restore"}</Text>
      </TouchableOpacity>

      <Modal
        visible={open}
        transparent
        animationType="fade"
        onRequestClose={() => { if (!busy) setOpen(false); }}
        testID={`restore-customer-modal-${customer.id}`}
      >
        <View style={s.overlay}>
          <View style={s.card}>
            <Text style={s.title}>Restore this customer?</Text>
            <Text style={s.body}>
              They&apos;ll appear in the active customer list again.
            </Text>

            {wasAnonymized ? (
              <View style={s.warning} testID={`restore-anonymized-warning-${customer.id}`}>
                <Text style={s.warningText}>
                  <Text style={{ fontFamily: font.bold }}>Warning:</Text>{" "}
                  This customer&apos;s personal information was previously scrubbed
                  and cannot be recovered. Only the deletion state will be
                  restored — name, email, phone, and address will remain blank.
                </Text>
              </View>
            ) : null}

            <View style={s.actions}>
              <TouchableOpacity
                style={s.cancelBtn}
                onPress={() => { if (!busy) setOpen(false); }}
                disabled={busy}
                testID={`restore-customer-cancel-${customer.id}`}
              >
                <Text style={s.cancelText}>Cancel</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={[s.confirmBtn, busy && { opacity: 0.6 }]}
                onPress={confirm}
                disabled={busy}
                testID={`restore-customer-confirm-${customer.id}`}
              >
                <Text style={s.confirmText}>
                  {busy ? "Restoring\u2026" : "Yes, restore"}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
}

const s = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: "#0EA5E9",
    backgroundColor: "transparent",
  },
  pillDisabled: { opacity: 0.5 },
  pillText: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: "#0EA5E9",
  },
  overlay: {
    flex: 1,
    backgroundColor: "rgba(15, 23, 42, 0.55)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.lg,
  },
  card: {
    width: "100%",
    maxWidth: 400,
    backgroundColor: "#fff",
    borderRadius: radius.lg,
    padding: 24,
    elevation: 8,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.25,
    shadowRadius: 12,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: "#0F172A",
    marginBottom: 8,
  },
  body: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#334155",
    lineHeight: 20,
    marginBottom: 12,
  },
  warning: {
    borderWidth: 1,
    borderColor: "#F59E0B",
    backgroundColor: "rgba(245, 158, 11, 0.08)",
    borderRadius: radius.md,
    padding: 12,
    marginBottom: 16,
  },
  warningText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#78350F",
    lineHeight: 20,
  },
  actions: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: 8,
    marginTop: 8,
  },
  cancelBtn: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: "#E5E7EB",
    backgroundColor: "#fff",
  },
  cancelText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#334155",
  },
  confirmBtn: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: radius.md,
    backgroundColor: "#0EA5E9",
  },
  confirmText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
});
