/**
 * Phase 56.13c · Training Mobile — Module list screen.
 * Mirror of /tests on web.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, Pressable, RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

type Module = {
  code: string;
  title: string;
  description?: string;
  department: string;
  is_system?: boolean;
  lesson_count: number;
  question_count: number;
  progress?: { percent?: number };
};

export default function TrainingList() {
  const router = useRouter();
  const [items, setItems] = useState<Module[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const rows = (await api.get("/training/modules")) as Module[];
      setItems(Array.isArray(rows) ? rows : []);
      setErr("");
    } catch (e: any) {
      setErr(e?.message || "Could not load training modules");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const renderCard = ({ item }: { item: Module }) => {
    const pct = Math.round((item.progress?.percent || 0) * 100);
    const done = pct >= 100;
    const started = pct > 0 && pct < 100;
    const cta = done ? "Review" : started ? "Resume" : "Start";
    const deptColor =
      item.department === "landscaping" ? "#166534" :
      item.department === "both" ? "#92400E" : "#1E40AF";
    const deptBg =
      item.department === "landscaping" ? "#DCFCE7" :
      item.department === "both" ? "#FEF3C7" : "#DBEAFE";

    return (
      <Pressable
        style={styles.card}
        onPress={() => router.push(`/(app)/tests/${item.code}` as any)}
        testID={`training-module-card-${item.code}`}
      >
        <View style={styles.cardHeader}>
          <View style={styles.badgeRow}>
            <View style={[styles.badge, { backgroundColor: deptBg }]}>
              <Text style={[styles.badgeText, { color: deptColor }]}>
                {(item.department || "pool").toUpperCase()}
              </Text>
            </View>
            {item.is_system ? (
              <View style={[styles.badge, { backgroundColor: colors.surfaceAlt }]}>
                <Text style={[styles.badgeText, { color: colors.muted }]}>SYSTEM</Text>
              </View>
            ) : null}
          </View>
          <Text style={styles.pctText}>{pct}%</Text>
        </View>
        <Text style={styles.title}>{item.title}</Text>
        {item.description ? (
          <Text style={styles.desc} numberOfLines={2}>{item.description}</Text>
        ) : null}
        <Text style={styles.meta}>
          {item.lesson_count} lessons · {item.question_count} quiz questions
        </Text>
        <View style={styles.progressWrap}>
          <View style={[styles.progressBar, { width: `${pct}%`, backgroundColor: done ? "#10B981" : colors.brand }]} />
        </View>
        <View style={[styles.cta, { backgroundColor: done ? "#10B981" : colors.brand }]}>
          <Ionicons name={done ? "trophy-outline" : "play-outline"} size={14} color="#fff" />
          <Text style={styles.ctaText}>{cta}</Text>
        </View>
      </Pressable>
    );
  };

  return (
    <View style={styles.root}>
      <Header title="Tests · Training" />
      {loading ? (
        <Loading />
      ) : err ? (
        <View style={styles.pad}><Text style={styles.err}>{err}</Text></View>
      ) : items.length === 0 ? (
        <EmptyState title="No modules yet"
                    hint="Nothing published for your department." />
      ) : (
        <FlatList
          data={items}
          keyExtractor={(m) => m.code}
          renderItem={renderCard}
          contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}
          refreshControl={
            <RefreshControl refreshing={refreshing}
                            onRefresh={() => { setRefreshing(true); load(); }} />
          }
          testID="training-list"
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  pad: { padding: spacing.md },
  err: { color: "#DC2626", fontFamily: font.regular, fontSize: fontSize.base },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, padding: spacing.md,
  },
  cardHeader: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    marginBottom: spacing.xs,
  },
  badgeRow: { flexDirection: "row", gap: spacing.xs },
  badge: {
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999,
  },
  badgeText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.5 },
  pctText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.muted },
  title: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  desc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  meta: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: spacing.xs },
  progressWrap: {
    height: 6, backgroundColor: colors.border, borderRadius: 3,
    marginTop: spacing.sm, overflow: "hidden",
  },
  progressBar: { height: "100%", borderRadius: 3 },
  cta: {
    marginTop: spacing.sm, alignSelf: "flex-end",
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.md,
  },
  ctaText: { fontFamily: font.bold, fontSize: fontSize.xs, color: "#fff" },
});
