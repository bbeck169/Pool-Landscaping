/**
 * Phase 20B mobile A.4 · Employee onboarding checklist.
 * Any authenticated user can access; renders only their own assignments.
 */
import React, { useCallback, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, RefreshControl, Modal, Alert } from 'react-native';
import { Ionicons } from "@expo/vector-icons";
import { WebView } from "react-native-webview";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

export default function MyOnboarding() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [openStep, setOpenStep] = useState<{ a: any; step: any } | null>(null);

  const load = useCallback(async () => {
    try { setRows(await api.get("/onboarding/assignments/mine")); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const complete = async (a: any, sid: string) => {
    await api.post(
      `/onboarding/assignments/${a.id}/steps/${sid}/complete`,
      {},
    );
    setOpenStep(null); load();
  };

  const submitQuiz = async (a: any, step: any, answers: number[]) => {
    try {
      const r = await api.post(
        `/onboarding/assignments/${a.id}/steps/${step.id}/quiz`,
        { answers },
      );
      Alert.alert(r.passed ? "Passed" : "Try again",
                  `Score: ${r.score}%`);
      setOpenStep(null); load();
    } catch (e: any) { Alert.alert("Quiz failed", e?.message || ""); }
  };

  if (loading) return (
    <View style={styles.root}>
      <Header title="My Onboarding" />
      <Loading />
    </View>
  );

  if (rows.length === 0) return (
    <View style={styles.root}>
      <Header title="My Onboarding" />
      <View style={styles.empty}>
        <Ionicons name="clipboard-outline" size={40} color={colors.muted} />
        <Text style={styles.emptyText}>
          No active onboarding assignments. If you&apos;re new, ask your admin.
        </Text>
      </View>
    </View>
  );

  return (
    <View style={styles.root}>
      <Header title="My Onboarding" subtitle="Complete every step to activate" />
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: 120 }}
        refreshControl={
          <RefreshControl refreshing={refreshing}
                          onRefresh={() => { setRefreshing(true); load(); }} />}
      >
        {rows.map((a) => {
          const steps = a.template_snapshot?.steps || [];
          const done = Object.values(a.step_progress || {})
            .filter((s: any) => s.completed_at).length;
          const pct = steps.length ? Math.round(100 * done / steps.length) : 0;
          return (
            <View key={a.id} style={styles.card}>
              <View style={styles.cardHead}>
                <View>
                  <Text style={styles.cardTitle}>
                    {a.template_snapshot?.title}
                  </Text>
                  <Text style={styles.cardMeta}>
                    {done}/{steps.length} · {pct}% complete
                  </Text>
                </View>
                <View style={styles.ring}>
                  <Text style={styles.ringText}>{pct}%</Text>
                </View>
              </View>
              <View style={styles.progressBar}>
                <View style={[styles.progressFill, { width: `${pct}%` }]} />
              </View>
              {steps.map((s: any, i: number) => {
                const sp = (a.step_progress || {})[s.id] || {};
                const isDone = !!sp.completed_at;
                return (
                  <Pressable key={s.id}
                             onPress={() => !isDone && setOpenStep({ a, step: s })}
                             style={[styles.step,
                                     isDone ? styles.stepDone : null]}
                             testID={`onb-step-${i}`}>
                    <Ionicons
                      name={isDone ? "checkmark-circle" : "ellipse-outline"}
                      size={22}
                      color={isDone ? "#059669" : colors.muted}
                    />
                    <View style={{ flex: 1 }}>
                      <Text style={[styles.stepTitle,
                                    isDone ? { color: "#065F46" } : null]}>
                        {s.title}
                      </Text>
                      <Text style={styles.stepMeta}>
                        {s.kind}{s.description ? ` · ${s.description}` : ""}
                      </Text>
                    </View>
                    {!isDone && (
                      <Ionicons name="chevron-forward" size={16}
                                color={colors.muted} />
                    )}
                  </Pressable>
                );
              })}
            </View>
          );
        })}
      </ScrollView>

      <StepSheet open={openStep} onClose={() => setOpenStep(null)}
                 onComplete={complete} onQuiz={submitQuiz} />
    </View>
  );
}

function StepSheet({ open, onClose, onComplete, onQuiz }: {
  open: { a: any; step: any } | null;
  onClose: () => void;
  onComplete: (a: any, sid: string) => Promise<void>;
  onQuiz: (a: any, step: any, answers: number[]) => Promise<void>;
}) {
  const [answers, setAnswers] = useState<number[]>([]);
  React.useEffect(() => { setAnswers([]); }, [open?.step?.id]);
  if (!open) return null;
  const { a, step } = open;

  const setAns = (qi: number, ai: number) => {
    const next = [...answers]; next[qi] = ai; setAnswers(next);
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetBg}>
        <View style={styles.sheet}>
          <View style={styles.sheetHead}>
            <Text style={styles.sheetTitle} numberOfLines={2}>{step.title}</Text>
            <Pressable onPress={onClose}>
              <Ionicons name="close" size={22} color={colors.muted} />
            </Pressable>
          </View>
          <Text style={styles.sheetDesc}>{step.description || ""}</Text>

          {step.kind === "task" || step.kind === "policy_ack" ? (
            <Pressable style={styles.doneBtn}
                       onPress={() => onComplete(a, step.id)}
                       testID="onb-mark-complete">
              <Text style={styles.doneBtnText}>
                {step.kind === "policy_ack" ? "I acknowledge" : "Mark complete"}
              </Text>
            </Pressable>
          ) : null}

          {step.kind === "video" && step.resource_url ? (
            <View style={{ marginTop: spacing.md }}>
              <View style={{ height: 220, borderRadius: radius.md,
                              overflow: "hidden",
                              borderWidth: 1, borderColor: colors.border }}>
                <WebView source={{ uri: step.resource_url }} />
              </View>
              <Pressable style={styles.doneBtn}
                         onPress={() => onComplete(a, step.id)}
                         testID="onb-mark-watched">
                <Text style={styles.doneBtnText}>Mark watched</Text>
              </Pressable>
            </View>
          ) : null}

          {step.kind === "doc_upload" ? (
            <View>
              <Text style={styles.sheetDesc}>
                Upload via Files, then tap &quot;Mark complete&quot; once submitted.
              </Text>
              <Pressable style={styles.doneBtn}
                         onPress={() => onComplete(a, step.id)}
                         testID="onb-doc-complete">
                <Text style={styles.doneBtnText}>Mark complete</Text>
              </Pressable>
            </View>
          ) : null}

          {step.kind === "quiz" && (step.quiz_questions || []).length > 0 ? (
            <ScrollView style={{ maxHeight: 400 }}>
              {(step.quiz_questions || []).map((q: any, qi: number) => (
                <View key={qi} style={{ marginTop: spacing.md }}>
                  <Text style={styles.qText}>{qi + 1}. {q.q}</Text>
                  {(q.choices || []).map((c: string, ai: number) => (
                    <Pressable key={ai} onPress={() => setAns(qi, ai)}
                               style={[styles.qChoice,
                                       answers[qi] === ai ? styles.qChoiceActive : null]}
                               testID={`onb-quiz-${qi}-${ai}`}>
                      <Ionicons
                        name={answers[qi] === ai
                          ? "radio-button-on"
                          : "radio-button-off"}
                        size={18}
                        color={answers[qi] === ai ? colors.brand : colors.muted}
                      />
                      <Text style={styles.qChoiceText}>{c}</Text>
                    </Pressable>
                  ))}
                </View>
              ))}
              <Pressable style={styles.doneBtn}
                         onPress={() => onQuiz(a, step, answers)}
                         testID="onb-quiz-submit">
                <Text style={styles.doneBtnText}>Submit quiz</Text>
              </Pressable>
            </ScrollView>
          ) : null}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg,
          padding: spacing.md, marginBottom: spacing.md,
          borderWidth: 1, borderColor: colors.border },
  cardHead: { flexDirection: "row", justifyContent: "space-between",
              alignItems: "center", marginBottom: spacing.sm },
  cardTitle: { fontFamily: font.bold, fontSize: fontSize.lg,
               color: colors.onSurface },
  cardMeta: { fontFamily: font.regular, fontSize: fontSize.sm,
              color: colors.muted, marginTop: 2 },
  ring: { width: 44, height: 44, borderRadius: 22,
          backgroundColor: colors.brandTertiary,
          alignItems: "center", justifyContent: "center" },
  ringText: { fontFamily: font.bold, fontSize: fontSize.sm,
              color: colors.brand },
  progressBar: { height: 6, borderRadius: 3,
                 backgroundColor: colors.surfaceSecondary,
                 overflow: "hidden", marginBottom: spacing.md },
  progressFill: { height: "100%", backgroundColor: colors.brand },
  step: { flexDirection: "row", alignItems: "center", gap: spacing.md,
          padding: spacing.md, borderRadius: radius.md,
          backgroundColor: colors.surfaceSecondary,
          borderWidth: 1, borderColor: colors.border,
          marginBottom: spacing.xs },
  stepDone: { backgroundColor: "#ECFDF5", borderColor: "#6EE7B7" },
  stepTitle: { fontFamily: font.semibold, fontSize: fontSize.base,
               color: colors.onSurface },
  stepMeta: { fontFamily: font.regular, fontSize: 12,
              color: colors.muted, marginTop: 2 },
  empty: { padding: spacing.xl, alignItems: "center" },
  emptyText: { color: colors.muted, marginTop: spacing.md,
               textAlign: "center", fontFamily: font.regular,
               fontSize: fontSize.base },
  sheetBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)",
             justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, padding: spacing.lg,
           borderTopLeftRadius: 20, borderTopRightRadius: 20,
           maxHeight: "85%" },
  sheetHead: { flexDirection: "row", justifyContent: "space-between",
               alignItems: "center", marginBottom: spacing.sm },
  sheetTitle: { flex: 1, fontFamily: font.bold, fontSize: fontSize.lg,
                color: colors.onSurface },
  sheetDesc: { fontFamily: font.regular, fontSize: fontSize.sm,
               color: colors.muted, marginBottom: spacing.md },
  doneBtn: { backgroundColor: colors.brand, padding: spacing.md,
             borderRadius: radius.md, alignItems: "center",
             marginTop: spacing.md },
  doneBtnText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.base },
  qText: { fontFamily: font.semibold, fontSize: fontSize.base,
           color: colors.onSurface, marginBottom: spacing.sm },
  qChoice: { flexDirection: "row", alignItems: "center", gap: spacing.sm,
             padding: spacing.sm, borderRadius: radius.md,
             backgroundColor: colors.surfaceSecondary,
             borderWidth: 1, borderColor: colors.border,
             marginBottom: 4 },
  qChoiceActive: { borderColor: colors.brand,
                   backgroundColor: colors.brandTertiary },
  qChoiceText: { fontFamily: font.regular, fontSize: fontSize.base,
                 color: colors.onSurface },
});
