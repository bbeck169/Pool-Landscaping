import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, Pressable, TextInput, RefreshControl, Alert, StyleSheet } from 'react-native';
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Card, PrimaryButton, StatusChip, EmptyState, Sheet } from '@/src/components/ui';

type Tab = "articles" | "keywords" | "queue" | "settings";

export default function SeoStudio() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("articles");
  const [refreshing, setRefreshing] = useState(false);

  // Articles
  const [articles, setArticles] = useState<any[]>([]);
  const [genOpen, setGenOpen] = useState(false);
  const [kw, setKw] = useState("");
  const [title, setTitle] = useState("");
  const [wordCount, setWordCount] = useState("800");
  const [generating, setGenerating] = useState(false);

  // Keywords
  const [seed, setSeed] = useState("");
  const [location, setLocation] = useState("Vistancia, Arizona");
  const [kwLoading, setKwLoading] = useState(false);
  const [kwResults, setKwResults] = useState<any[]>([]);

  // Settings
  const [wp, setWp] = useState<{ connected: boolean; url: string; username: string }>({
    connected: false,
    url: "",
    username: "",
  });
  const [wpUrl, setWpUrl] = useState("");
  const [wpUser, setWpUser] = useState("");
  const [wpPass, setWpPass] = useState("");
  const [wpSaving, setWpSaving] = useState(false);
  const [wpTesting, setWpTesting] = useState(false);

  // Queue / schedule
  const [schedule, setSchedule] = useState<any>({ enabled: true, paused: false, day_of_week: 0, hour: 9, minute: 0 });
  const [queued, setQueued] = useState<any[]>([]);

  const load = useCallback(async () => {
    try {
      const [a, s, q] = await Promise.all([
        api.get("/seo/articles"),
        api.get("/seo/wp-settings"),
        api.get("/seo/schedule"),
      ]);
      setArticles(a || []);
      setWp(s);
      setWpUrl(s.url || "");
      setWpUser(s.username || "");
      setSchedule(q.settings);
      setQueued(q.queued || []);
    } catch {}
    setRefreshing(false);
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const generate = async () => {
    if (!kw.trim()) return Alert.alert("Keyword required", "Enter a target keyword.");
    setGenerating(true);
    try {
      const art = await api.post("/seo/articles", {
        keyword: kw.trim(),
        title: title.trim() || undefined,
        word_count: parseInt(wordCount) || 800,
      });
      setGenOpen(false);
      setKw("");
      setTitle("");
      await load();
      router.push(`/seo/${art.id}`);
    } catch (e: any) {
      Alert.alert("Generation failed", e.message);
    } finally {
      setGenerating(false);
    }
  };

  const suggestKeywords = async () => {
    if (!seed.trim()) return Alert.alert("Topic required", "Enter a seed topic.");
    setKwLoading(true);
    try {
      const res = await api.post("/seo/keywords/suggest", { seed: seed.trim(), location });
      setKwResults(res.keywords || []);
    } catch (e: any) {
      Alert.alert("Failed", e.message);
    } finally {
      setKwLoading(false);
    }
  };

  const useKeyword = (k: string) => {
    setKw(k);
    setTab("articles");
    setGenOpen(true);
  };

  const saveWp = async () => {
    if (!wpUrl.trim() || !wpUser.trim() || !wpPass.trim())
      return Alert.alert("All fields required", "Enter site URL, username and application password.");
    setWpSaving(true);
    try {
      const s = await api.put("/seo/wp-settings", {
        url: wpUrl.trim(),
        username: wpUser.trim(),
        app_password: wpPass.trim(),
      });
      setWp({ connected: s.connected, url: s.url, username: s.username });
      setWpPass("");
      Alert.alert("Saved", "WordPress connection saved.");
    } catch (e: any) {
      Alert.alert("Save failed", e.message);
    } finally {
      setWpSaving(false);
    }
  };

  const testWp = async () => {
    setWpTesting(true);
    try {
      const r = await api.post("/seo/wp-settings/test");
      Alert.alert("Connected ✅", `Authenticated as ${r.name}.`);
    } catch (e: any) {
      Alert.alert("Connection failed", e.message);
    } finally {
      setWpTesting(false);
    }
  };

  const tabs: { key: Tab; label: string; icon: any }[] = [
    { key: "articles", label: "Articles", icon: "document-text-outline" },
    { key: "keywords", label: "Keywords", icon: "search-outline" },
    { key: "queue", label: "Queue", icon: "time-outline" },
    { key: "settings", label: "Connect", icon: "link-outline" },
  ];

  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  const saveSchedule = async (patch: any) => {
    const next = { ...schedule, ...patch };
    setSchedule(next);
    try {
      const s = await api.put("/seo/schedule", {
        enabled: next.enabled,
        paused: next.paused,
        day_of_week: next.day_of_week,
        hour: next.hour,
        minute: next.minute,
      });
      setSchedule(s);
    } catch (e: any) {
      Alert.alert("Failed", e.message);
    }
  };

  const removeFromQueue = async (aid: string) => {
    try {
      await api.post(`/seo/articles/${aid}/unschedule`, {});
      await load();
    } catch (e: any) {
      Alert.alert("Failed", e.message);
    }
  };

  const fmt = (iso?: string) =>
    iso ? new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";

  return (
    <View style={styles.root}>
      <Header title="SEO Studio" back subtitle="AI content & auto-publishing" />

      <View style={styles.segment}>
        {tabs.map((t) => {
          const active = tab === t.key;
          return (
            <Pressable
              key={t.key}
              onPress={() => setTab(t.key)}
              style={[styles.segBtn, active && styles.segBtnActive]}
              testID={`seo-tab-${t.key}`}
            >
              <Ionicons name={t.icon} size={16} color={active ? "#fff" : colors.onSurfaceSecondary} />
              <Text style={[styles.segText, { color: active ? "#fff" : colors.onSurfaceSecondary }]}>
                {t.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        keyboardShouldPersistTaps="handled"
      >
        {tab === "articles" && (
          <>
            <PrimaryButton title="Generate AI Article" icon="sparkles" onPress={() => setGenOpen(true)} testID="seo-generate-open" />
            <View style={{ height: spacing.lg }} />
            {articles.length === 0 ? (
              <EmptyState icon="document-text-outline" title="No articles yet" subtitle="Generate your first SEO article with AI." testID="seo-articles-empty" />
            ) : (
              articles.map((a) => (
                <Pressable key={a.id} onPress={() => router.push(`/seo/${a.id}`)} testID={`seo-article-${a.id}`}>
                  <Card style={styles.listCard}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.cardTitle} numberOfLines={2}>{a.title}</Text>
                      <Text style={styles.cardMeta}>🎯 {a.keyword} · {a.word_count || 0} words</Text>
                      {a.wp_link ? <Text style={styles.link} numberOfLines={1}>{a.wp_link}</Text> : null}
                    </View>
                    <StatusChip status={a.status || "draft"} />
                  </Card>
                </Pressable>
              ))
            )}
          </>
        )}

        {tab === "keywords" && (
          <>
            <Card>
              <Text style={styles.label}>Seed topic</Text>
              <TextInput style={styles.input} value={seed} onChangeText={setSeed} placeholder="e.g. pool cleaning" placeholderTextColor={colors.muted} testID="seo-seed" />
              <Text style={styles.label}>Location</Text>
              <TextInput style={styles.input} value={location} onChangeText={setLocation} placeholderTextColor={colors.muted} />
              <View style={{ height: spacing.sm }} />
              <PrimaryButton title="Suggest Keywords" icon="search" loading={kwLoading} onPress={suggestKeywords} testID="seo-suggest" />
            </Card>
            <View style={{ height: spacing.md }} />
            {kwResults.map((k, i) => (
              <Card key={i} style={styles.kwCard}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardTitle}>{k.keyword}</Text>
                  <Text style={styles.cardMeta}>
                    {k.intent} · ~{k.volume}/mo · KD {k.difficulty}
                  </Text>
                </View>
                <Pressable style={styles.useBtn} onPress={() => useKeyword(k.keyword)} testID={`seo-use-kw-${i}`}>
                  <Text style={styles.useBtnText}>Write</Text>
                </Pressable>
              </Card>
            ))}
          </>
        )}

        {tab === "queue" && (
          <>
            <Card>
              <View style={styles.wpStatusRow}>
                <Ionicons name="repeat-outline" size={20} color={colors.brand} />
                <Text style={styles.wpStatusText}>Weekly auto-drip · publishes as WordPress draft</Text>
              </View>
              <View style={styles.rowBetween}>
                <Text style={styles.label}>Auto-publishing</Text>
                <Pressable
                  onPress={() => saveSchedule({ paused: !schedule.paused })}
                  style={[styles.toggle, !schedule.paused && styles.toggleOn]}
                  testID="seo-schedule-toggle"
                >
                  <Text style={[styles.toggleText, { color: !schedule.paused ? "#fff" : colors.onSurfaceSecondary }]}>
                    {schedule.paused ? "Paused" : "Active"}
                  </Text>
                </Pressable>
              </View>
              <Text style={styles.label}>Publish day</Text>
              <View style={styles.dayRow}>
                {DAYS.map((d, i) => {
                  const active = schedule.day_of_week === i;
                  return (
                    <Pressable key={d} onPress={() => saveSchedule({ day_of_week: i })} style={[styles.dayChip, active && styles.dayChipActive]} testID={`seo-day-${i}`}>
                      <Text style={[styles.dayChipText, { color: active ? "#fff" : colors.onSurfaceSecondary }]}>{d}</Text>
                    </Pressable>
                  );
                })}
              </View>
              <Text style={styles.hint}>New items added to the weekly queue publish one per week on {DAYS[schedule.day_of_week]} at {String(schedule.hour).padStart(2, "0")}:00 UTC.</Text>
            </Card>
            <View style={{ height: spacing.md }} />
            <Text style={styles.queueHeading}>Upcoming ({queued.length})</Text>
            {queued.length === 0 ? (
              <EmptyState icon="time-outline" title="Queue is empty" subtitle="Schedule an article from its detail screen." testID="seo-queue-empty" />
            ) : (
              queued.map((a) => (
                <Card key={a.id} style={styles.listCard}>
                  <Pressable style={{ flex: 1 }} onPress={() => router.push(`/seo/${a.id}`)} testID={`seo-queued-${a.id}`}>
                    <Text style={styles.cardTitle} numberOfLines={2}>{a.title}</Text>
                    <Text style={styles.cardMeta}>🕒 {fmt(a.scheduled_for)}{a.queue_mode === "auto" ? " · weekly" : ""}</Text>
                  </Pressable>
                  <Pressable onPress={() => removeFromQueue(a.id)} hitSlop={8} testID={`seo-remove-${a.id}`}>
                    <Ionicons name="close-circle" size={22} color={colors.muted} />
                  </Pressable>
                </Card>
              ))
            )}
          </>
        )}

        {tab === "settings" && (
          <Card>
            <View style={styles.wpStatusRow}>
              <Ionicons name={wp.connected ? "checkmark-circle" : "alert-circle-outline"} size={20} color={wp.connected ? colors.success : colors.warning} />
              <Text style={styles.wpStatusText}>
                {wp.connected ? `Connected: ${wp.url}` : "Not connected"}
              </Text>
            </View>
            <Text style={styles.label}>WordPress site URL</Text>
            <TextInput style={styles.input} value={wpUrl} onChangeText={setWpUrl} autoCapitalize="none" keyboardType="url" placeholder="https://yoursite.com" placeholderTextColor={colors.muted} testID="wp-url" />
            <Text style={styles.label}>Username</Text>
            <TextInput style={styles.input} value={wpUser} onChangeText={setWpUser} autoCapitalize="none" placeholder="admin" placeholderTextColor={colors.muted} testID="wp-user" />
            <Text style={styles.label}>Application password</Text>
            <TextInput style={styles.input} value={wpPass} onChangeText={setWpPass} autoCapitalize="none" secureTextEntry placeholder={wp.connected ? "•••• (unchanged)" : "xxxx xxxx xxxx xxxx"} placeholderTextColor={colors.muted} testID="wp-pass" />
            <Text style={styles.hint}>Create one in WordPress → Users → Profile → Application Passwords.</Text>
            <View style={{ height: spacing.sm }} />
            <PrimaryButton title="Save Connection" icon="save-outline" loading={wpSaving} onPress={saveWp} testID="wp-save" />
            <View style={{ height: spacing.sm }} />
            <PrimaryButton title="Test Connection" variant="outline" loading={wpTesting} onPress={testWp} disabled={!wp.connected} testID="wp-test" />
          </Card>
        )}
      </ScrollView>

      <Sheet visible={genOpen} onClose={() => setGenOpen(false)} title="Generate AI Article" testID="seo-gen-sheet">
        <Text style={styles.label}>Target keyword</Text>
        <TextInput style={styles.input} value={kw} onChangeText={setKw} placeholder="e.g. weekly pool maintenance" placeholderTextColor={colors.muted} testID="seo-gen-kw" />
        <Text style={styles.label}>Working title (optional)</Text>
        <TextInput style={styles.input} value={title} onChangeText={setTitle} placeholder="Leave blank to auto-generate" placeholderTextColor={colors.muted} />
        <Text style={styles.label}>Word count</Text>
        <TextInput style={styles.input} value={wordCount} onChangeText={setWordCount} keyboardType="number-pad" placeholderTextColor={colors.muted} />
        <View style={{ height: spacing.md }} />
        <PrimaryButton title="Generate" icon="sparkles" loading={generating} onPress={generate} testID="seo-gen-submit" />
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  segment: {
    flexDirection: "row",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  segBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    height: 38,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  segBtnActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  segText: { fontFamily: font.semibold, fontSize: fontSize.sm },
  listCard: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md, marginBottom: spacing.md },
  kwCard: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginBottom: spacing.sm },
  cardTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  cardMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 3 },
  link: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.brand, marginTop: 3 },
  useBtn: { backgroundColor: colors.brandTertiary, paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.pill },
  useBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: spacing.sm, marginBottom: 4 },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 6 },
  wpStatusRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: spacing.sm },
  wpStatusText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.sm },
  toggle: { paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  toggleOn: { backgroundColor: colors.success, borderColor: colors.success },
  toggleText: { fontFamily: font.semibold, fontSize: fontSize.sm },
  dayRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  dayChip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: radius.pill, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  dayChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  dayChipText: { fontFamily: font.semibold, fontSize: fontSize.sm },
  queueHeading: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: spacing.sm },
});
