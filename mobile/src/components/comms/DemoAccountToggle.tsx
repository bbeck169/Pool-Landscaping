/**
 * Task 1 · Feb-2026 — Mobile mirror of the web ``DemoAccountToggle``.
 *
 * Compact toggle wired to ``PATCH /api/comms/demo-flag``. Guards
 * the flip with a native Modal-based hard-confirm so an accidental
 * tap can't unmute production comms for a real customer / user.
 */
import React, { useState } from "react";
import { View, Text, Pressable, StyleSheet, Modal, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type Props = {
  recordType: "user" | "customer";
  recordId: string;
  isDemo: boolean;
  recordLabel?: string;
  onChange?: (next: boolean) => void;
  compact?: boolean;
};

export default function DemoAccountToggle({
  recordType, recordId, isDemo, recordLabel, onChange, compact,
}: Props) {
  const [pending, setPending] = useState(false);
  const [modal, setModal] = useState<{ open: boolean; nextValue: boolean | null }>({
    open: false, nextValue: null,
  });
  const active = !!isDemo;
  const nextVal = !active;

  const openConfirm = () => setModal({ open: true, nextValue: nextVal });
  const closeConfirm = () => { if (!pending) setModal({ open: false, nextValue: null }); };

  const confirm = async () => {
    setPending(true);
    try {
      await api.patch("/comms/demo-flag", {
        record_type: recordType,
        record_id: recordId,
        is_demo_account: modal.nextValue,
      });
      onChange?.(modal.nextValue as boolean);
      setModal({ open: false, nextValue: null });
    } catch (e: any) {
      Alert.alert("Toggle failed", String(e?.message || "Try again"));
    } finally { setPending(false); }
  };

  return (
    <View testID={`demo-flag-wrap-${recordType}-${recordId}`}>
      <Pressable
        onPress={openConfirm}
        style={[ss.toggle, active ? ss.toggleActive : ss.toggleInactive]}
        testID={`demo-flag-toggle-${recordType}-${recordId}`}
        accessibilityRole="switch"
        accessibilityState={{ checked: active }}
      >
        <Ionicons
          name={active ? "shield-checkmark" : "shield-outline"}
          size={12}
          color={active ? "#166534" : colors.onSurfaceSecondary}
        />
        {compact ? null : (
          <Text style={[ss.toggleText, active ? ss.toggleTextActive : null]}>
            {active ? "Demo: ON" : "Demo: OFF"}
          </Text>
        )}
      </Pressable>

      <Modal visible={modal.open} transparent animationType="fade"
               onRequestClose={closeConfirm}>
        <View style={ss.scrim}>
          <View style={ss.card}
                   testID={`demo-flag-confirm-modal-${recordType}-${recordId}`}>
            <Text style={ss.cardTitle}>
              {modal.nextValue ? "Enable" : "Disable"} demo whitelist
              {recordLabel ? ` for ${recordLabel}` : ""}?
            </Text>
            <Text style={ss.cardBody}>
              {modal.nextValue
                ? `Setting is_demo_account = true means this ${recordType} will bypass the outbound-comms safety gate. Real emails / SMS may be sent. Audit-logged.`
                : `Setting is_demo_account = false immediately suppresses all future outbound emails and SMS to this ${recordType}. Audit-logged.`}
            </Text>
            <View style={ss.cardActions}>
              <Pressable onPress={closeConfirm} style={ss.btnSecondary}
                            testID={`demo-flag-confirm-cancel-${recordType}-${recordId}`}>
                <Text style={ss.btnSecondaryText}>Cancel</Text>
              </Pressable>
              <Pressable
                onPress={confirm}
                disabled={pending}
                style={[
                  modal.nextValue ? ss.btnGo : ss.btnDanger,
                  pending ? { opacity: 0.6 } : null,
                ]}
                testID={`demo-flag-confirm-btn-${recordType}-${recordId}`}
              >
                <Text style={ss.btnGoText}>
                  {pending ? "Saving…" :
                     (modal.nextValue ? "Enable demo comms" : "Disable demo comms")}
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const ss = StyleSheet.create({
  toggle: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 999, borderWidth: 1,
  },
  toggleActive: {
    backgroundColor: "#DCFCE7", borderColor: "#86EFAC",
  },
  toggleInactive: {
    backgroundColor: colors.surfaceSecondary, borderColor: colors.border,
  },
  toggleText: { fontFamily: font.semibold, fontSize: 11, color: colors.onSurfaceSecondary },
  toggleTextActive: { color: "#166534" },
  scrim: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.55)",
    justifyContent: "center", alignItems: "center", paddingHorizontal: spacing.lg,
  },
  card: {
    width: "100%", maxWidth: 400,
    backgroundColor: colors.surface,
    borderRadius: radius.lg, padding: spacing.lg,
  },
  cardTitle: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  cardBody: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginBottom: spacing.md },
  cardActions: { flexDirection: "row", justifyContent: "flex-end", gap: 8 },
  btnSecondary: {
    paddingHorizontal: spacing.md, paddingVertical: 10,
    borderRadius: radius.md, backgroundColor: colors.surfaceSecondary,
  },
  btnSecondaryText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  btnGo: {
    paddingHorizontal: spacing.md, paddingVertical: 10,
    borderRadius: radius.md, backgroundColor: colors.brand,
  },
  btnDanger: {
    paddingHorizontal: spacing.md, paddingVertical: 10,
    borderRadius: radius.md, backgroundColor: colors.error,
  },
  btnGoText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});
