/**
 * Phase 56.13c · Training Mobile — Module detail screen.
 * Mirror of /tests/{code} on web. Markdown body rendered as plain
 * Text with light in-app styling (no extra deps).
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

type Lesson = { id: string; title: string; body_md: string; order: number };
type Module = {
  code: string; title: string; description?: string; disclaimer?: string;
  lessons: Lesson[]; quiz?: any;
  progress?: { lessons_completed?: string[] };
};

// Very lightweight markdown → Text mapping. Supports #, ##, paragraphs,
// bullet lists, and inline emphasis via naive replacement. Good enough
// for the CPO chapters without pulling in another dep.
function renderMarkdown(md: string) {
  const lines = (md || "").split(/\r?\n/);
  const out: React.ReactNode[] = [];
  let key = 0;
  for (const raw of lines) {
    const l = raw.trimEnd();
    if (!l) continue;
    if (l.startsWith("# ")) {
      out.push(<Text key={key++} style={styles.h1}>{l.slice(2)}</Text>); continue;
    }
    if (l.startsWith("## ")) {
      out.push(<Text key={key++} style={styles.h2}>{l.slice(3)}</Text>); continue;
    }
    if (l.startsWith("- ")) {
      out.push(<Text key={key++} style={styles.li}>•  {l.slice(2)}</Text>); continue;
    }
    if (l.startsWith("*") && l.endsWith("*") && l.length > 2) {
      out.push(<Text key={key++} style={styles.em}>{l.slice(1, -1)}</Text>); continue;
    }
    out.push(<Text key={key++} style={styles.p}>{l}</Text>);
  }
  return out;
}

export default function TrainingModuleDetail() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const router = useRouter();
  const [mod, setMod] = useState<Module | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const m = (await api.get(`/training/modules/${code}`)) as Module;
      setMod(m);
      if (!selectedId && m.lessons?.length) setSelectedId(m.lessons[0].id);
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Could not load");
    }
  }, [code, selectedId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const lessons = mod?.lessons || [];
  const completed = useMemo(
    () => new Set(mod?.progress?.lessons_completed || []),
    [mod]
  );
  const selected = lessons.find((l) => l.id === selectedId) || lessons[0] || null;
  const idx = lessons.findIndex((l) => l.id === selected?.id);
  const allDone = lessons.length > 0 && lessons.every((l) => completed.has(l.id));

  const markDone = useCallback(async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await api.post(`/training/modules/${code}/progress`, { lesson_id: selected.id });
      await load();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Failed");
    } finally {
      setBusy(false);
    }
  }, [code, selected, load]);

  if (!mod) return <View style={styles.root}><Header title="Loading…" /><Loading /></View>;

  return (
    <View style={styles.root}>
      <Header title={mod.title} onBack={() => router.back()} />
      {mod.disclaimer ? (
        <View style={styles.disclaimer} testID="training-module-disclaimer">
          <Text style={styles.disclaimerText}>{mod.disclaimer}</Text>
        </View>
      ) : null}

      <ScrollView horizontal style={styles.lessonStrip}
                  contentContainerStyle={{ padding: spacing.sm, gap: spacing.xs }}
                  showsHorizontalScrollIndicator={false}
                  testID="training-lesson-strip">
        {lessons.map((l) => {
          const done = completed.has(l.id);
          const active = l.id === selected?.id;
          return (
            <Pressable
              key={l.id}
              onPress={() => setSelectedId(l.id)}
              style={[styles.chip, active && styles.chipActive, done && styles.chipDone]}
              testID={`training-lesson-chip-${l.id}`}
            >
              <Ionicons name={done ? "checkmark-circle" : "ellipse-outline"}
                        size={12} color={done ? "#10B981" : colors.muted} />
              <Text style={[styles.chipText, active && { color: colors.brand, fontFamily: font.bold }]}>
                {String(l.order).padStart(2, "0")}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>

      <ScrollView style={styles.body}
                  contentContainerStyle={{ padding: spacing.md, paddingBottom: 100 }}
                  testID="training-lesson-body">
        {selected ? renderMarkdown(selected.body_md) : (
          <Text style={styles.p}>This module has no lessons.</Text>
        )}
      </ScrollView>

      <View style={styles.footer}>
        <Pressable
          disabled={idx <= 0}
          onPress={() => setSelectedId(lessons[idx - 1]?.id)}
          style={[styles.footBtn, { opacity: idx <= 0 ? 0.4 : 1 }]}
          testID="training-lesson-prev"
        >
          <Ionicons name="chevron-back" size={14} color={colors.onSurface} />
          <Text style={styles.footBtnText}>Prev</Text>
        </Pressable>
        <Pressable
          disabled={busy || (selected && completed.has(selected.id))}
          onPress={markDone}
          style={[styles.footBtnPrimary,
                  (selected && completed.has(selected.id)) && { backgroundColor: colors.muted }]}
          testID="training-lesson-mark-complete"
        >
          <Text style={styles.footBtnPrimaryText}>
            {selected && completed.has(selected.id) ? "Completed" : busy ? "…" : "Mark done"}
          </Text>
        </Pressable>
        <Pressable
          disabled={idx >= lessons.length - 1}
          onPress={() => setSelectedId(lessons[idx + 1]?.id)}
          style={[styles.footBtn, { opacity: idx >= lessons.length - 1 ? 0.4 : 1 }]}
          testID="training-lesson-next"
        >
          <Text style={styles.footBtnText}>Next</Text>
          <Ionicons name="chevron-forward" size={14} color={colors.onSurface} />
        </Pressable>
      </View>

      {allDone ? (
        <View style={styles.quizBanner} testID="training-take-quiz-banner">
          <Text style={styles.quizBannerText}>
            All lessons complete — ready to take the quiz.
          </Text>
          <Pressable
            style={styles.quizBtn}
            onPress={() => router.push(`/(app)/tests/${code}/quiz` as any)}
            testID="training-take-quiz-btn"
          >
            <Text style={styles.quizBtnText}>Take Quiz</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  disclaimer: {
    backgroundColor: "#FEF3C7", padding: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: "#FCD34D",
  },
  disclaimerText: { color: "#7C2D12", fontFamily: font.regular, fontSize: fontSize.xs },
  lessonStrip: { maxHeight: 44, backgroundColor: colors.surfaceAlt },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipActive: { borderColor: colors.brand },
  chipDone: { backgroundColor: "#F0FDF4" },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.xs, color: colors.onSurface },
  body: { flex: 1 },
  h1: { fontFamily: font.bold, fontSize: 20, color: colors.onSurface, marginBottom: 6 },
  h2: { fontFamily: font.bold, fontSize: 15, color: colors.onSurface, marginTop: 10, marginBottom: 4 },
  p: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, marginVertical: 3, lineHeight: 20 },
  li: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, marginVertical: 2, paddingLeft: 4 },
  em: { fontFamily: font.regular, fontStyle: "italic", fontSize: fontSize.sm, color: colors.muted, marginVertical: 3 },
  footer: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: spacing.md, borderTopWidth: 1, borderTopColor: colors.border,
    backgroundColor: colors.surface,
  },
  footBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 8, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
  },
  footBtnText: { fontFamily: font.bold, fontSize: fontSize.xs, color: colors.onSurface },
  footBtnPrimary: {
    backgroundColor: "#10B981", paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md,
  },
  footBtnPrimaryText: { fontFamily: font.bold, fontSize: fontSize.xs, color: "#fff" },
  quizBanner: {
    position: "absolute", bottom: 60, left: spacing.md, right: spacing.md,
    padding: spacing.md, borderRadius: radius.md, backgroundColor: "#ECFDF5",
    borderWidth: 1, borderColor: "#10B981",
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
  },
  quizBannerText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#065F46", flex: 1 },
  quizBtn: {
    backgroundColor: "#10B981", paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md,
  },
  quizBtnText: { fontFamily: font.bold, fontSize: fontSize.xs, color: "#fff" },
});
