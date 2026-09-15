import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity, ActivityIndicator, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";

function scoreColor(s: number) {
  if (s >= 85) return "#16A34A";
  if (s >= 60) return "#EAB308";
  return "#B91C1C";
}

export default function WebsiteSeoPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const [url, setUrl] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const loadHistory = useCallback(async () => {
    try {
      const r = await api.get("/seo/scans?limit=10");
      setHistory(r?.scans || []);
    } catch {}
  }, []);

  useFocusEffect(useCallback(() => {
    if (!isAdmin) return;
    loadHistory();
    api.get("/tenants/business-card").then((c: any) => {
      if (c?.website_url && !url) setUrl(c.website_url);
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]));

  const run = async () => {
    if (!url.trim()) return;
    setRunning(true);
    try {
      const r = await api.post("/seo/analyze", { url: url.trim() });
      setResult(r);
      await loadHistory();
    } catch {}
    finally { setRunning(false); setRefreshing(false); }
  };

  if (!isAdmin) {
    return (
      <View style={s.root}>
        <Header title="Website SEO" back />
        <View style={s.center}>
          <Ionicons name="lock-closed" size={32} color={colors.muted} />
          <Text style={s.centerText}>Admin only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={s.root}>
      <Header title="Website SEO" subtitle="Analyze your site SEO score" back />
      <ScrollView
        testID="website-seo-page"
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); loadHistory().then(() => setRefreshing(false)); }} />
        }
      >
        {/* URL input + run */}
        <View style={s.inputRow}>
          <AppTextInput
            style={s.urlInput}
            value={url}
            onChangeText={setUrl}
            placeholder="https://yoursite.com"
            placeholderTextColor={colors.muted}
            autoCapitalize="none"
            keyboardType="url"
            testID="website-seo-url-input"
          />
          <TouchableOpacity
            style={[s.runBtn, (running || !url.trim()) && { opacity: 0.5 }]}
            onPress={run}
            disabled={running || !url.trim()}
            testID="website-seo-run-btn"
          >
            {running ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Ionicons name="search" size={18} color="#fff" />
            )}
          </TouchableOpacity>
        </View>

        {/* Latest result */}
        {result ? (
          <View style={s.scoreCard} testID="website-seo-result">
            <Text style={[s.scoreNum, { color: scoreColor(result.score || 0) }]}>
              {result.score || 0}
            </Text>
            <Text style={s.scoreLabel}>out of 100</Text>
            {(result.fixes || []).length > 0 ? (
              <View style={s.fixesList}>
                <Text style={s.fixesTitle}>{result.fixes.length} Fix{result.fixes.length === 1 ? "" : "es"}</Text>
                {result.fixes.map((f: any, i: number) => (
                  <View key={i} style={s.fixRow} testID={`website-seo-fix-${i}`}>
                    <Ionicons name="alert-circle" size={14} color="#EAB308" />
                    <Text style={s.fixText}>{f.title || f.issue || f}</Text>
                  </View>
                ))}
              </View>
            ) : null}
          </View>
        ) : null}

        {/* History */}
        {history.length > 0 ? (
          <View style={s.historyCard}>
            <Text style={s.historyTitle}>Recent Scans</Text>
            {history.map((h: any, i: number) => (
              <Pressable
                key={h.id || i}
                style={s.historyRow}
                onPress={() => setResult(h)}
                testID={`website-seo-history-${i}`}
              >
                <View style={[s.historyScore, { backgroundColor: scoreColor(h.score || 0) + "22" }]}>
                  <Text style={[s.historyScoreText, { color: scoreColor(h.score || 0) }]}>{h.score}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={s.historyUrl} numberOfLines={1}>{h.url}</Text>
                  <Text style={s.historyDate}>{new Date(h.created_at).toLocaleDateString()}</Text>
                </View>
              </Pressable>
            ))}
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  centerText: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.muted },
  inputRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.lg },
  urlInput: {
    flex: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.md,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
  },
  runBtn: {
    width: 48, height: 48, borderRadius: radius.md, backgroundColor: colors.brand,
    alignItems: "center", justifyContent: "center",
  },
  scoreCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl,
    borderWidth: 1, borderColor: colors.border, alignItems: "center", marginBottom: spacing.lg,
  },
  scoreNum: { fontFamily: font.bold, fontSize: 48 },
  scoreLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  fixesList: { width: "100%", marginTop: spacing.lg },
  fixesTitle: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface, marginBottom: spacing.sm },
  fixRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm, paddingVertical: 6 },
  fixText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, flex: 1, lineHeight: 18 },
  historyCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.border,
  },
  historyTitle: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.md },
  historyRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.sm },
  historyScore: { width: 40, height: 40, borderRadius: radius.sm, alignItems: "center", justifyContent: "center" },
  historyScoreText: { fontFamily: font.bold, fontSize: fontSize.lg },
  historyUrl: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  historyDate: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
});
