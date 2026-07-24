import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, Pressable,
  ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

export default function LocalSeoChecklist() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const [data, setData] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [toggling, setToggling] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/local-seo/checklist");
      setData(r);
    } catch {
      setData({ items: [] });
    } finally {
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { if (isAdmin) load(); }, [isAdmin, load]));

  const toggle = async (key: string, next: boolean) => {
    setToggling(key);
    // Optimistic
    setData((d: any) => d && ({
      ...d,
      items: d.items.map((it: any) => it.key === key ? { ...it, ok: next } : it),
    }));
    try {
      await api.patch("/local-seo/checklist", { toggles: { [key]: next } });
      await load();
    } catch {
      await load();
    } finally {
      setToggling(null);
    }
  };

  if (!isAdmin) {
    return (
      <View style={s.root}>
        <Header title="Local SEO" back />
        <View style={s.center}>
          <Ionicons name="lock-closed" size={32} color={colors.muted} />
          <Text style={s.centerText}>Admin only</Text>
        </View>
      </View>
    );
  }

  const items = data?.items || [];
  const done = items.filter((i: any) => i.ok).length;

  return (
    <View style={s.root}>
      <Header title="Local SEO" subtitle="GBP hygiene checklist" back />
      {!data ? (
        <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View>
      ) : (
        <ScrollView
          testID="local-seo-page"
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        >
          {/* Score */}
          <View style={s.scoreCard} testID="local-seo-score">
            <Text style={s.scoreNum}>{done}/{items.length}</Text>
            <Text style={s.scoreLabel}>Items complete</Text>
            <View style={s.progressBg}>
              <View style={[s.progressFill, { width: items.length ? `${(done / items.length) * 100}%` : "0%" }]} />
            </View>
          </View>

          {/* Items */}
          {items.map((it: any) => (
            <Pressable
              key={it.key}
              style={s.item}
              onPress={() => toggle(it.key, !it.ok)}
              testID={`local-seo-item-${it.key}`}
            >
              <View style={[s.checkCircle, it.ok && s.checkCircleDone]}>
                {it.ok ? (
                  <Ionicons name="checkmark" size={14} color="#fff" />
                ) : toggling === it.key ? (
                  <ActivityIndicator size="small" color={colors.muted} />
                ) : null}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[s.itemLabel, it.ok && s.itemDone]}>{it.label}</Text>
                {it.description ? <Text style={s.itemDesc}>{it.description}</Text> : null}
              </View>
            </Pressable>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  centerText: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.muted },
  scoreCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl,
    borderWidth: 1, borderColor: colors.border, alignItems: "center", marginBottom: spacing.lg,
  },
  scoreNum: { fontFamily: font.bold, fontSize: 36, color: colors.brand },
  scoreLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  progressBg: {
    width: "100%", height: 6, borderRadius: 3, backgroundColor: colors.surfaceTertiary,
    marginTop: spacing.md, overflow: "hidden",
  },
  progressFill: { height: 6, borderRadius: 3, backgroundColor: colors.brand },
  item: {
    flexDirection: "row", alignItems: "flex-start", gap: spacing.md,
    paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  checkCircle: {
    width: 26, height: 26, borderRadius: 13, borderWidth: 2,
    borderColor: colors.border, alignItems: "center", justifyContent: "center",
    marginTop: 2,
  },
  checkCircleDone: { backgroundColor: colors.success, borderColor: colors.success },
  itemLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  itemDone: { textDecorationLine: "line-through", color: colors.muted },
  itemDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2, lineHeight: 18 },
});
