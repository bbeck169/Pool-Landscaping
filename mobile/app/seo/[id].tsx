import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Alert, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import DateTimePicker from "@react-native-community/datetimepicker";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Card, PrimaryButton, Loading, StatusChip, Sheet } from "@/src/components/ui";

const fmtDate = (iso?: string) =>
  iso ? new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";

export default function SeoArticleDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [art, setArt] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [audit, setAudit] = useState<any>(null);
  const [auditing, setAuditing] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [schedOpen, setSchedOpen] = useState(false);
  const [scheduling, setScheduling] = useState(false);
  const [pickDate, setPickDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(9, 0, 0, 0);
    return d;
  });
  const [showPicker, setShowPicker] = useState(false);

  const load = useCallback(async () => {
    try {
      setArt(await api.get(`/seo/articles/${id}`));
    } catch {}
    setLoading(false);
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const runAudit = async () => {
    setAuditing(true);
    try {
      setAudit(await api.post("/seo/audit", { keyword: art.keyword, article_id: id }));
    } catch (e: any) {
      Alert.alert("Audit failed", e.message);
    } finally {
      setAuditing(false);
    }
  };

  const doPublish = (status: "publish" | "draft") => {
    Alert.alert(
      status === "publish" ? "Publish to WordPress?" : "Save as draft?",
      status === "publish"
        ? "This will publish the article live on your WordPress site."
        : "This will create a draft post on your WordPress site.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: status === "publish" ? "Publish" : "Save Draft",
          onPress: async () => {
            setPublishing(true);
            try {
              const r = await api.post(`/seo/articles/${id}/publish`, { status });
              await load();
              Alert.alert("Success ✅", `Post ${r.status} on WordPress.`);
            } catch (e: any) {
              Alert.alert("Publish failed", e.message);
            } finally {
              setPublishing(false);
            }
          },
        },
      ]
    );
  };

  const copyMarkdown = async () => {
    await Clipboard.setStringAsync(art?.body_markdown || "");
    Alert.alert("Copied", "Article markdown copied to clipboard.");
  };

  const scheduleAuto = async () => {
    setScheduling(true);
    try {
      const r = await api.post(`/seo/articles/${id}/schedule`, { mode: "auto" });
      setSchedOpen(false);
      await load();
      Alert.alert("Added to weekly queue ✅", `Will publish ${fmtDate(r.scheduled_for)}.`);
    } catch (e: any) {
      Alert.alert("Failed", e.message);
    } finally {
      setScheduling(false);
    }
  };

  const scheduleManual = async (when: Date) => {
    setScheduling(true);
    try {
      const r = await api.post(`/seo/articles/${id}/schedule`, { mode: "manual", scheduled_for: when.toISOString() });
      setSchedOpen(false);
      await load();
      Alert.alert("Scheduled ✅", `Will publish ${fmtDate(r.scheduled_for)}.`);
    } catch (e: any) {
      Alert.alert("Failed", e.message);
    } finally {
      setScheduling(false);
    }
  };

  const preset = (days: number) => {
    const d = new Date();
    d.setDate(d.getDate() + days);
    d.setHours(9, 0, 0, 0);
    return d;
  };

  const unschedule = async () => {
    try {
      await api.post(`/seo/articles/${id}/unschedule`, {});
      await load();
    } catch (e: any) {
      Alert.alert("Failed", e.message);
    }
  };

  if (loading) return <View style={styles.root}><Header title="Article" back /><Loading /></View>;
  if (!art) return <View style={styles.root}><Header title="Article" back /></View>;

  const scoreColor = (s: number) => (s >= 80 ? colors.success : s >= 50 ? colors.warning : colors.error);
  const statusIcon = (st: string) => (st === "pass" ? "checkmark-circle" : st === "warn" ? "alert-circle" : "close-circle");
  const statusColor = (st: string) => (st === "pass" ? colors.success : st === "warn" ? colors.warning : colors.error);

  return (
    <View style={styles.root}>
      <Header title="Article" back subtitle={art.keyword} />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm }}>
          <StatusChip status={art.status || "draft"} />
          {art.wp_link ? (
            <Pressable onPress={() => Clipboard.setStringAsync(art.wp_link)}>
              <Text style={styles.link} numberOfLines={1}>{art.wp_link}</Text>
            </Pressable>
          ) : null}
        </View>

        <Text style={styles.title}>{art.title}</Text>
        <Text style={styles.meta}>{art.meta_description}</Text>
        <View style={styles.tagRow}>
          {(art.tags || []).map((t: string, i: number) => (
            <View key={i} style={styles.tag}><Text style={styles.tagText}>{t}</Text></View>
          ))}
        </View>
        <Text style={styles.wordCount}>{art.word_count || 0} words · slug: {art.slug}</Text>

        <View style={styles.actions}>
          <View style={{ flex: 1 }}>
            <PrimaryButton title="Publish" icon="cloud-upload-outline" loading={publishing} onPress={() => doPublish("publish")} testID="seo-publish" />
          </View>
          <View style={{ flex: 1 }}>
            <PrimaryButton title="Draft" variant="outline" onPress={() => doPublish("draft")} testID="seo-publish-draft" />
          </View>
        </View>

        {art.status === "scheduled" ? (
          <Card style={styles.schedCard}>
            <Ionicons name="time-outline" size={20} color="#4338CA" />
            <View style={{ flex: 1 }}>
              <Text style={styles.schedTitle}>Scheduled {art.queue_mode === "auto" ? "(weekly queue)" : ""}</Text>
              <Text style={styles.schedWhen}>{fmtDate(art.scheduled_for)}</Text>
            </View>
            <Pressable onPress={unschedule} hitSlop={8} testID="seo-unschedule">
              <Text style={styles.removeText}>Remove</Text>
            </Pressable>
          </Card>
        ) : (
          <View style={{ marginTop: spacing.sm }}>
            <PrimaryButton title="Schedule Auto-Publish" variant="outline" icon="calendar-outline" onPress={() => setSchedOpen(true)} testID="seo-schedule-open" />
          </View>
        )}

        <View style={{ height: spacing.md }} />
        <PrimaryButton title="Run SEO Audit" variant="outline" icon="analytics-outline" loading={auditing} onPress={runAudit} testID="seo-audit" />

        {audit ? (
          <Card style={{ marginTop: spacing.md }}>
            <View style={styles.scoreRow}>
              <Text style={styles.scoreLabel}>SEO Score</Text>
              <Text style={[styles.scoreVal, { color: scoreColor(audit.score) }]}>{audit.score}/100</Text>
            </View>
            {(audit.checks || []).map((c: any, i: number) => (
              <View key={i} style={styles.checkRow}>
                <Ionicons name={statusIcon(c.status) as any} size={16} color={statusColor(c.status)} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.checkLabel}>{c.label}</Text>
                  <Text style={styles.checkDetail}>{c.detail}</Text>
                </View>
              </View>
            ))}
            {(audit.suggestions || []).length ? (
              <>
                <Text style={styles.suggTitle}>Suggestions</Text>
                {audit.suggestions.map((s: string, i: number) => (
                  <Text key={i} style={styles.suggItem}>• {s}</Text>
                ))}
              </>
            ) : null}
          </Card>
        ) : null}

        <View style={styles.bodyHeader}>
          <Text style={styles.bodyTitle}>Content</Text>
          <Pressable onPress={copyMarkdown} hitSlop={8} style={styles.copyBtn}>
            <Ionicons name="copy-outline" size={16} color={colors.brand} />
            <Text style={styles.copyText}>Copy</Text>
          </Pressable>
        </View>
        <Card>
          <Text style={styles.body}>{art.body_markdown}</Text>
        </Card>

        {(art.faqs || []).length ? (
          <>
            <Text style={[styles.bodyTitle, { marginTop: spacing.lg }]}>FAQs</Text>
            {art.faqs.map((f: any, i: number) => (
              <Card key={i} style={{ marginBottom: spacing.sm }}>
                <Text style={styles.faqQ}>{f.q}</Text>
                <Text style={styles.faqA}>{f.a}</Text>
              </Card>
            ))}
          </>
        ) : null}
      </ScrollView>

      <Sheet visible={schedOpen} onClose={() => setSchedOpen(false)} title="Schedule Auto-Publish" testID="seo-sched-sheet">
        <Text style={styles.sheetHint}>Approved articles publish to WordPress automatically at the scheduled time.</Text>
        <PrimaryButton title="Add to Weekly Queue" icon="repeat" loading={scheduling} onPress={scheduleAuto} testID="seo-sched-auto" />
        <View style={styles.orRow}>
          <View style={styles.orLine} />
          <Text style={styles.orText}>or pick a specific time</Text>
          <View style={styles.orLine} />
        </View>
        {Platform.OS === "web" ? (
          <View style={{ gap: spacing.sm }}>
            <PrimaryButton title="Tomorrow, 9 AM" variant="outline" onPress={() => scheduleManual(preset(1))} testID="seo-sched-tomorrow" />
            <PrimaryButton title="In 3 days, 9 AM" variant="outline" onPress={() => scheduleManual(preset(3))} testID="seo-sched-3days" />
            <PrimaryButton title="Next week, 9 AM" variant="outline" onPress={() => scheduleManual(preset(7))} testID="seo-sched-nextweek" />
          </View>
        ) : (
          <>
            <Pressable style={styles.dateBtn} onPress={() => setShowPicker(true)} testID="seo-sched-pick">
              <Ionicons name="calendar-outline" size={18} color={colors.brand} />
              <Text style={styles.dateBtnText}>{fmtDate(pickDate.toISOString())}</Text>
            </Pressable>
            {showPicker ? (
              <DateTimePicker
                value={pickDate}
                mode="datetime"
                onChange={(e, d) => {
                  setShowPicker(Platform.OS === "ios");
                  if (d) setPickDate(d);
                }}
              />
            ) : null}
            <View style={{ height: spacing.sm }} />
            <PrimaryButton title="Schedule for this time" icon="checkmark" loading={scheduling} onPress={() => scheduleManual(pickDate)} testID="seo-sched-confirm" />
          </>
        )}
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  title: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, marginTop: spacing.sm },
  tagRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: spacing.md },
  tag: { backgroundColor: colors.brandTertiary, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  tagText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand },
  wordCount: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.sm },
  link: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand, flexShrink: 1 },
  actions: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.lg },
  schedCard: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginTop: spacing.md, backgroundColor: "#EEF2FF", borderColor: "#C7D2FE" },
  schedTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#3730A3" },
  schedWhen: { fontFamily: font.regular, fontSize: fontSize.sm, color: "#4338CA", marginTop: 2 },
  removeText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.error },
  sheetHint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginBottom: spacing.md },
  orRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginVertical: spacing.lg },
  orLine: { flex: 1, height: 1, backgroundColor: colors.border },
  orText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  dateBtn: { flexDirection: "row", alignItems: "center", gap: spacing.sm, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md, backgroundColor: colors.surface },
  dateBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  scoreRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  scoreLabel: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  scoreVal: { fontFamily: font.bold, fontSize: fontSize.xl },
  checkRow: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start", marginTop: spacing.sm },
  checkLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  checkDetail: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  suggTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginTop: spacing.md, marginBottom: 4 },
  suggItem: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 3 },
  bodyHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.xl, marginBottom: spacing.sm },
  bodyTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  copyBtn: { flexDirection: "row", alignItems: "center", gap: 4 },
  copyText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  body: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 22 },
  faqQ: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  faqA: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 4, lineHeight: 20 },
});
