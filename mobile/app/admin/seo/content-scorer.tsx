/** Phase 17A · Mobile — Content Scorer. */
import React, { useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Alert } from 'react-native';
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { AdminOnlyGate, ScoreChip, CenterLoader } from "./_shared";
import AppTextInput from "@/src/components/ui/AppTextInput";

export default function ContentScorerMobile() {
  return (
    <AdminOnlyGate title="Content Scorer">
      <Inner />
    </AdminOnlyGate>
  );
}

function Inner() {
  const [mode, setMode] = useState<"url" | "html">("url");
  const [urlOrHtml, setUrlOrHtml] = useState("https://");
  const [keyword, setKeyword] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);

  const analyze = async () => {
    if (!keyword.trim()) {
      Alert.alert("Missing keyword", "Enter a target keyword.");
      return;
    }
    setBusy(true); setResult(null);
    try {
      const body: any = { target_keyword: keyword };
      if (mode === "url") body.url = urlOrHtml;
      else body.html = urlOrHtml;
      const r = await api.post("/seo/content-score", body, 60000);
      setResult(r);
    } catch (e: any) {
      Alert.alert("Failed to score", e?.message || "Error");
    } finally { setBusy(false); }
  };

  const subScores: [string, number | null | undefined][] = result ? [
    ["Overall", result.score],
    ["Readability", result.sub_scores?.readability],
    ["Keyword", result.sub_scores?.keyword],
    ["Semantic", result.sub_scores?.semantic],
    ["Structure", result.sub_scores?.structure],
    ["Length", result.sub_scores?.length],
    ["Meta", result.sub_scores?.meta],
    ["Links", result.sub_scores?.links],
  ] : [];

  return (
    <View style={styles.root}>
      <Header title="Content Scorer" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 60 }}>
        <View style={styles.toggleRow}>
          {(["url", "html"] as const).map((m) => (
            <Pressable key={m}
                       style={[styles.toggleBtn,
                                mode === m && styles.toggleBtnActive]}
                       testID={`scorer-toggle-${m}`}
                       onPress={() => {
                         setMode(m);
                         setUrlOrHtml(m === "url" ? "https://" : "");
                       }}>
              <Text style={[styles.toggleText,
                             mode === m && styles.toggleTextActive]}>
                {m === "url" ? "URL" : "HTML"}
              </Text>
            </Pressable>
          ))}
        </View>

        <Text style={styles.label}>
          {mode === "url" ? "Page URL" : "Paste HTML"}
        </Text>
        <AppTextInput
          style={[styles.input, mode === "html" && { minHeight: 140,
                                                      textAlignVertical: "top" }]}
          value={urlOrHtml}
          multiline={mode === "html"}
          autoCapitalize="none"
          onChangeText={setUrlOrHtml}
          testID="scorer-input" />

        <Text style={styles.label}>Target keyword</Text>
        <AppTextInput style={styles.input} value={keyword}
                    autoCapitalize="none"
                    onChangeText={setKeyword}
                    testID="scorer-keyword" />

        <Pressable style={[styles.submit, busy && { opacity: 0.6 }]}
                    disabled={busy} onPress={analyze}
                    testID="scorer-analyze">
          <Ionicons name="analytics-outline" size={16} color="#fff" />
          <Text style={styles.submitText}>
            {busy ? "Analyzing…" : "Analyze"}
          </Text>
        </Pressable>

        {busy && <CenterLoader />}

        {result && (
          <View style={{ marginTop: spacing.xl }}>
            <View style={styles.overallCard}>
              <Text style={styles.overallLabel}>Overall</Text>
              <ScoreChip value={result.score} size="lg" />
              <Text style={styles.wordCount}>
                {result.word_count ?? 0} words ·{" "}
                {(result.readability ?? 0).toFixed(0)} Flesch
              </Text>
            </View>

            {subScores.slice(1).map(([label, v]) => (
              <View key={label} style={styles.bar}>
                <Text style={styles.barLabel}>{label}</Text>
                <View style={styles.barTrack}>
                  <View style={[styles.barFill,
                                 { width: `${Math.max(0, Math.min(100,
                                                                   (v as number) ?? 0))}%` }]} />
                </View>
                <Text style={styles.barValue}>{v ?? "—"}</Text>
              </View>
            ))}

            {result.recommendations?.length > 0 && (
              <View style={{ marginTop: spacing.lg }}>
                <Text style={styles.recTitle}>Recommendations</Text>
                {result.recommendations.map((rec: string, i: number) => (
                  <View key={i} style={styles.recRow}>
                    <Ionicons name="bulb-outline" size={14}
                               color={colors.brand} />
                    <Text style={styles.recText}>{rec}</Text>
                  </View>
                ))}
              </View>
            )}
          </View>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  toggleRow: { flexDirection: "row", gap: spacing.sm,
                marginBottom: spacing.lg },
  toggleBtn: {
    flex: 1, paddingVertical: 10, borderRadius: radius.md,
    backgroundColor: colors.surface, alignItems: "center",
    borderWidth: 1, borderColor: colors.border,
  },
  toggleBtnActive: { backgroundColor: colors.brand,
                      borderColor: colors.brand },
  toggleText: { fontFamily: font.semibold, fontSize: fontSize.sm,
                 color: colors.onSurface },
  toggleTextActive: { color: "#fff" },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm,
            color: colors.muted, marginTop: spacing.sm,
            marginBottom: spacing.xs },
  input: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    padding: spacing.md, fontFamily: font.regular,
    fontSize: fontSize.base, color: colors.onSurface,
    borderWidth: 1, borderColor: colors.border,
  },
  submit: {
    marginTop: spacing.lg, backgroundColor: colors.brand,
    borderRadius: radius.md, padding: spacing.md,
    alignItems: "center", flexDirection: "row",
    justifyContent: "center", gap: spacing.sm,
  },
  submitText: { fontFamily: font.bold, fontSize: fontSize.lg,
                 color: "#fff" },
  overallCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.lg, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", marginBottom: spacing.lg,
  },
  overallLabel: { fontFamily: font.semibold, fontSize: 10,
                   color: colors.muted, textTransform: "uppercase" },
  wordCount: { fontFamily: font.regular, fontSize: fontSize.sm,
                color: colors.muted, marginTop: 6 },
  bar: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  barLabel: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm,
               color: colors.onSurface },
  barTrack: {
    flex: 2, height: 8, backgroundColor: colors.surfaceSecondary,
    borderRadius: 4, overflow: "hidden",
  },
  barFill: { height: "100%", backgroundColor: colors.brand },
  barValue: { width: 34, textAlign: "right",
                fontFamily: font.bold, fontSize: fontSize.sm,
                color: colors.onSurface },
  recTitle: { fontFamily: font.bold, fontSize: fontSize.base,
               color: colors.onSurface, marginBottom: spacing.sm },
  recRow: {
    flexDirection: "row", gap: spacing.sm, padding: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  recText: { flex: 1, fontFamily: font.regular,
              fontSize: fontSize.sm, color: colors.onSurface },
});
