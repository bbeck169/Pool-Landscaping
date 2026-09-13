import React, { useCallback, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useToast } from "@/src/components/ToastProvider";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading, Sheet, PrimaryButton, EmptyState } from "@/src/components/ui";

function isoDate(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function weekDays(): { iso: string; label: string }[] {
  const today = new Date();
  const monday = new Date(today);
  monday.setDate(today.getDate() - ((today.getDay() + 6) % 7)); // Monday
  return Array.from({ length: 6 }).map((_, i) => {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    return { iso: isoDate(d), label: d.toLocaleDateString("en-US", { weekday: "short", day: "numeric" }) };
  });
}

export default function RouteCoverage() {
  const { showToast } = useToast();
  const [techs, setTechs] = useState<any[]>([]);
  const [active, setActive] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [sheet, setSheet] = useState(false);
  const [saving, setSaving] = useState(false);

  const [source, setSource] = useState<string | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const [scope, setScope] = useState<"day" | "week">("day");
  const days = useMemo(() => weekDays(), []);
  const [date, setDate] = useState<string>(isoDate(new Date()));

  const load = useCallback(async () => {
    try {
      const [t, a] = await Promise.all([api.get("/technicians"), api.get("/coverage/active")]);
      setTechs(t);
      setActive(a);
    } catch { /* keep */ }
    finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const openSheet = () => {
    setSource(null); setTarget(null); setScope("day"); setDate(isoDate(new Date()));
    setSheet(true);
  };

  const submit = async () => {
    if (!source) { Alert.alert("Pick a technician", "Choose whose route to move."); return; }
    if (!target) { Alert.alert("Pick a substitute", "Choose the technician to cover the route."); return; }
    if (source === target) { Alert.alert("Different tech", "The substitute must be different from the original."); return; }
    setSaving(true);
    try {
      const res = await api.post("/coverage", { source_technician_id: source, target_technician_id: target, scope, date });
      setSheet(false);
      await load();
      showToast(`${res.job_count} stop(s) moved to ${res.target_technician_name} for ${res.label}. Reverts after Saturday.`);
    } catch (e: any) {
      Alert.alert("Couldn't move route", e.message || "Try a different day or technician.");
    } finally {
      setSaving(false);
    }
  };

  const undo = (c: any) => {
    Alert.alert("Undo coverage", `Return ${c.source_technician_name}'s ${c.label} route now?`, [
      { text: "Cancel", style: "cancel" },
      { text: "Undo", onPress: async () => {
        try { await api.post(`/coverage/${c.id}/revert`, {}); await load(); }
        catch (e: any) { Alert.alert("Error", e.message || "Could not undo."); }
      } },
    ]);
  };

  if (loading) return <Loading testID="coverage-loading" />;

  return (
    <View style={styles.root}>
      <Header title="Route Coverage" back subtitle="Temporarily cover a tech's route" />

      <Pressable style={styles.coverBtn} onPress={openSheet} testID="coverage-cover-btn">
        <Ionicons name="swap-horizontal" size={18} color="#fff" />
        <Text style={styles.coverBtnText}>Cover a route</Text>
      </Pressable>

      <Text style={styles.sectionTitle}>Active coverage</Text>
      {active.length === 0 ? (
        <EmptyState icon="git-branch-outline" title="No active coverage" subtitle="Move a day's route to a substitute; it auto-returns after Saturday." testID="coverage-empty" />
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingTop: 0 }}>
          {active.map((c) => (
            <View key={c.id} style={styles.card} testID={`coverage-${c.id}`}>
              <View style={styles.iconWrap}>
                <Ionicons name="swap-horizontal" size={18} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.cardTitle} numberOfLines={1}>{c.source_technician_name} → {c.target_technician_name}</Text>
                <Text style={styles.cardMeta} numberOfLines={1}>{c.label} · {c.job_count} stop(s) · reverts after Sat</Text>
              </View>
              <Pressable style={styles.undoBtn} onPress={() => undo(c)} testID={`coverage-undo-${c.id}`}>
                <Text style={styles.undoText}>Undo</Text>
              </Pressable>
            </View>
          ))}
        </ScrollView>
      )}

      <Sheet visible={sheet} onClose={() => setSheet(false)} title="Cover a Route" testID="coverage-sheet">
        <ScrollView style={{ maxHeight: 500 }} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>Move route from</Text>
          <View style={styles.chipWrap}>
            {techs.map((t) => (
              <Pressable key={t.id} style={[styles.chip, source === t.id && styles.chipActive]} onPress={() => setSource(t.id)} testID={`coverage-source-${t.id}`}>
                <Text style={[styles.chipText, source === t.id && { color: "#fff" }]}>{t.name}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.label}>How much</Text>
          <View style={styles.segRow}>
            <Pressable style={[styles.seg, scope === "day" && styles.segActive]} onPress={() => setScope("day")} testID="coverage-scope-day">
              <Text style={[styles.segText, scope === "day" && { color: "#fff" }]}>One day</Text>
            </Pressable>
            <Pressable style={[styles.seg, scope === "week" && styles.segActive]} onPress={() => setScope("week")} testID="coverage-scope-week">
              <Text style={[styles.segText, scope === "week" && { color: "#fff" }]}>Rest of week</Text>
            </Pressable>
          </View>

          {scope === "day" ? (
            <>
              <Text style={styles.label}>Which day (this week)</Text>
              <View style={styles.chipWrap}>
                {days.map((d) => (
                  <Pressable key={d.iso} style={[styles.chip, date === d.iso && styles.chipActive]} onPress={() => setDate(d.iso)} testID={`coverage-day-${d.iso}`}>
                    <Text style={[styles.chipText, date === d.iso && { color: "#fff" }]}>{d.label}</Text>
                  </Pressable>
                ))}
              </View>
            </>
          ) : (
            <Text style={styles.note}>Moves all open stops from today through Saturday.</Text>
          )}

          <Text style={styles.label}>Cover with</Text>
          <View style={styles.chipWrap}>
            {techs.filter((t) => t.id !== source).map((t) => (
              <Pressable key={t.id} style={[styles.chip, target === t.id && styles.chipActiveGreen]} onPress={() => setTarget(t.id)} testID={`coverage-target-${t.id}`}>
                <Text style={[styles.chipText, target === t.id && { color: "#fff" }]}>{t.name}</Text>
              </Pressable>
            ))}
          </View>

          <View style={{ height: spacing.md }} />
          <PrimaryButton title={saving ? "Moving…" : "Move Route"} icon="swap-horizontal" loading={saving} onPress={submit} testID="coverage-submit" />
        </ScrollView>
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  coverBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.brand, marginHorizontal: spacing.lg, marginTop: spacing.md, height: 50, borderRadius: radius.md },
  coverBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginTop: spacing.lg, marginHorizontal: spacing.lg, marginBottom: spacing.sm },
  card: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  iconWrap: { width: 36, height: 36, borderRadius: 18, backgroundColor: "#0EA5E9", alignItems: "center", justifyContent: "center" },
  cardTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  cardMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  undoBtn: { paddingHorizontal: spacing.md, height: 34, borderRadius: radius.pill, borderWidth: 1.5, borderColor: colors.error, alignItems: "center", justifyContent: "center" },
  undoText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.error },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: spacing.md, marginBottom: spacing.xs },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { paddingHorizontal: spacing.md, height: 38, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipActiveGreen: { backgroundColor: "#16A34A", borderColor: "#16A34A" },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  segRow: { flexDirection: "row", gap: spacing.sm },
  seg: { flex: 1, height: 42, borderRadius: radius.md, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  segActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  segText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  note: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.xs },
});
