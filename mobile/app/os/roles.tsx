// Phase 37 · Feb-2026 — Business OS Roles (P1.3).
// Web: BusinessOS.jsx Roles slice. Backend: GET/POST /role-definitions.
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, TextInput } from "react-native";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

export default function OsRoles() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [draft, setDraft] = useState({ name: "", accountabilities: "", user_id: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r: any = await api.get("/role-definitions");
      setRows(Array.isArray(r) ? r : r?.items || []);
    } catch { setRows([]); } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const save = useCallback(async () => {
    if (!draft.name.trim()) return;
    setBusy(true);
    try {
      await api.post("/role-definitions", {
        name: draft.name,
        accountabilities: draft.accountabilities.split("\n").map((s) => s.trim()).filter(Boolean),
        user_id: draft.user_id || null,
      });
      setAddOpen(false); setDraft({ name: "", accountabilities: "", user_id: "" });
      await load();
    } catch { /* ignore */ } finally { setBusy(false); }
  }, [draft, load]);

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="os-roles-page">
        <Header title="Roles" right={<IconButton icon="add" onPress={() => setAddOpen(true)} testID="os-roles-create" />} />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => {
            setRefreshing(true); await load(); setRefreshing(false);
          }} />}
        >
          {loading ? <Loading /> : rows.length === 0 ? (
            <EmptyState icon="people-outline" title="No roles defined yet" subtitle="Tap + to define one." testID="os-roles-empty" />
          ) : rows.map((r) => (
            <View key={r.id} style={styles.row} testID={`os-role-row-${r.id}`}>
              <Text style={styles.name}>{r.name || "—"}</Text>
              {r.user_name ? <Text style={styles.assigned}>Held by {r.user_name}</Text> : null}
              {Array.isArray(r.accountabilities) && r.accountabilities.length > 0 ? (
                <Text style={styles.acc} numberOfLines={3}>{r.accountabilities.join(" · ")}</Text>
              ) : null}
            </View>
          ))}
        </ScrollView>
        <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="New role" testID="os-roles-sheet">
          <View style={{ gap: spacing.md, padding: spacing.lg }}>
            <TextInput placeholder="Role name" value={draft.name} onChangeText={(t) => setDraft((d) => ({ ...d, name: t }))} style={styles.input} testID="os-roles-input-name" />
            <TextInput placeholder="Accountabilities (one per line)" value={draft.accountabilities} onChangeText={(t) => setDraft((d) => ({ ...d, accountabilities: t }))} multiline style={[styles.input, { minHeight: 80 }]} testID="os-roles-input-accountabilities" />
            <TextInput placeholder="Assign to user id (optional)" value={draft.user_id} onChangeText={(t) => setDraft((d) => ({ ...d, user_id: t }))} style={styles.input} testID="os-roles-input-user" />
            <PrimaryButton label={busy ? "Saving…" : "Save"} onPress={save} disabled={busy || !draft.name.trim()} testID="os-roles-save" />
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
  name: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface },
  assigned: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.brand },
  acc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, padding: spacing.sm, fontFamily: font.regular, fontSize: fontSize.md, backgroundColor: colors.surface },
});
