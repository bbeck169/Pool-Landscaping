/**
 * TD-96-mobile · Lead SMS / Email compose sheet.
 * 1:1 RN port of web `pages/leads/LeadComposeModal.jsx` (lead-lean on
 * purpose — no templates / attachments; see TD-100 Option A).
 *
 *   SMS   → POST /api/leads/{id}/send-sms   {body, override_consent}
 *   Email → POST /api/leads/{id}/send-email {subject, body, override_consent}
 *
 * GSM counter warns > 160 (multi-segment) and hard-caps at 1600.
 * Consent: `sms_ok` / `email_ok === false` → override toggle required.
 */
import React, { useMemo, useState } from "react";
import { View, Text, StyleSheet, Modal, Pressable, KeyboardAvoidingView, Platform, ScrollView } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api, ApiError } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import AppTextInput from "@/src/components/ui/AppTextInput";

export const SMS_HARD_CAP = 1600;
export const SMS_SINGLE_SEGMENT_WARN = 160;

export type LeadComposeChannel = "sms" | "email";

/** Mirrors web: string detail → as-is; `{message}` dict → message; else e.message. */
export function composeErrorMessage(e: any): string {
  const d = e instanceof ApiError ? e.detail : e?.detail;
  if (typeof d === "string" && d) return d;
  if (d && typeof d === "object" && typeof (d as any).message === "string") return (d as any).message;
  return e?.message || "Send failed";
}

type Props = { lead: any; channel: LeadComposeChannel; onClose: () => void; onSent?: (row: any) => void };

export default function LeadComposeSheet({ lead, channel, onClose, onSent }: Props) {
  const { showToast } = useToast();
  const isSms = channel === "sms";
  const label = isSms ? "SMS" : "Email";
  const [body, setBody] = useState("");
  const [subject, setSubject] = useState("");
  const [override, setOverride] = useState(false);
  const [busy, setBusy] = useState(false);

  // Consent — absent field on the lead means "OK" (web parity).
  const needsOverride = isSms ? lead?.sms_ok === false : lead?.email_ok === false;
  const charCount = body.length;
  const charWarn = isSms && charCount > SMS_SINGLE_SEGMENT_WARN;
  const charOver = isSms && charCount > SMS_HARD_CAP;

  const canSend = useMemo(() => {
    if (busy) return false;
    if (needsOverride && !override) return false;
    if (isSms) return body.trim().length > 0 && body.length <= SMS_HARD_CAP;
    return subject.trim().length > 0 && body.trim().length > 0;
  }, [busy, needsOverride, override, isSms, body, subject]);

  const submit = async () => {
    if (!canSend) return;
    setBusy(true);
    try {
      const path = isSms ? `/leads/${lead.id}/send-sms` : `/leads/${lead.id}/send-email`;
      const payload = isSms ? { body, override_consent: override } : { subject, body, override_consent: override };
      const row = await api.post(path, payload);
      const status = row?.status || "sent";
      if (status === "sent") showToast(`${label} sent`, "success");
      else showToast(`${label} ${status}${row?.error || row?.provider_status_raw ? ` — ${row?.error || row?.provider_status_raw}` : ""}`, "error");
      onSent?.(row); // TD-96-mobile-timeline · web LeadComposeModal parity (any persisted row)
      onClose();
    } catch (e: any) {
      showToast(composeErrorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const counterColor = charOver ? colors.error : charWarn ? "#B45309" : colors.muted;

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView style={s.overlay} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <View style={s.card} testID="lead-compose-modal">
          <View style={s.headRow}>
            <Text style={s.title}>{isSms ? "Send SMS" : "Send Email"}</Text>
            <Pressable onPress={onClose} hitSlop={12} style={s.closeBtn} testID="lead-compose-close" accessibilityLabel="Close compose">
              <Ionicons name="close" size={20} color={colors.muted} />
            </Pressable>
          </View>
          <ScrollView keyboardShouldPersistTaps="handled">
            <Text style={s.to} testID="lead-compose-to">
              {`To: ${(isSms ? lead?.phone : lead?.email) || "—"}${lead?.name ? `  · ${lead.name}` : ""}`}
            </Text>
            {needsOverride ? (
              <View style={s.consent} testID="lead-compose-consent-warning">
                <Text style={s.consentTitle}>{`This lead has opted out of ${isSms ? "SMS" : "email"}.`}</Text>
                <Pressable
                  onPress={() => setOverride((v) => !v)} style={s.checkRow} testID="lead-compose-override"
                  accessibilityRole="checkbox" accessibilityState={{ checked: override }}
                >
                  <Ionicons name={override ? "checkbox" : "square-outline"} size={20} color="#9F1239" />
                  <Text style={s.consentText}>Override — send anyway</Text>
                </Pressable>
              </View>
            ) : null}
            {!isSms ? (
              <>
                <Text style={s.label}>Subject</Text>
                <AppTextInput
                  style={s.input} value={subject} onChangeText={setSubject} maxLength={200}
                  placeholder="Following up on your quote request…" placeholderTextColor={colors.muted}
                  testID="lead-compose-subject"
                />
              </>
            ) : null}
            <Text style={s.label}>{isSms ? "Message" : "Body"}</Text>
            <AppTextInput
              style={[s.input, s.body, !isSms && { minHeight: 160 }]} value={body} onChangeText={setBody} multiline
              maxLength={isSms ? SMS_HARD_CAP : 50000} placeholderTextColor={colors.muted}
              placeholder={isSms ? "Hi, following up on your quote request…" : "Write your message…"}
              testID="lead-compose-body"
            />
            {isSms ? (
              <Text style={[s.counter, { color: counterColor }, charOver && { fontFamily: font.semibold }]} testID="lead-compose-char-counter">
                {`${charCount} / ${SMS_HARD_CAP}${charWarn && !charOver ? " · will send as multi-segment SMS" : ""}${charOver ? " · over the 1600-character cap" : ""}`}
              </Text>
            ) : null}
          </ScrollView>
          <View style={s.btns}>
            <Pressable style={s.cancel} onPress={onClose} testID="lead-compose-cancel">
              <Text style={s.cancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[s.send, !canSend && { opacity: 0.5 }]} onPress={submit} disabled={!canSend}
              accessibilityState={{ disabled: !canSend }} testID="lead-compose-send"
            >
              <Text style={s.sendText}>{busy ? "Sending…" : isSms ? "Send SMS" : "Send Email"}</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const s = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "center", padding: spacing.lg },
  card: { backgroundColor: "#fff", borderRadius: radius.lg, padding: spacing.xl, maxHeight: "90%" },
  headRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  title: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  closeBtn: { minWidth: 44, minHeight: 44, alignItems: "flex-end", justifyContent: "center" },
  to: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginBottom: spacing.md },
  consent: { borderWidth: 1, borderColor: "#FECDD3", backgroundColor: "#FFF1F2", borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  consentTitle: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#9F1239" },
  checkRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44 },
  consentText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#9F1239" },
  label: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: 4 },
  input: {
    backgroundColor: "#F8FAFC", borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm,
  },
  body: { minHeight: 110, textAlignVertical: "top" },
  counter: { fontFamily: font.regular, fontSize: 11, marginTop: -4 },
  btns: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.lg },
  cancel: { paddingHorizontal: 16, minHeight: 44, justifyContent: "center", borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  cancelText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  send: { paddingHorizontal: 16, minHeight: 44, justifyContent: "center", borderRadius: radius.md, backgroundColor: colors.brand },
  sendText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
});
