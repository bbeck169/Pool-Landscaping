/**
 * Phase 4 · Batch B / D6 — Mobile onboarding checklist (user view).
 * Admin dashboard remains web-only in this phase.
 * Deep-links: read_handbook_section → /handbook/[code]
 *             form_signature       → /templates (existing)
 *             training_module      → /training  (existing)
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, fontSize, font } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

const KIND_LABEL: Record<string, string> = {
  read_handbook_section: "Read Section",
  training_module: "Training Module",
  form_signature: "Fill / Sign Form",
  video_watch: "Watch Video",
  checklist: "Checklist",
};

function deepLink(t: any): string {
  const ref = t.related_ref || "";
  switch (t.kind) {
    case "read_handbook_section": return `/handbook/${ref}`;
    case "training_module":       return `/training?module=${ref}`;
    case "form_signature":        return `/templates`;
    default:                       return `/onboarding-checklist`;
  }
}

export default function OnboardingChecklist() {
  const [prog, setProg] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setProg(await api.get("/onboarding/user-progress?user_id=me")); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const markDone = async (code: string) => {
    setBusy(code);
    try {
      await api.post("/onboarding/user-progress/mark-complete", { task_code: code });
      await load();
    } finally { setBusy(null); }
  };

  if (loading) return <Loading />;
  if (!prog) return null;

  return (
    <View style={styles.container}>
      <Header title="Onboarding" />
      <ScrollView contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}>

        <View style={styles.summary} testID="mobile-onboarding-summary">
          <Text style={styles.summaryPct}>{prog.complete} / {prog.total}</Text>
          <Text style={styles.summaryLabel}>tasks · {Math.round(prog.pct)}%</Text>
          <View style={styles.progressTrack}>
            <View style={[styles.progressFill, { width: `${prog.pct}%` }]} />
          </View>
        </View>

        {prog.rows.map((t: any) => {
          const done = t.progress?.status === "complete";
          return (
            <View key={t.code} style={styles.row} testID={`mobile-onboarding-task-${t.code}`}>
              <Ionicons name={done ? "checkmark-circle" : "ellipse-outline"}
                size={22} color={done ? colors.success : colors.muted} />
              <View style={{ flex: 1 }}>
                <Text style={[styles.rowTitle, done && styles.rowTitleDone]}>{t.title}</Text>
                <Text style={styles.rowMeta}>{KIND_LABEL[t.kind] || t.kind}</Text>
              </View>
              {!done && (
                <View style={styles.rowActions}>
                  <Pressable style={styles.startBtn} onPress={() => router.push(deepLink(t) as any)}
                    testID={`mobile-onboarding-start-${t.code}`}>
                    <Text style={styles.startTxt}>Start</Text>
                  </Pressable>
                  <Pressable style={styles.doneBtn} disabled={busy === t.code}
                    onPress={() => markDone(t.code)}
                    testID={`mobile-onboarding-complete-${t.code}`}>
                    <Text style={styles.doneTxt}>{busy === t.code ? "…" : "Done"}</Text>
                  </Pressable>
                </View>
              )}
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  body: { padding: spacing.md, gap: spacing.sm },
  summary: {
    padding: spacing.md, borderRadius: radius.md, backgroundColor: colors.brand,
    marginBottom: spacing.md,
  },
  summaryPct: { color: "#fff", fontFamily: font.bold, fontSize: 28 },
  summaryLabel: { color: "#fff", opacity: 0.85, fontSize: fontSize.sm, marginBottom: 8 },
  progressTrack: { height: 6, backgroundColor: "rgba(255,255,255,0.25)", borderRadius: 3 },
  progressFill: { height: 6, backgroundColor: "#fff", borderRadius: 3 },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  rowTitle: { color: colors.onSurface, fontFamily: font.bold, fontSize: fontSize.md },
  rowTitleDone: { color: colors.muted, textDecorationLine: "line-through" },
  rowMeta: { color: colors.muted, fontSize: fontSize.xs, marginTop: 2 },
  rowActions: { gap: 4 },
  startBtn: {
    paddingHorizontal: spacing.sm, paddingVertical: 6, borderRadius: radius.sm,
    backgroundColor: colors.brandTertiary,
  },
  startTxt: { color: colors.brand, fontFamily: font.bold, fontSize: fontSize.xs },
  doneBtn: {
    paddingHorizontal: spacing.sm, paddingVertical: 6, borderRadius: radius.sm,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  doneTxt: { color: colors.onSurface, fontFamily: font.bold, fontSize: fontSize.xs },
});
