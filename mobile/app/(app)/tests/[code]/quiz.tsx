/**
 * Phase 56.13c · Training Mobile — Quiz runner + results screen.
 * Mirror of /tests/{code}/quiz on web. Cert PDF opens via Linking.
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, Linking, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import Constants from "expo-constants";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

type Choice = { id: string; text: string };
type Question = { id: string; prompt: string; choices: Choice[] };

const BACKEND_URL: string =
  (Constants.expoConfig?.extra as any)?.EXPO_PUBLIC_BACKEND_URL
  || (process.env.EXPO_PUBLIC_BACKEND_URL as string)
  || "";

export default function TrainingQuiz() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const router = useRouter();
  const [mod, setMod] = useState<any>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [idx, setIdx] = useState(0);
  const [result, setResult] = useState<any>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      const m = await api.get(`/training/modules/${code}`);
      setMod(m);
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Could not load quiz");
    }
  }, [code]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const questions: Question[] = useMemo(
    () => mod?.quiz?.questions || [],
    [mod?.quiz?.questions],
  );
  const q = questions[idx];
  const totalQ = questions.length;
  const chosen = q ? answers[q.id] : null;
  const allAnswered = useMemo(
    () => totalQ > 0 && questions.every((qq) => !!answers[qq.id]),
    [questions, answers, totalQ]
  );

  const submit = useCallback(async () => {
    setSubmitting(true);
    try {
      const r = await api.post(`/training/modules/${code}/quiz`, { answers });
      setResult(r);
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Submit failed");
    } finally {
      setSubmitting(false);
    }
  }, [code, answers]);

  const retake = useCallback(() => {
    setResult(null); setAnswers({}); setIdx(0);
  }, []);

  const downloadPdf = useCallback(() => {
    if (!result?.certificate_id || !BACKEND_URL) return;
    Linking.openURL(`${BACKEND_URL}/api/training/certificates/${result.certificate_id}/pdf`);
  }, [result?.certificate_id]);

  if (!mod) return <View style={styles.root}><Header title="Loading…" /><Loading /></View>;

  // ── Results screen ──
  if (result) {
    const passed = !!result.passed;
    return (
      <View style={styles.root}>
        <Header title="Quiz Results" onBack={() => router.replace(`/(app)/tests/${code}` as any)} />
        <ScrollView contentContainerStyle={{ padding: spacing.md }} testID="training-quiz-results">
          <View style={[styles.scoreCard, passed ? styles.scoreCardPass : styles.scoreCardFail]}
                testID="training-quiz-score-banner">
            <View>
              <Text style={[styles.scoreValue, { color: passed ? "#065F46" : "#7F1D1D" }]}
                    testID="training-quiz-score-value">
                {Math.round((result.score || 0) * 100)}%
              </Text>
              <Text style={styles.scoreMeta}>
                {result.correct} of {result.total} correct · passing = {Math.round((result.passing_score || 0.75) * 100)}%
              </Text>
            </View>
            <View style={[styles.passfailPill, { backgroundColor: passed ? "#10B981" : "#DC2626" }]}
                  testID="training-quiz-passfail">
              <Text style={styles.passfailText}>{passed ? "PASS" : "FAIL"}</Text>
            </View>
          </View>

          {passed && result.certificate_id ? (
            <View style={styles.certCard} testID="training-quiz-certificate-block">
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 }}>
                <Ionicons name="ribbon-outline" size={18} color="#10B981" />
                <Text style={styles.certTitle}>Certificate awarded — {result.certificate_id}</Text>
              </View>
              <Pressable style={styles.pdfBtn} onPress={downloadPdf}
                         testID="training-quiz-cert-pdf-btn">
                <Ionicons name="download-outline" size={14} color="#fff" />
                <Text style={styles.pdfBtnText}>Download Certificate PDF</Text>
              </Pressable>
              <Text style={styles.certDisclaimer}>{mod.disclaimer}</Text>
            </View>
          ) : null}

          <View style={styles.reviewCard} testID="training-quiz-review">
            <Text style={styles.reviewHeader}>Your answers</Text>
            {questions.map((qq, i) => {
              const my = answers[qq.id];
              return (
                <View key={qq.id} style={styles.reviewRow}
                      testID={`training-quiz-review-q-${qq.id}`}>
                  <Text style={styles.reviewPrompt}>Q{i + 1}. {qq.prompt}</Text>
                  {qq.choices.map((c) => (
                    <Text key={c.id} style={[styles.reviewChoice,
                        my === c.id && { color: colors.onSurface, fontFamily: font.bold }]}>
                      {my === c.id ? "→ " : "   "}{c.text}
                      {my === c.id ? "  (your answer)" : ""}
                    </Text>
                  ))}
                </View>
              );
            })}
          </View>

          <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.md }}>
            <Pressable style={styles.retakeBtn} onPress={retake}
                       testID="training-quiz-retake-btn">
              <Ionicons name="refresh" size={14} color="#fff" />
              <Text style={styles.retakeBtnText}>Retake Quiz</Text>
            </Pressable>
            <Pressable style={styles.backBtn}
                       onPress={() => router.replace(`/(app)/tests/${code}` as any)}>
              <Text style={styles.backBtnText}>Back to Module</Text>
            </Pressable>
          </View>
        </ScrollView>
      </View>
    );
  }

  // ── Runner screen ──
  return (
    <View style={styles.root}>
      <Header title={`${mod.title} — Quiz`} onBack={() => router.back()} />
      <ScrollView contentContainerStyle={{ padding: spacing.md }} testID="training-quiz-runner">
        {questions.length === 0 ? (
          <Text style={styles.emptyText}>This module has no quiz.</Text>
        ) : (
          <>
            <Text style={styles.counter}>Question {idx + 1} of {totalQ}</Text>
            <View style={styles.qCard}>
              <Text style={styles.qPrompt} testID={`training-quiz-question-${q.id}`}>
                {q.prompt}
              </Text>
              {q.choices.map((c) => {
                const active = chosen === c.id;
                return (
                  <Pressable
                    key={c.id}
                    onPress={() => setAnswers((s) => ({ ...s, [q.id]: c.id }))}
                    style={[styles.choice, active && styles.choiceActive]}
                    testID={`training-quiz-choice-${q.id}-${c.id}`}
                  >
                    <Text style={styles.choiceText}>{c.text}</Text>
                  </Pressable>
                );
              })}
            </View>

            <View style={styles.qNav}>
              <Pressable
                disabled={idx <= 0}
                onPress={() => setIdx(idx - 1)}
                style={[styles.navBtn, { opacity: idx <= 0 ? 0.4 : 1 }]}
                testID="training-quiz-prev"
              >
                <Text style={styles.navBtnText}>← Prev</Text>
              </Pressable>
              {idx < totalQ - 1 ? (
                <Pressable
                  onPress={() => setIdx(idx + 1)}
                  style={[styles.navBtn, { backgroundColor: colors.brand, borderColor: colors.brand }]}
                  testID="training-quiz-next"
                >
                  <Text style={[styles.navBtnText, { color: "#fff" }]}>Next →</Text>
                </Pressable>
              ) : (
                <Pressable
                  disabled={submitting || !allAnswered}
                  onPress={submit}
                  style={[styles.navBtn,
                    { backgroundColor: allAnswered ? "#10B981" : colors.muted,
                      borderColor: allAnswered ? "#10B981" : colors.muted }]}
                  testID="training-quiz-submit"
                >
                  <Text style={[styles.navBtnText, { color: "#fff" }]}>
                    {submitting ? "…" : allAnswered ? "Submit Quiz" : `Answer all ${totalQ}`}
                  </Text>
                </Pressable>
              )}
            </View>
          </>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  emptyText: { color: colors.muted, fontFamily: font.regular, fontSize: fontSize.sm },
  counter: { color: colors.muted, fontFamily: font.bold, fontSize: fontSize.xs, marginBottom: spacing.sm },
  qCard: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, padding: spacing.md,
  },
  qPrompt: { color: colors.onSurface, fontFamily: font.bold, fontSize: fontSize.base, marginBottom: spacing.sm },
  choice: {
    borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.sm, marginBottom: spacing.xs, backgroundColor: colors.surfaceAlt,
  },
  choiceActive: { borderColor: colors.brand, backgroundColor: "#EFF6FF" },
  choiceText: { color: colors.onSurface, fontFamily: font.regular, fontSize: fontSize.base },
  qNav: {
    flexDirection: "row", justifyContent: "space-between", marginTop: spacing.md,
  },
  navBtn: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 14, paddingVertical: 10,
  },
  navBtnText: { fontFamily: font.bold, fontSize: fontSize.xs, color: colors.onSurface },

  scoreCard: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
  },
  scoreCardPass: { backgroundColor: "#ECFDF5", borderColor: "#10B981" },
  scoreCardFail: { backgroundColor: "#FEF2F2", borderColor: "#DC2626" },
  scoreValue: { fontFamily: font.bold, fontSize: 28 },
  scoreMeta: { color: colors.muted, fontFamily: font.regular, fontSize: fontSize.xs },
  passfailPill: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md },
  passfailText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },

  certCard: {
    backgroundColor: colors.surface, borderColor: "#10B981",
    borderWidth: 1, borderRadius: radius.md, padding: spacing.md, marginTop: spacing.md,
  },
  certTitle: { color: "#065F46", fontFamily: font.bold, fontSize: fontSize.sm },
  pdfBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start",
    backgroundColor: "#10B981", paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md,
  },
  pdfBtnText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.xs },
  certDisclaimer: { color: colors.muted, fontFamily: font.regular, fontSize: fontSize.xs, marginTop: spacing.sm },

  reviewCard: {
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, marginTop: spacing.md, padding: spacing.sm,
  },
  reviewHeader: { color: colors.muted, fontFamily: font.bold, fontSize: fontSize.xs, marginBottom: spacing.xs },
  reviewRow: { paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: colors.border },
  reviewPrompt: { color: colors.onSurface, fontFamily: font.bold, fontSize: fontSize.xs, marginBottom: 2 },
  reviewChoice: { color: colors.muted, fontFamily: font.regular, fontSize: fontSize.xs },

  retakeBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4,
    backgroundColor: colors.brand, paddingVertical: 10, borderRadius: radius.md,
  },
  retakeBtnText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.xs },
  backBtn: {
    flex: 1, alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingVertical: 10,
  },
  backBtnText: { color: colors.onSurface, fontFamily: font.bold, fontSize: fontSize.xs },
});
