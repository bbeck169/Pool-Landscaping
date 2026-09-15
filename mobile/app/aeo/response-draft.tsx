// Phase 16 · Feb-2026 — Response draft composer.
//
// Tone pills, editable body, character counter vs a platform character
// hint, copy to clipboard, mark as posted, discard. Includes a
// "Suggested from your library" collapsible fed by
// `/api/aeo/response/templates`.
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { router, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { Card, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Tone = "empathetic" | "professional" | "apologetic" | "assertive";
const TONES: { key: Tone; label: string }[] = [
  { key: "empathetic",   label: "Empathetic" },
  { key: "professional", label: "Professional" },
  { key: "apologetic",   label: "Apologetic" },
  { key: "assertive",    label: "Assertive" },
];

// Rough per-platform char hints — matches web behavior.
const PLATFORM_HINTS: Record<string, number> = {
  google: 4000, yelp: 5000, facebook: 8000, x: 280, generic: 4000,
};

export default function ResponseDraft() {
  const { showToast } = useToast();
  const { mentionId, platform: platformParam } = useLocalSearchParams<{
    mentionId?: string; platform?: string;
  }>();
  const [tone, setTone] = useState<Tone>("professional");
  const [body, setBody] = useState("");
  const [generating, setGenerating] = useState(false);
  const [posting, setPosting] = useState(false);
  const [templates, setTemplates] = useState<any[]>([]);
  const [showLib, setShowLib] = useState(false);
  const [draftId, setDraftId] = useState<string | null>(null);

  const platform = (platformParam || "generic").toLowerCase();
  const charLimit = PLATFORM_HINTS[platform] ?? PLATFORM_HINTS.generic;
  const over = body.length > charLimit;

  const loadTemplates = useCallback(async () => {
    try {
      const j: any = await api.get("/aeo/response/templates");
      setTemplates(j?.templates || j?.items || []);
    } catch {
      setTemplates([]);
    }
  }, []);
  useEffect(() => { loadTemplates(); }, [loadTemplates]);

  const generate = async () => {
    if (!mentionId) {
      Alert.alert("No mention selected", "Open a mention first, then Draft reply.");
      return;
    }
    setGenerating(true);
    try {
      const j: any = await api.post(
        `/aeo/mentions/${encodeURIComponent(mentionId)}/response/draft`,
        { tone },
      );
      const draft = j?.draft || j;
      setBody(draft?.body || draft?.text || "");
      if (draft?.id) setDraftId(draft.id);
    } catch (err: any) {
      showToast(String(err?.message || err), "error");
    } finally {
      setGenerating(false);
    }
  };

  const copyBody = async () => {
    await Clipboard.setStringAsync(body);
    showToast("The draft is on your clipboard.");
  };

  const markPosted = async () => {
    if (!draftId) {
      Alert.alert("No draft", "Generate a draft first, then mark it posted.");
      return;
    }
    setPosting(true);
    try {
      await api.post(`/aeo/response/drafts/${encodeURIComponent(draftId)}`, {
        action: "mark_posted",
      });
      showToast("The draft is now marked as posted.");
    } catch (err: any) {
      showToast(String(err?.message || err), "error");
    } finally {
      setPosting(false);
    }
  };

  return (
    <RoleGate level="admin_plus">
      <View style={styles.container}>
        <Header title="Draft reply" />
        <ScrollView contentContainerStyle={styles.body}>
          <Card>
            <Text style={styles.sectionLabel}>Tone</Text>
            <View style={styles.toneRow}>
              {TONES.map((t) => {
                const on = tone === t.key;
                return (
                  <Pressable
                    key={t.key}
                    testID={`tone-pill-${t.key}`}
                    accessibilityLabel={`Tone ${t.label}`}
                    onPress={() => setTone(t.key)}
                    style={[styles.tonePill, on && styles.tonePillOn]}
                  >
                    <Text style={[styles.tonePillText, on && styles.tonePillTextOn]}>
                      {t.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
            <PrimaryButton
              testID="draft-generate-btn"
              title={generating ? "Drafting…" : "Generate draft"}
              icon="sparkles-outline"
              onPress={generate}
              loading={generating}
              disabled={!mentionId}
            />
          </Card>

          <Card>
            <View style={styles.rowBetween}>
              <Text style={styles.sectionLabel}>Reply body</Text>
              <Text style={[styles.charCount, over && { color: colors.error }]}>
                {body.length}/{charLimit}
              </Text>
            </View>
            <AppTextInput
              testID="draft-body-input"
              multiline
              value={body}
              onChangeText={setBody}
              placeholder="Your reply will appear here…"
              placeholderTextColor={colors.muted}
              style={styles.textarea}
            />
            <View style={styles.actionRow}>
              <Pressable
                testID="draft-copy-btn"
                accessibilityLabel="Copy reply to clipboard"
                onPress={copyBody}
                style={[styles.actionBtn, { backgroundColor: colors.brandTertiary }]}
              >
                <Ionicons name="copy-outline" size={16} color={colors.onBrandTertiary} />
                <Text style={{ color: colors.onBrandTertiary, fontFamily: font.semibold, marginLeft: 6 }}>Copy</Text>
              </Pressable>
              <Pressable
                testID="draft-mark-posted-btn"
                accessibilityLabel="Mark as posted"
                onPress={markPosted}
                disabled={posting || !draftId}
                style={[styles.actionBtn, { backgroundColor: "#DCFCE7", opacity: posting || !draftId ? 0.5 : 1 }]}
              >
                <Ionicons name="checkmark-done-outline" size={16} color={colors.success} />
                <Text style={{ color: colors.success, fontFamily: font.semibold, marginLeft: 6 }}>Mark posted</Text>
              </Pressable>
              <Pressable
                testID="draft-discard-btn"
                accessibilityLabel="Discard draft"
                onPress={() => setBody("")}
                style={[styles.actionBtn, { backgroundColor: colors.surfaceSecondary }]}
              >
                <Ionicons name="trash-outline" size={16} color={colors.error} />
                <Text style={{ color: colors.error, fontFamily: font.semibold, marginLeft: 6 }}>Discard</Text>
              </Pressable>
            </View>
          </Card>

          <Card>
            <Pressable
              testID="draft-library-toggle"
              onPress={() => setShowLib((v) => !v)}
              style={styles.rowBetween}
            >
              <Text style={styles.sectionLabel}>
                Suggested from your library ({templates.length})
              </Text>
              <Ionicons name={showLib ? "chevron-up" : "chevron-down"} size={20} color={colors.muted} />
            </Pressable>
            {showLib ? (
              templates.length === 0 ? (
                <Text style={styles.hint}>No templates yet.</Text>
              ) : (
                templates.slice(0, 10).map((t: any) => (
                  <Pressable
                    key={t.id}
                    testID={`draft-template-${t.id}`}
                    onPress={() => setBody((t.body || t.text || "").slice(0, charLimit))}
                    style={styles.tplRow}
                  >
                    <View style={{ flex: 1 }}>
                      <Text style={styles.tplTitle}>{t.title || "Untitled"}</Text>
                      <Text style={styles.tplBody} numberOfLines={2}>
                        {t.body || t.text || ""}
                      </Text>
                    </View>
                    <Ionicons name="arrow-forward" size={16} color={colors.muted} />
                  </Pressable>
                ))
              )
            ) : null}
          </Card>
        </ScrollView>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  sectionLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  toneRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: spacing.md },
  tonePill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  tonePillOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  tonePillText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  tonePillTextOn: { color: "#FFFFFF" },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  charCount: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  textarea: {
    minHeight: 140,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface, textAlignVertical: "top",
  },
  actionRow: { flexDirection: "row", gap: 6, marginTop: spacing.md, flexWrap: "wrap" },
  actionBtn: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  tplRow: { flexDirection: "row", alignItems: "center", paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider, gap: spacing.sm },
  tplTitle: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  tplBody: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
