/**
 * Phase 4 · Batch B / D6 — Handbook section reader (mobile).
 * On 30-second read, auto-marks the matching read_handbook_section
 * onboarding task complete.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView } from "react-native";
import { useLocalSearchParams } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, fontSize, font } from '@/src/theme';
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

export default function HandbookSection() {
  const params = useLocalSearchParams<{ code?: string }>();
  const code = String(params.code || "");
  const [section, setSection] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setSection(await api.get(`/handbook/sections/${encodeURIComponent(code)}`));
    } catch (e: any) {
      setSection({ error: e?.message || "Failed to load." });
    } finally { setLoading(false); }
  }, [code]);

  useEffect(() => { if (code) load(); }, [code, load]);

  // 30-second read → auto-complete matching onboarding task.
  useEffect(() => {
    if (!section || section.error) return;
    const t = setTimeout(async () => {
      try {
        const tasks = await api.get("/onboarding/tasks");
        const match = (tasks?.rows || []).find(
          (x: any) => x.kind === "read_handbook_section" && x.related_ref === section.code);
        if (match) {
          await api.post("/onboarding/user-progress/mark-complete",
            { task_code: match.code, evidence: { source: "mobile_auto_read_30s" } });
        }
      } catch {}
    }, 30000);
    return () => clearTimeout(t);
  }, [section]);

  if (loading) return <Loading />;
  if (!section) return null;

  return (
    <View style={styles.container}>
      <Header title="Handbook" showBack />
      <ScrollView contentContainerStyle={styles.body}>
        {section.error ? (
          <Text style={styles.err}>{section.error}</Text>
        ) : (
          <>
            <Text style={styles.title} testID="mobile-handbook-title">{section.title}</Text>
            <Text style={styles.meta}>
              {section.is_system ? "System · read-only" : `Custom · v${section.version || 1}`}
            </Text>
            <Text style={styles.markdown} testID="mobile-handbook-body">{section.markdown_body}</Text>
          </>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  body: { padding: spacing.md },
  title: { color: colors.onSurface, fontFamily: font.bold, fontSize: fontSize.xxl, marginBottom: 4 },
  meta: { color: colors.muted, fontSize: fontSize.xs, marginBottom: spacing.md },
  markdown: { color: colors.onSurface, fontSize: fontSize.md, lineHeight: 22 },
  err: { color: colors.error, fontSize: fontSize.md, padding: spacing.md },
});
