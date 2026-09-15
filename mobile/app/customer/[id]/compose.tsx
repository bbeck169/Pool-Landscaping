/**
 * Phase 29 · Template Compose Screen
 *
 * Accessed from customer detail → SendCreateSheet → "Send Message"
 * Route: /customer/[id]/compose?channel=email|sms
 *
 * 1. GET /api/marketing/templates?channel={channel} → list templates
 * 2. User picks a template → shows variable fields to fill
 * 3. POST /api/marketing/templates/preview-message → preview rendered message
 * 4. POST /api/communications/send → send
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Alert,
  ActivityIndicator, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { PrimaryButton } from "@/src/components/ui";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Template = {
  id: string;
  name: string;
  channel: string;
  subject?: string;
  body: string;
  variables?: string[];
};

export default function ComposeScreen() {
  const { id: customerId, channel: channelParam } = useLocalSearchParams<{ id: string; channel: string }>();
  const router = useRouter();
  const channel = channelParam || "email";

  const [templates, setTemplates] = useState<Template[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [vars, setVars] = useState<Record<string, string>>({});
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [preview, setPreview] = useState("");
  const [showPreview, setShowPreview] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.get(`/marketing/templates?channel=${channel}`);
        setTemplates(res.templates || res || []);
      } catch { setTemplates([]); }
      finally { setLoadingTemplates(false); }
    })();
  }, [channel]);

  const selectTemplate = useCallback((t: Template) => {
    setSelectedTemplate(t);
    setSubject(t.subject || "");
    setBody(t.body || "");
    const v: Record<string, string> = {};
    (t.variables || []).forEach((k: string) => { v[k] = ""; });
    setVars(v);
  }, []);

  const doPreview = useCallback(async () => {
    if (!selectedTemplate) return;
    try {
      const res = await api.post("/marketing/templates/preview-message", {
        template_id: selectedTemplate.id,
        variables: vars,
        customer_id: customerId,
      });
      setPreview(res.rendered || res.body || body);
      setShowPreview(true);
    } catch {
      // If preview endpoint fails, show raw body
      setPreview(body);
      setShowPreview(true);
    }
  }, [selectedTemplate, vars, customerId, body]);

  const send = useCallback(async () => {
    setSending(true);
    try {
      await api.post("/communications/send", {
        customer_id: customerId,
        channel,
        template_id: selectedTemplate?.id,
        subject: channel === "email" ? subject : undefined,
        body: body || preview,
        variables: vars,
      });
      Alert.alert("Sent!", `${channel === "email" ? "Email" : "SMS"} sent successfully.`, [
        { text: "OK", onPress: () => router.back() },
      ]);
    } catch (e: any) {
      Alert.alert("Send failed", e?.message || "Unknown error");
    } finally { setSending(false); }
  }, [customerId, channel, selectedTemplate, subject, body, preview, vars, router]);

  if (loadingTemplates) {
    return (
      <View style={s.root} testID="compose-loading">
        <Header title={`Compose ${channel === "email" ? "Email" : "SMS"}`} back />
        <ActivityIndicator size="large" color={colors.brand} style={{ marginTop: 60 }} />
      </View>
    );
  }

  // Show preview
  if (showPreview) {
    return (
      <View style={s.root} testID="compose-preview">
        <Header title="Preview" back />
        <ScrollView contentContainerStyle={s.content}>
          {channel === "email" && subject ? (
            <Text style={s.previewSubject}>{subject}</Text>
          ) : null}
          <View style={s.previewBody}>
            <Text style={s.previewText}>{preview}</Text>
          </View>
          <View style={{ flexDirection: "row", gap: spacing.md, marginTop: spacing.xl }}>
            <Pressable style={s.backBtn} onPress={() => setShowPreview(false)} testID="preview-back">
              <Text style={s.backBtnText}>Edit</Text>
            </Pressable>
            <View style={{ flex: 1 }}>
              <PrimaryButton title="Send" icon="send-outline" onPress={send} loading={sending} testID="compose-send" />
            </View>
          </View>
        </ScrollView>
      </View>
    );
  }

  // Template picker (no template selected yet)
  if (!selectedTemplate) {
    return (
      <View style={s.root} testID="compose-template-picker">
        <Header title={`Compose ${channel === "email" ? "Email" : "SMS"}`} back />
        <ScrollView contentContainerStyle={s.content}>
          <Text style={s.sectionTitle}>Choose a template</Text>
          {templates.length === 0 ? (
            <Text style={s.emptyText}>No templates found for {channel}. You can compose a free-form message instead.</Text>
          ) : null}
          {templates.map((t) => (
            <Pressable
              key={t.id}
              style={s.templateCard}
              onPress={() => selectTemplate(t)}
              testID={`compose-template-${t.id}`}
            >
              <Ionicons name="document-text-outline" size={20} color={colors.brand} />
              <View style={{ flex: 1 }}>
                <Text style={s.templateName}>{t.name}</Text>
                {t.subject ? <Text style={s.templateSub} numberOfLines={1}>{t.subject}</Text> : null}
              </View>
              <Ionicons name="chevron-forward" size={16} color={colors.muted} />
            </Pressable>
          ))}
          <Pressable
            style={[s.templateCard, { borderStyle: "dashed" }]}
            onPress={() => selectTemplate({ id: "", name: "Free-form", channel, body: "", variables: [] })}
            testID="compose-freeform"
          >
            <Ionicons name="create-outline" size={20} color={colors.brand} />
            <Text style={[s.templateName, { flex: 1 }]}>Free-form message</Text>
            <Ionicons name="chevron-forward" size={16} color={colors.muted} />
          </Pressable>
        </ScrollView>
      </View>
    );
  }

  // Compose with selected template
  return (
    <View style={s.root} testID="compose-editor">
      <Header title={selectedTemplate.name || "Compose"} back />
      <KeyboardAwareScrollView
        contentContainerStyle={s.content}
        bottomOffset={24}
        keyboardShouldPersistTaps="handled"
      >
        {/* Variable fields */}
        {Object.keys(vars).length > 0 ? (
          <View style={s.varsSection}>
            <Text style={s.sectionTitle}>Fill in details</Text>
            {Object.keys(vars).map((k) => (
              <View key={k} style={s.varRow}>
                <Text style={s.varLabel}>{k.replace(/_/g, " ").toUpperCase()}</Text>
                <AppTextInput
                  style={s.varInput}
                  value={vars[k]}
                  onChangeText={(v) => setVars((p) => ({ ...p, [k]: v }))}
                  placeholder={`Enter ${k.replace(/_/g, " ")}`}
                  placeholderTextColor={colors.muted}
                  testID={`compose-var-${k}`}
                />
              </View>
            ))}
          </View>
        ) : null}

        {channel === "email" ? (
          <>
            <Text style={s.varLabel}>SUBJECT</Text>
            <AppTextInput
              style={s.varInput}
              value={subject}
              onChangeText={setSubject}
              placeholder="Email subject"
              placeholderTextColor={colors.muted}
              testID="compose-subject"
            />
          </>
        ) : null}

        <Text style={[s.varLabel, { marginTop: spacing.lg }]}>MESSAGE</Text>
        <AppTextInput
          style={[s.varInput, { minHeight: 140, textAlignVertical: "top" }]}
          value={body}
          onChangeText={setBody}
          placeholder="Type your message…"
          placeholderTextColor={colors.muted}
          multiline
          numberOfLines={6}
          testID="compose-body"
        />

        <View style={{ flexDirection: "row", gap: spacing.md, marginTop: spacing.xl }}>
          <Pressable style={s.previewBtn} onPress={doPreview} testID="compose-preview-btn">
            <Ionicons name="eye-outline" size={18} color={colors.brand} />
            <Text style={s.previewBtnText}>Preview</Text>
          </Pressable>
          <View style={{ flex: 1 }}>
            <PrimaryButton
              title="Send"
              icon="send-outline"
              onPress={send}
              loading={sending}
              disabled={!body.trim()}
              testID="compose-send"
            />
          </View>
        </View>
      </KeyboardAwareScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  content: { padding: spacing.lg, paddingBottom: spacing["3xl"] },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: spacing.md },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, lineHeight: 22, marginBottom: spacing.lg },
  templateCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    padding: spacing.md, borderRadius: radius.lg,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  templateName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  templateSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  varsSection: { marginBottom: spacing.lg },
  varRow: { marginBottom: spacing.md },
  varLabel: {
    fontFamily: font.semibold, fontSize: 11, letterSpacing: 1,
    color: colors.onSurfaceSecondary, marginBottom: spacing.xs,
  },
  varInput: {
    borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: 10, backgroundColor: colors.surface,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  previewBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 16, paddingVertical: 12, borderRadius: radius.md,
    borderWidth: 1.5, borderColor: colors.brand,
  },
  previewBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  backBtn: {
    paddingHorizontal: 16, paddingVertical: 12, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
  },
  backBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  previewSubject: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: spacing.md },
  previewBody: {
    padding: spacing.lg, borderRadius: radius.lg,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  previewText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 22 },
});
