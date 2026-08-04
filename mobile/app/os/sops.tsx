// Phase 37 · Feb-2026 — Mobile Business OS · SOPs (P1.3).
// Web: BusinessOS.jsx SOP slice. Backend: GET/POST /sops, POST /sops/generate.
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, TextInput, Pressable } from "react-native";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, Loading, EmptyState, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

export default function OsSops() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [draft, setDraft] = useState({ title: "", topic: "", steps: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r: any = await api.get("/sops");
      setRows(Array.isArray(r) ? r : r?.items || []);
    } catch { setRows([]); } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = useCallback(async () => {
    if (!draft.title.trim()) return;
    setBusy(true);
    try {
      await api.post("/sops", { title: draft.title, topic: draft.topic || "", steps: draft.steps || "" });
      setAddOpen(false); setDraft({ title: "", topic: "", steps: "" });
      await load();
    } catch { /* ignore */ } finally { setBusy(false); }
  }, [draft, load]);

  const generate = useCallback(async () => {
    if (!draft.title.trim()) return;
    setBusy(true);
    try {
      await api.post("/sops/generate", { title: draft.title, topic: draft.topic || draft.title });
      setAddOpen(false); setDraft({ title: "", topic: "", steps: "" });
      await load();
    } catch { /* ignore */ } finally { setBusy(false); }
  }, [draft, load]);

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="os-sops-page">
        <Header title="SOPs" right={
          <IconButton icon="add" onPress={() => setAddOpen(true)} testID="os-sops-create" />
        } />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => {
            setRefreshing(true); await load(); setRefreshing(false);
          }} />}
        >
          {loading ? <Loading /> : rows.length === 0 ? (
            <EmptyState icon="document-text-outline" title="No SOPs yet" subtitle="Tap + to add or auto-generate one." testID="os-sops-empty" />
          ) : rows.map((r) => (
            <View key={r.id} style={styles.row} testID={`os-sop-row-${r.id}`}>
              <Text style={styles.title}>{r.title || "—"}</Text>
              {r.topic ? <Text style={styles.topic}>{r.topic}</Text> : null}
              {r.steps ? <Text style={styles.steps} numberOfLines={3}>{r.steps}</Text> : null}
            </View>
          ))}
        </ScrollView>
        <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="New SOP" testID="os-sops-sheet">
          <View style={{ gap: spacing.md, padding: spacing.lg }}>
            <TextInput placeholder="Title" value={draft.title} onChangeText={(t) => setDraft((d) => ({ ...d, title: t }))} style={styles.input} testID="os-sops-input-title" />
            <TextInput placeholder="Topic (optional)" value={draft.topic} onChangeText={(t) => setDraft((d) => ({ ...d, topic: t }))} style={styles.input} testID="os-sops-input-topic" />
            <TextInput placeholder="Steps (optional — leave blank + tap Generate to auto-write)" value={draft.steps} onChangeText={(t) => setDraft((d) => ({ ...d, steps: t }))} multiline style={[styles.input, { minHeight: 80 }]} testID="os-sops-input-steps" />
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <View style={{ flex: 1 }}>
                <PrimaryButton label={busy ? "Saving…" : "Save"} onPress={save} disabled={busy || !draft.title.trim()} testID="os-sops-save" />
              </View>
              <View style={{ flex: 1 }}>
                <PrimaryButton label={busy ? "Generating…" : "Generate"} onPress={generate} disabled={busy || !draft.title.trim()} testID="os-sops-generate" />
              </View>
            </View>
          </View>
        </Sheet>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.sm, paddingBottom: spacing["3xl"] },
  row: { padding: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, gap: 4 },
  title: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface },
  topic: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  steps: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 4 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, padding: spacing.sm, fontFamily: font.regular, fontSize: fontSize.md, backgroundColor: colors.surface },
});
