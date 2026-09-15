/** Phase 17B · Mobile — LLM Visibility: Queries tab + Dashboard tab. */
import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, Alert, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { showConfirm } from "@/src/components/ConfirmModal";
import { AdminOnlyGate, BrandPill, CenterLoader } from "./_shared";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Tab = "queries" | "dashboard";

export default function LlmVisibilityMobile() {
  return (
    <AdminOnlyGate title="LLM Visibility">
      <Inner />
    </AdminOnlyGate>
  );
}

function Inner() {
  const [tab, setTab] = useState<Tab>("queries");
  const [queries, setQueries] = useState<any[]>([]);
  const [dash, setDash] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [qText, setQText] = useState("");
  const [brand, setBrand] = useState("");
  const [category, setCategory] = useState("general");
  const [scanning, setScanning] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [qs, d] = await Promise.all([
        api.get("/seo/llm-visibility/queries"),
        api.get("/seo/llm-visibility/dashboard?range=30d"),
      ]);
      setQueries(Array.isArray(qs) ? qs : (qs.items || []));
      setDash(d);
    } finally { setLoading(false); }
  };
  useFocusEffect(useCallback(() => { load(); }, []));

  const add = async () => {
    if (!qText.trim() || !brand.trim()) {
      Alert.alert("Missing fields",
                   "Enter both query text and expected brand.");
      return;
    }
    try {
      await api.post("/seo/llm-visibility/queries", {
        query_text: qText, expected_brand: brand, category,
      });
      setShowNew(false); setQText(""); setBrand("");
      await load();
    } catch (e: any) {
      Alert.alert("Failed to add", e?.message || "Error");
    }
  };

  const del = async (qid: string) => {
    showConfirm({
      title: "Delete query",
      message: "This cannot be undone.",
      confirmLabel: "Delete",
      confirmStyle: "destructive",
      onConfirm: async () => {
        await api.del(`/seo/llm-visibility/queries/${qid}`);
        await load();
      },
    });
  };

  const runScan = async () => {
    if (queries.length === 0) {
      Alert.alert("No queries", "Add at least one query first.");
      return;
    }
    setScanning(true);
    try {
      const r = await api.post("/seo/llm-visibility/scan",
                                 { query_ids: queries.map((q) => q.id) },
                                 180000);
      Alert.alert("Scan complete",
                   `${r.results?.length || 0} results ·` +
                   ` engines: ${(r.engines_configured || []).join(", ") || "none"}`);
      await load();
    } catch (e: any) {
      Alert.alert("Scan failed", e?.message || "Error");
    } finally { setScanning(false); }
  };

  return (
    <View style={styles.root}>
      <Header title="LLM Visibility" />
      <View style={styles.tabRow}>
        {(["queries", "dashboard"] as Tab[]).map((t) => (
          <Pressable key={t}
                     style={[styles.tab, tab === t && styles.tabActive]}
                     onPress={() => setTab(t)}
                     testID={`llm-tab-${t}`}>
            <Text style={[styles.tabText,
                           tab === t && styles.tabTextActive]}>
              {t === "queries" ? "Queries" : "Dashboard"}
            </Text>
          </Pressable>
        ))}
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 60 }}>
        {loading && <CenterLoader />}

        {!loading && tab === "queries" && (
          <>
            <View style={styles.actionRow}>
              <Pressable style={styles.actionBtn}
                          onPress={() => setShowNew(true)}
                          testID="llm-add-query-btn">
                <Ionicons name="add" size={16} color="#fff" />
                <Text style={styles.actionBtnText}>Add query</Text>
              </Pressable>
              <Pressable style={[styles.actionBtnSecondary,
                                    scanning && { opacity: 0.6 }]}
                          disabled={scanning}
                          onPress={runScan}
                          testID="llm-scan-btn">
                {scanning ? <ActivityIndicator color={colors.brand} /> : (
                  <>
                    <Ionicons name="search" size={16} color={colors.brand} />
                    <Text style={styles.actionBtnSecondaryText}>
                      Run scan
                    </Text>
                  </>
                )}
              </Pressable>
            </View>

            {showNew && (
              <View style={styles.newQueryBox}>
                <Text style={styles.label}>Query text</Text>
                <AppTextInput style={styles.input} value={qText}
                            onChangeText={setQText}
                            testID="llm-new-text" />
                <Text style={styles.label}>Expected brand</Text>
                <AppTextInput style={styles.input} value={brand}
                            onChangeText={setBrand}
                            testID="llm-new-brand" />
                <Text style={styles.label}>Category</Text>
                <AppTextInput style={styles.input} value={category}
                            onChangeText={setCategory}
                            testID="llm-new-category" />
                <View style={{ flexDirection: "row", gap: spacing.sm,
                                marginTop: spacing.sm }}>
                  <Pressable style={styles.submitBtn}
                              onPress={add}
                              testID="llm-new-submit">
                    <Text style={styles.submitBtnText}>Add</Text>
                  </Pressable>
                  <Pressable style={styles.cancelBtn}
                              onPress={() => setShowNew(false)}>
                    <Text style={styles.cancelBtnText}>Cancel</Text>
                  </Pressable>
                </View>
              </View>
            )}

            {queries.length === 0 ? (
              <Text style={styles.empty}>
                No tracked queries yet. Add one to start scanning.
              </Text>
            ) : (
              queries.map((q) => (
                <View key={q.id} style={styles.queryRow}>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text style={styles.queryText} numberOfLines={2}>
                      {q.query_text}
                    </Text>
                    <Text style={styles.queryMeta}>
                      Brand: {q.expected_brand} · {q.category}
                    </Text>
                  </View>
                  <Pressable onPress={() => del(q.id)}
                              testID={`llm-delete-${q.id}`}
                              style={styles.iconBtn}>
                    <Ionicons name="trash-outline" size={16}
                               color={colors.error} />
                  </Pressable>
                </View>
              ))
            )}
          </>
        )}

        {!loading && tab === "dashboard" && dash && (
          <>
            <View style={styles.kpiRow}>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>Mention rate</Text>
                <Text style={styles.kpiValue}>
                  {(dash.mention_rate_pct ?? 0).toFixed(1)}%
                </Text>
              </View>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>Avg position</Text>
                <Text style={styles.kpiValue}>
                  {dash.avg_position ?? "—"}
                </Text>
              </View>
              <View style={styles.kpiCard}>
                <Text style={styles.kpiLabel}>Total scans</Text>
                <Text style={styles.kpiValue}>
                  {dash.total_scans ?? 0}
                </Text>
              </View>
            </View>

            <Text style={styles.sectionTitle}>Engines</Text>
            <View style={styles.enginesRow}>
              {["claude", "openai", "gemini", "perplexity"].map((eng) => {
                const on = (dash.engines_configured || []).includes(eng);
                return (
                  <View key={eng} style={[styles.engine,
                                            on ? styles.engineOn
                                                : styles.engineOff]}>
                    <Text style={[styles.engineText,
                                    { color: on ? "#166534" : colors.muted }]}>
                      {eng}
                    </Text>
                    {!on && (
                      <Text style={styles.engineNote}>not configured</Text>
                    )}
                  </View>
                );
              })}
            </View>

            <Text style={styles.sectionTitle}>Top competitors</Text>
            {(dash.competitors || []).length === 0 ? (
              <Text style={styles.empty}>No competitor mentions yet.</Text>
            ) : (
              (dash.competitors || []).slice(0, 10).map(
                (c: any, i: number) => (
                  <View key={i} style={styles.compRow}>
                    <Text style={styles.compRank}>#{i + 1}</Text>
                    <Text style={styles.compName}
                           numberOfLines={1}>{c.name}</Text>
                    <BrandPill text={`${c.mentions}x`} tone="brand" />
                  </View>
                )
              )
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  tabRow: {
    flexDirection: "row", gap: spacing.sm,
    padding: spacing.lg, paddingBottom: 0,
  },
  tab: {
    flex: 1, paddingVertical: 10, borderRadius: radius.md,
    backgroundColor: colors.surface, alignItems: "center",
    borderWidth: 1, borderColor: colors.border,
  },
  tabActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  tabText: { fontFamily: font.semibold, fontSize: fontSize.sm,
              color: colors.onSurface },
  tabTextActive: { color: "#fff" },
  actionRow: { flexDirection: "row", gap: spacing.sm,
                marginBottom: spacing.md },
  actionBtn: {
    flex: 1, flexDirection: "row", alignItems: "center",
    justifyContent: "center", gap: 6,
    backgroundColor: colors.brand, borderRadius: radius.md,
    paddingVertical: 10,
  },
  actionBtnText: { fontFamily: font.bold, fontSize: fontSize.sm,
                    color: "#fff" },
  actionBtnSecondary: {
    flex: 1, flexDirection: "row", alignItems: "center",
    justifyContent: "center", gap: 6,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.brand,
    borderRadius: radius.md, paddingVertical: 10,
  },
  actionBtnSecondaryText: { fontFamily: font.bold,
                             fontSize: fontSize.sm, color: colors.brand },
  newQueryBox: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, marginBottom: spacing.md,
  },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm,
            color: colors.muted, marginTop: spacing.sm,
            marginBottom: spacing.xs },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, padding: spacing.md,
    fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface, borderWidth: 1,
    borderColor: colors.border,
  },
  submitBtn: {
    flex: 1, backgroundColor: colors.brand,
    borderRadius: radius.md, padding: spacing.md,
    alignItems: "center",
  },
  submitBtnText: { fontFamily: font.bold, fontSize: fontSize.base,
                    color: "#fff" },
  cancelBtn: {
    flex: 1, backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, padding: spacing.md,
    alignItems: "center",
  },
  cancelBtnText: { fontFamily: font.semibold, fontSize: fontSize.base,
                    color: colors.onSurface },
  queryRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    padding: spacing.md, backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  queryText: { fontFamily: font.bold, fontSize: fontSize.base,
                color: colors.onSurface },
  queryMeta: { fontFamily: font.regular, fontSize: fontSize.sm,
                color: colors.muted, marginTop: 2 },
  iconBtn: { padding: spacing.sm },
  empty: { fontFamily: font.regular, fontSize: fontSize.base,
            color: colors.muted, textAlign: "center",
            padding: spacing.lg },
  kpiRow: { flexDirection: "row", gap: spacing.sm,
             marginBottom: spacing.lg },
  kpiCard: {
    flex: 1, backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    alignItems: "center",
  },
  kpiLabel: { fontFamily: font.semibold, fontSize: 10,
               color: colors.muted, textTransform: "uppercase" },
  kpiValue: { fontFamily: font.bold, fontSize: fontSize["2xl"],
               color: colors.onSurface, marginTop: 4 },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.base,
                   color: colors.onSurface, marginBottom: spacing.sm,
                   marginTop: spacing.md },
  enginesRow: { flexDirection: "row", flexWrap: "wrap",
                 gap: spacing.sm, marginBottom: spacing.md },
  engine: {
    paddingHorizontal: spacing.md, paddingVertical: 6,
    borderRadius: 999, borderWidth: 1, alignItems: "center",
  },
  engineOn: { backgroundColor: "#DCFCE7", borderColor: "#86EFAC" },
  engineOff: { backgroundColor: colors.surface,
                borderColor: colors.border },
  engineText: { fontFamily: font.bold, fontSize: fontSize.sm },
  engineNote: { fontFamily: font.regular, fontSize: 9,
                 color: colors.muted, marginTop: 2 },
  compRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    padding: spacing.md, backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  compRank: { fontFamily: font.bold, fontSize: fontSize.lg,
               color: colors.brand, width: 32 },
  compName: { flex: 1, fontFamily: font.semibold,
               fontSize: fontSize.base, color: colors.onSurface },
});
