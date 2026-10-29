/**
 * Customer detail · Email compose sheet (Ticket 1 · D1a).
 * RN port of web `SendComposeModal` (CustomerDetail.jsx), email channel only,
 * WITHOUT attachments + AI draft (explicit follow-ups). Shell borrowed from
 * `LeadComposeSheet`.
 *
 *   Templates → GET  /marketing/templates?channel=email&active=true
 *   Preview   → POST /customers/{id}/preview-message {channel, subject, body}
 *   Send      → POST /customers/{id}/send-email {to, subject || "Message from {name}", body, customer_id}
 *
 * BE `send-email` is require_admin and validates `to` against the customer's
 * emails — callers gate on isAdmin && primaryEmail.
 */
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Modal, Pressable, KeyboardAvoidingView, Platform, ScrollView, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { composeErrorMessage } from "@/src/components/leads/LeadComposeSheet";

type Template = { id: string; name?: string; subject?: string; body?: string };
type Preview = { subject_rendered?: string | null; body_rendered?: string; unresolved_tokens?: string[] };
type Props = { customer: any; to: string; onClose: () => void; onSent?: () => void };

export default function CustomerEmailComposeSheet({ customer, to, onClose, onSent }: Props) {
  const { showToast } = useToast();
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [pickedId, setPickedId] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.get("/marketing/templates?channel=email&active=true")
      .then((r: any) => { if (!cancelled) setTemplates(r?.templates || []); })
      .catch(() => { if (!cancelled) setTemplates([]); });
    return () => { cancelled = true; };
  }, []);

  const pick = (t: Template | null) => {
    setPickedId(t?.id || "");
    setSubject(t?.subject || "");
    setBody(t?.body || "");
    setPreview(null);
  };

  const runPreview = async () => {
    if (!body.trim()) { showToast("Nothing to preview", "error"); return; }
    setPreviewing(true);
    try {
      const r: any = await api.post(`/customers/${customer.id}/preview-message`, { channel: "email", subject: subject || "", body: body || "" });
      setPreview(r);
    } catch (e: any) {
      showToast(composeErrorMessage(e) || "Preview failed", "error");
    } finally { setPreviewing(false); }
  };

  const canSend = !busy && body.trim().length > 0;
  const submit = async () => {
    if (!canSend) return;
    setBusy(true);
    try {
      await api.post(`/customers/${customer.id}/send-email`, {
        to, subject: subject || `Message from ${customer?.name || "your service"}`, body, customer_id: customer.id,
      });
      showToast("Message sent", "success");
      onSent?.();
      onClose();
    } catch (e: any) {
      showToast(composeErrorMessage(e), "error");
    } finally { setBusy(false); }
  };

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView style={s.overlay} behavior={Platform.OS === "ios" ? "padding" : "height"}>
        <View style={s.card} testID="customer-email-compose-modal">
          <View style={s.headRow}>
            <Text style={s.title} numberOfLines={1}>{`Email ${to}`}</Text>
            <Pressable onPress={onClose} hitSlop={12} style={s.closeBtn} testID="customer-email-compose-close" accessibilityLabel="Close compose">
              <Ionicons name="close" size={20} color={colors.muted} />
            </Pressable>
          </View>
          <ScrollView keyboardShouldPersistTaps="handled">
            <Text style={s.label}>Template</Text>
            <TemplateChips templates={templates} pickedId={pickedId} onPick={pick} />
            <Text style={s.label}>Subject</Text>
            <AppTextInput
              style={s.input} value={subject} onChangeText={(v: string) => { setSubject(v); setPreview(null); }} maxLength={200}
              placeholder={`Message from ${customer?.name || "your service"}`} placeholderTextColor={colors.muted}
              testID="customer-email-compose-subject"
            />
            <Text style={s.label}>Message</Text>
            <AppTextInput
              style={[s.input, s.body]} value={body} onChangeText={(v: string) => { setBody(v); setPreview(null); }} multiline
              maxLength={50000} placeholder="Write your message…" placeholderTextColor={colors.muted}
              testID="customer-email-compose-body"
            />
            {preview ? <PreviewBox preview={preview} /> : null}
          </ScrollView>
          <View style={s.btns}>
            <Pressable style={[s.ghost, previewing && { opacity: 0.5 }]} onPress={runPreview} disabled={previewing} testID="customer-email-compose-preview-btn">
              <Text style={s.ghostText}>{previewing ? "Rendering…" : "Preview"}</Text>
            </Pressable>
            <Pressable style={s.ghost} onPress={onClose} testID="customer-email-compose-cancel">
              <Text style={s.ghostText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[s.send, !canSend && { opacity: 0.5 }]} onPress={submit} disabled={!canSend}
              accessibilityState={{ disabled: !canSend }} testID="customer-email-compose-send"
            >
              <Text style={s.sendText}>{busy ? "Sending…" : "Send"}</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function TemplateChips({ templates, pickedId, onPick }: { templates: Template[] | null; pickedId: string; onPick: (t: Template | null) => void }) {
  if (templates === null) return <ActivityIndicator style={s.chipsLoading} color={colors.brand} testID="customer-email-compose-templates-loading" />;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips} testID="customer-email-compose-templates">
      <Chip label="Custom" active={!pickedId} onPress={() => onPick(null)} testID="customer-email-compose-template-custom" />
      {templates.map((t) => (
        <Chip key={t.id} label={t.name || "Untitled"} active={pickedId === t.id} onPress={() => onPick(t)} testID={`customer-email-compose-template-${t.id}`} />
      ))}
      {templates.length === 0 ? <Text style={s.emptyText} testID="customer-email-compose-templates-empty">No email templates yet</Text> : null}
    </ScrollView>
  );
}

function Chip({ label, active, onPress, testID }: { label: string; active: boolean; onPress: () => void; testID: string }) {
  return (
    <Pressable style={[s.chip, active && s.chipActive]} onPress={onPress} testID={testID} accessibilityState={{ selected: active }}>
      <Text style={[s.chipText, active && s.chipTextActive]} numberOfLines={1}>{label}</Text>
    </Pressable>
  );
}

function PreviewBox({ preview }: { preview: Preview }) {
  const unresolved = preview.unresolved_tokens || [];
  return (
    <View style={s.preview} testID="customer-email-compose-preview">
      {preview.subject_rendered ? <Text style={s.previewSubject} testID="customer-email-compose-preview-subject">{preview.subject_rendered}</Text> : null}
      <Text style={s.previewBody} testID="customer-email-compose-preview-body">{preview.body_rendered || ""}</Text>
      {unresolved.length ? (
        <Text style={s.unresolved} testID="customer-email-compose-preview-unresolved">{`Unresolved: ${unresolved.join(", ")}`}</Text>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "center", padding: spacing.lg },
  card: { backgroundColor: "#fff", borderRadius: radius.lg, padding: spacing.xl, maxHeight: "90%" },
  headRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  title: { flex: 1, fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  closeBtn: { minWidth: 44, minHeight: 44, alignItems: "flex-end", justifyContent: "center" },
  label: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: 4 },
  chips: { gap: spacing.sm, paddingBottom: spacing.md, alignItems: "center" },
  chipsLoading: { alignSelf: "flex-start", marginBottom: spacing.md },
  chip: { paddingHorizontal: 12, minHeight: 36, justifyContent: "center", borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: "#F8FAFC", maxWidth: 200 },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  chipTextActive: { color: "#fff" },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  input: {
    backgroundColor: "#F8FAFC", borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm,
  },
  body: { minHeight: 160, textAlignVertical: "top" },
  preview: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md, backgroundColor: "#F1F5F9", marginTop: spacing.sm },
  previewSubject: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: 4 },
  previewBody: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  unresolved: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#B45309", marginTop: spacing.sm },
  btns: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.lg },
  ghost: { paddingHorizontal: 14, minHeight: 44, justifyContent: "center", borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  ghostText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  send: { paddingHorizontal: 16, minHeight: 44, justifyContent: "center", borderRadius: radius.md, backgroundColor: colors.brand },
  sendText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
});
