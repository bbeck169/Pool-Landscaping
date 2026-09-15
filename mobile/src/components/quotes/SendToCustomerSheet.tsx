/**
 * SendToCustomerSheet — mobile mirror of web's SendToCustomerModal.
 *
 * Fires `POST /quotes/{qid}/send-to-customer` with optional recipient
 * override and admin note.
 *
 * Props:
 *   visible      — controls modal visibility
 *   quoteId      — the quote to send
 *   primaryEmail — pre-filled recipient from quote.customer_email
 *   onClose      — close handler
 *   onSent       — called after successful send (parent refreshes data)
 */
import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Modal,
  Pressable,
  ActivityIndicator,
  Platform,
  KeyboardAvoidingView,
  Switch } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { mapApiError } from "@/src/utils/mapApiError";
import AppTextInput from "@/src/components/ui/AppTextInput";

interface Props {
  visible: boolean;
  quoteId: string;
  primaryEmail?: string;
  onClose: () => void;
  onSent: () => void;
}

export default function SendToCustomerSheet({
  visible,
  quoteId,
  primaryEmail,
  onClose,
  onSent,
}: Props) {
  const { showToast } = useToast();

  const [busy, setBusy] = useState(false);
  const [useOverride, setUseOverride] = useState(false);
  const [override, setOverride] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  // Reset on every open
  useEffect(() => {
    if (visible) {
      setBusy(false);
      setUseOverride(false);
      setOverride("");
      setNote("");
      setError("");
    }
  }, [visible, quoteId]);

  const recipientPreview = useOverride
    ? (override || "").trim() || "(enter an address)"
    : primaryEmail || "(no email on file)";

  const canSubmit = !busy && (!useOverride || !!override.trim());

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    const body: Record<string, string> = {};
    if (useOverride && override.trim()) {
      body.recipient_email = override.trim();
    }
    if (note.trim()) {
      body.note = note.trim().slice(0, 500);
    }
    try {
      const r: any = await api.post(`/quotes/${quoteId}/send-to-customer`, body);
      const recipient = r?.recipient || recipientPreview;
      showToast(`Quote sent to ${recipient}.`);
      onSent();
      onClose();
    } catch (e) {
      const mapped = mapApiError(e);
      setError(mapped.message);
      showToast(mapped.message, "error");
    } finally {
      setBusy(false);
    }
  };

  if (!visible) return null;

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={s.overlay}
      >
        <Pressable style={s.backdrop} onPress={onClose} />
        <View style={s.sheet} testID="send-to-customer-modal">
          {/* Title */}
          <View style={s.titleRow}>
            <Text style={s.title}>Send quote to customer</Text>
            <Pressable onPress={onClose} hitSlop={10} testID="send-to-customer-close">
              <Ionicons name="close" size={24} color={colors.onSurfaceSecondary} />
            </Pressable>
          </View>

          {/* Recipient */}
          <Text style={s.label}>Recipient</Text>
          <Text style={s.recipientPreview} testID="send-to-customer-recipient-preview">
            {recipientPreview}
          </Text>

          <View style={s.overrideRow} testID="send-to-customer-override-row">
            <Switch
              value={useOverride}
              onValueChange={setUseOverride}
              trackColor={{ false: colors.border, true: colors.brand }}
              testID="send-to-customer-override-toggle"
            />
            <Text style={s.overrideLabel}>Send to a different address</Text>
          </View>

          {useOverride ? (
            <AppTextInput
              style={s.input}
              value={override}
              onChangeText={setOverride}
              placeholder="name@example.com"
              placeholderTextColor={colors.muted}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
              testID="send-to-customer-override-input"
            />
          ) : null}

          {/* Note */}
          <Text style={[s.label, { marginTop: spacing.md }]}>
            Admin note (audit only — not shown to customer)
          </Text>
          <AppTextInput
            style={[s.input, s.noteInput]}
            value={note}
            onChangeText={(t) => setNote(t.slice(0, 500))}
            placeholder="Optional context recorded on the send audit log."
            placeholderTextColor={colors.muted}
            multiline
            maxLength={500}
            testID="send-to-customer-note-input"
          />
          <Text style={s.charCount} testID="send-to-customer-note-count">
            {note.length}/500
          </Text>

          {/* Error */}
          {error ? (
            <Text style={s.error} testID="send-to-customer-error">{error}</Text>
          ) : null}

          {/* Actions */}
          <View style={s.actions}>
            <Pressable
              style={s.cancelBtn}
              onPress={onClose}
              testID="send-to-customer-cancel"
              accessibilityRole="button"
            >
              <Text style={s.cancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[s.submitBtn, !canSubmit && { opacity: 0.4 }]}
              onPress={submit}
              disabled={!canSubmit}
              testID="send-to-customer-submit"
              accessibilityRole="button"
            >
              {busy ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <>
                  <Ionicons name="send-outline" size={14} color="#fff" />
                  <Text style={s.submitText}>Send</Text>
                </>
              )}
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

/* ------------------------------------------------------------------ */
/*  Styles                                                             */
/* ------------------------------------------------------------------ */

const s = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: "flex-end",
  },
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    padding: spacing.xl,
    paddingBottom: 34,
  },
  titleRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: spacing.md,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  label: {
    fontFamily: font.bold,
    fontSize: 10,
    color: colors.muted,
    letterSpacing: 1,
    textTransform: "uppercase",
    marginBottom: spacing.xs,
  },
  recipientPreview: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  overrideRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  overrideLabel: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 44,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  noteInput: {
    height: 80,
    paddingTop: spacing.sm,
    textAlignVertical: "top",
  },
  charCount: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    textAlign: "right",
    marginTop: 2,
  },
  error: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.error,
    marginTop: spacing.sm,
  },
  actions: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
  cancelBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: 10,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cancelText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  submitBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: spacing.lg,
    paddingVertical: 10,
    borderRadius: radius.md,
    backgroundColor: colors.brand,
  },
  submitText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
});
