// Phase 37 · Feb-2026 — Mobile Business OS hub (P1.3).
//
// Web parity: `frontend/src/pages/os/BusinessOS.jsx` overview slice.
// Backend: GET /api/os/overview.
// Hub-and-spoke — this file links out to the 7 deep-dives shipped in
// the rest of Phase 37.
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { router, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

const DEEP_DIVES = [
  { label: "SOPs",         to: "/os/sops",        icon: "document-text-outline", testID: "os-link-sops" },
  { label: "Roles",        to: "/os/roles",       icon: "people-outline",        testID: "os-link-roles" },
  { label: "Scorecards",   to: "/os/scorecards",  icon: "trophy-outline",        testID: "os-link-scorecards" },
  { label: "Huddle",       to: "/huddle",         icon: "chatbubbles-outline",   testID: "os-link-huddle" },
  { label: "Lean Boards",  to: "/os/leanboards",  icon: "grid-outline",          testID: "os-link-leanboards" },
  { label: "Sprints",      to: "/os/sprints",     icon: "flag-outline",          testID: "os-link-sprints" },
  { label: "Lana AI",      to: "/os/lana",        icon: "sparkles-outline",      testID: "os-link-lana" },
];

export default function BusinessOSHub() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r: any = await api.get("/os/overview");
      setData(r);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="os-hub-page">
        <Header title="Business OS" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={async () => {
              setRefreshing(true); await load(); setRefreshing(false);
            }} />
          }
        >
          {loading ? (
            <Loading />
          ) : (
            <>
              {data && (
                <Card style={styles.summary}>
                  <Text style={styles.summaryTitle}>Overview</Text>
                  <View style={styles.stats}>
                    <Stat label="SOPs" value={data.sop_count ?? 0} testID="os-overview-sops" />
                    <Stat label="Roles" value={data.role_count ?? 0} testID="os-overview-roles" />
                    <Stat label="Scorecards" value={data.scorecard_count ?? 0} testID="os-overview-scorecards" />
                    <Stat label="Sprints" value={data.sprint_count ?? 0} testID="os-overview-sprints" />
                  </View>
                </Card>
              )}
              <View style={styles.tiles} testID="os-deep-dives">
                {DEEP_DIVES.map((d) => (
                  <Pressable
                    key={d.to}
                    onPress={() => router.push(d.to as any)}
                    style={({ pressed }) => [styles.tile, pressed && { opacity: 0.7 }]}
                    testID={d.testID}
                  >
                    <Ionicons name={d.icon as any} size={20} color={colors.brand} />
                    <Text style={styles.tileLabel}>{d.label}</Text>
                    <Ionicons name="chevron-forward" size={16} color={colors.muted} />
                  </Pressable>
                ))}
              </View>
            </>
          )}
        </ScrollView>
      </View>
    </RoleGate>
  );
}

function Stat({ label, value, testID }: { label: string; value: number | string; testID: string }) {
  return (
    <View style={styles.stat} testID={testID}>
      <Text style={styles.statValue}>{String(value)}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  summary: { gap: spacing.sm },
  summaryTitle: { fontFamily: font.semibold, fontSize: fontSize.md, color: colors.onSurface },
  stats: { flexDirection: "row", justifyContent: "space-between", marginTop: spacing.xs },
  stat: { flex: 1, alignItems: "center" },
  statValue: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  statLabel: { fontFamily: font.medium, fontSize: 10, textTransform: "uppercase", color: colors.muted, letterSpacing: 0.5, marginTop: 2 },
  tiles: { gap: spacing.xs },
  tile: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    padding: spacing.md, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface,
  },
  tileLabel: { fontFamily: font.medium, fontSize: fontSize.md, color: colors.onSurface, flex: 1 },
});
