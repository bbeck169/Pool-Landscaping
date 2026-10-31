/**
 * TD-g2 · reason prompt for unlocking a submitted service report.
 *
 * Centered RN <Modal> + KeyboardAvoidingView (SwipeSheet has no keyboard
 * avoidance and ConfirmModal has no text input). Confirm stays disabled
 * until the trimmed reason is ≥ MIN_UNLOCK_REASON_LEN, so no API call
 * can fire with a short reason. Backdrop / Cancel / Android back dismiss
 * (disabled while the unlock is in flight).
 */
import React, { useEffect, useState } from "react";
import {
  Modal, View, Text, TextInput, Pressable, ActivityIndicator,
  KeyboardAvoidingView, Platform, StyleSheet,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { MIN_UNLOCK_REASON_LEN, isValidUnlockReason } from "@/src/lib/submittedReportUnlock";

type Props = {
  visible: boolean;
  busy?: boolean;
  onCancel: () => void;
  onSubmit: (reason: string) => void;
};

export default function UnlockReasonModal({ visible, busy = false, onCancel, onSubmit }: Props) {
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);
  useEffect(() => { if (visible) { setReason(""); setAttempted(false); } }, [visible]);

  const valid = isValidUnlockReason(reason);
  const len = reason.trim().length;
  const showError = !valid && (attempted || len > 0);
  const cancel = () => { if (!busy) onCancel(); };
  const submit = () => {
    setAttempted(true);
    if (!valid || busy) return;
    onSubmit(reason.trim());
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={cancel}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={s.root}>
        <Pressable style={s.backdrop} onPress={cancel} testID="unlock-reason-backdrop" accessibilityLabel="Cancel unlock" />
        <View style={s.card} testID="unlock-reason-modal">
          <Ionicons name="lock-open-outline" size={32} color={colors.brand} />
          <Text style={s.title} accessibilityRole="header">Unlock submitted report</Text>
          <Text style={s.body}>
            This report was already submitted. Enter a reason to unlock it. The reason is saved to the job&apos;s
            audit history. Close the job again afterwards to resubmit.
          </Text>
          <TextInput
            style={[s.input, showError && s.inputError]}
            value={reason}
            onChangeText={setReason}
            placeholder="Reason (at least 8 characters)"
            placeholderTextColor={colors.muted}
            multiline
            editable={!busy}
            autoFocus
            testID="unlock-reason-input"
            accessibilityLabel="Unlock reason"
          />
          <Text style={[s.hint, showError && s.hintError]} testID={showError ? "unlock-reason-error" : "unlock-reason-hint"}>
            {showError ? `Reason must be at least ${MIN_UNLOCK_REASON_LEN} characters (${len}/${MIN_UNLOCK_REASON_LEN}).` : `${len}/${MIN_UNLOCK_REASON_LEN} characters minimum`}
          </Text>
          <View style={s.actions}>
            <Pressable style={s.cancel} onPress={cancel} disabled={busy} testID="unlock-reason-cancel" accessibilityRole="button">
              <Text style={s.cancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[s.confirm, (!valid || busy) && s.disabled]}
              onPress={submit}
              disabled={busy}
              accessibilityState={{ disabled: !valid || busy }}
              testID="unlock-reason-confirm"
              accessibilityRole="button"
            >
              {busy ? <ActivityIndicator size="small" color="#fff" /> : <Text style={s.confirmText}>Unlock & save</Text>}
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.45)" },
  card: {
    width: "100%", maxWidth: 420, backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.xl, alignItems: "center", gap: spacing.sm,
  },
  title: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, textAlign: "center" },
  body: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
  input: {
    alignSelf: "stretch", minHeight: 72, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm, marginTop: spacing.sm,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, textAlignVertical: "top",
  },
  inputError: { borderColor: colors.error },
  hint: { alignSelf: "stretch", fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  hintError: { color: colors.error },
  actions: { flexDirection: "row", gap: spacing.sm, alignSelf: "stretch", marginTop: spacing.sm },
  cancel: {
    flex: 1, minHeight: 44, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  cancelText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.muted },
  confirm: { flex: 1, minHeight: 44, borderRadius: radius.md, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  confirmText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  disabled: { opacity: 0.5 },
});
