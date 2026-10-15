/**
 * Marketing Forms — read-only list (mobile parity, web /admin/marketing/forms).
 * admin + super_admin only (backend `require_admin`; web `<AdminOnly>`).
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, Pressable, RefreshControl, ActivityIndicator } from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { Header } from "@/src/components/widgets";
import CommsAdminGate from "@/src/components/comms/CommsAdminGate";
import { listForms, type MarketingForm } from "@/src/api/marketingForms";
import { colors, font, fontSize, radius, spacing } from "@/src/theme";

export default function MarketingFormsScreen() {
  return (
    <CommsAdminGate title="Marketing Forms">
      <MarketingFormsBody />
    </CommsAdminGate>
  );
}

function FormRow({ f, onPress }: { f: MarketingForm; onPress: () => void }) {
  const active = f.active !== false;
  return (
    <Pressable onPress={onPress} style={s.row} testID={`marketing-form-row-${f.id}`}>
      <View style={{ flex: 1 }}>
        <Text style={s.name} numberOfLines={1}>{f.name || "(untitled)"}</Text>
        <Text style={s.slug} numberOfLines={1}>/{f.slug || f.id}</Text>
        <View style={s.meta}>
          <View style={[s.pill, active ? s.pillOn : s.pillOff]} testID={`marketing-form-status-${f.id}`}>
            <Text style={[s.pillText, { color: active ? "#065F46" : "#4B5563" }]}>{active ? "Active" : "Inactive"}</Text>
          </View>
          <Text style={s.metaText} testID={`marketing-form-subs-${f.id}`}>{f.submission_count || 0} submissions</Text>
          <Text style={s.metaText}>{(f.fields || []).length} fields</Text>
          {f.version ? <Text style={s.metaText} testID={`marketing-form-version-${f.id}`}>v{f.version}</Text> : null}
        </View>
      </View>
      <Ionicons name="chevron-forward" size={18} color={colors.muted} />
    </Pressable>
  );
}

function MarketingFormsBody() {
  const router = useRouter();
  const [rows, setRows] = useState<MarketingForm[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await listForms());
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Couldn't load forms.");
      setRows((r) => r || []);
    }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={s.root} testID="marketing-forms-screen">
      <Header
        title="Marketing Forms"
        subtitle="View forms, versions & submissions"
        back
        right={
          <Pressable onPress={() => router.push("/admin/marketing/forms/submissions" as any)} hitSlop={8} testID="marketing-forms-inbox-btn" accessibilityLabel="Submissions inbox">
            <Ionicons name="file-tray-full-outline" size={22} color={colors.onSurface} />
          </Pressable>
        }
      />
      {rows === null ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} testID="marketing-forms-loader" />
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(f) => f.id}
          contentContainerStyle={{ padding: spacing.lg, gap: spacing.sm }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
          renderItem={({ item }) => (
            <FormRow f={item} onPress={() => router.push({ pathname: "/admin/marketing/forms/[id]", params: { id: item.id } } as any)} />
          )}
          ListHeaderComponent={error ? <Text style={s.err} testID="marketing-forms-error">{error}</Text> : null}
          ListEmptyComponent={!error ? <Text style={s.empty} testID="marketing-forms-empty">No forms yet — build one on desktop.</Text> : null}
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary },
  name: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  slug: { fontFamily: font.regular, fontSize: 12, color: colors.muted, marginTop: 1 },
  meta: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 8, marginTop: 6 },
  metaText: { fontFamily: font.medium, fontSize: 12, color: colors.muted },
  pill: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  pillOn: { backgroundColor: "#D1FAE5" },
  pillOff: { backgroundColor: "#F3F4F6" },
  pillText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.3 },
  err: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error, marginBottom: spacing.sm },
  empty: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", marginTop: 40 },
});
