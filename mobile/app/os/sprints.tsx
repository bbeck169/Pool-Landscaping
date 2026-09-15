// Phase 37 · Feb-2026 — Business OS Sprints (P1.3).
// Web: BusinessOS.jsx Sprints slice.
// Backend: GET/POST /sprints, POST /sprints/{id}/retro-ai.
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, Pressable } from "react-native";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, Loading, EmptyState, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";
import { showConfirm } from "@/src/components/ConfirmModal";
import AppTextInput from "@/src/components/ui/AppTextInput";

function _weekStart(): string {
  const d = new Date();
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  return new Date(d.setDate(diff)).toISOString().slice(0, 10);
}

export default function OsSprints() {
  const [rows, setRows] = useState<any[]>([]);
  const [active, setActive] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [draft, setDraft] = useState({ week_start: _weekStart(), theme: "", goals: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r: any = await api.get("/sprints");
      const list = Array.isArray(r) ? r : r?.items || [];
      setRows(list);
      if (list.length && !active) setActive(list[0]);
    } catch { setRows([]); } finally { setLoading(false); }
  }, [active]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = useCallback(async () => {
    if (!draft.week_start.trim()) return;
    setBusy(true);
    try {
      await api.post("/sprints", {
        week_start: draft.week_start,
        theme: draft.theme || "",
        goals: draft.goals.split("\n").map((s) => s.trim()).filter(Boolean),
      });
      setAddOpen(false); setDraft({ week_start: _weekStart(), theme: "", goals: "" });
      await load();
    } catch { /* ignore */ } finally { setBusy(false); }
  }, [draft, load]);

  const retroAI = useCallback((sprint: any) => {
    showConfirm({
      title: `Generate AI retrospective for "${sprint.theme || sprint.week_start}"?`,
      description: "Consumes AI credits from your Universal Key balance.",
      confirmLabel: "Generate",
      testID: "os-sprints-retro-confirm",
      onConfirm: async () => {
        setBusy(true);
        try {
          await api.post(`/sprints/${sprint.id}/retro-ai`, {});
          await load();
        } catch { /* ignore */ } finally { setBusy(false); }
      },
    });
  }, [load]);

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="os-sprints-page">
        <Header title="Sprints" right={<IconButton icon="add" onPress={() => setAddOpen(true)} testID="os-sprints-create" />} />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => {
            setRefreshing(true); await load(); setRefreshing(false);
          }} />}
        >
          {loading ? <Loading /> : rows.length === 0 ? (
            <EmptyState icon="flag-outline" title="No sprints yet" subtitle="Tap + to plan your first weekly sprint." testID="os-sprints-empty" />
          ) : (
            <>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.pills} testID="os-sprints-picker">
                {rows.map((r) => (
                  <Pressable
                    key={r.id}
                    onPress={() => setActive(r)}
                    style={[styles.pill, active?.id === r.id && styles.pillOn]}
                    testID={`os-sprints-week-${r.id}`}
                  >
                    <Text style={[styles.pillText, active?.id === r.id && styles.pillTextOn]}>{r.week_start}</Text>
                  </Pressable>
                ))}
              </ScrollView>
              {active && (
                <Card style={styles.detail} testID={`os-sprint-detail-${active.id}`}>
                  <Text style={styles.theme}>{active.theme || "—"}</Text>
                  <Text style={styles.week}>Week of {active.week_start}</Text>
                  <Text style={styles.section}>Goals</Text>
                  {(active.goals || []).length === 0 ? (
                    <Text style={styles.emptyGoals}>None set</Text>
                  ) : (active.goals || []).map((g: string, i: number) => (
                    <Text key={i} style={styles.goal}>• {g}</Text>
                  ))}
                  {active.retro_ai ? (
                    <>
                      <Text style={styles.section}>AI retrospective</Text>
                      <Text style={styles.retro}>{active.retro_ai}</Text>
                    </>
                  ) : (
                    <PrimaryButton
                      label={busy ? "Generating…" : "Generate AI retro"}
                      onPress={() => retroAI(active)}
                      disabled={busy}
                      testID="os-sprints-retro-ai"
                    />
                  )}
                </Card>
              )}
            </>
          )}
        </ScrollView>
        <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="New sprint" testID="os-sprints-sheet">
          <View style={{ gap: spacing.md, padding: spacing.lg }}>
            <AppTextInput placeholder="Week start (YYYY-MM-DD)" value={draft.week_start} onChangeText={(t) => setDraft((d) => ({ ...d, week_start: t }))} style={styles.input} testID="os-sprints-input-week" />
            <AppTextInput placeholder="Theme" value={draft.theme} onChangeText={(t) => setDraft((d) => ({ ...d, theme: t }))} style={styles.input} testID="os-sprints-input-theme" />
            <AppTextInput placeholder="Goals (one per line)" value={draft.goals} onChangeText={(t) => setDraft((d) => ({ ...d, goals: t }))} multiline style={[styles.input, { minHeight: 80 }]} testID="os-sprints-input-goals" />
            <PrimaryButton label={busy ? "Saving…" : "Save"} onPress={save} disabled={busy || !draft.week_start.trim()} testID="os-sprints-save" />
          </View>
        </Sheet>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.sm, paddingBottom: spacing["3xl"] },
  pills: { flexDirection: "row", gap: spacing.xs },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  pillOn: { backgroundColor: colors.brandTertiary, borderColor: colors.brand },
  pillText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  pillTextOn: { color: colors.brand },
  detail: { gap: spacing.sm },
  theme: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  week: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  section: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, marginTop: spacing.sm, textTransform: "uppercase", letterSpacing: 0.5 },
  emptyGoals: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  goal: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  retro: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, padding: spacing.sm, fontFamily: font.regular, fontSize: fontSize.md, backgroundColor: colors.surface },
});
