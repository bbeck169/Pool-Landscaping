import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { EmptyState, StatusChip } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

function fmtDate(iso: string | undefined) {
  if (!iso) return "\u2014";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleDateString(undefined, {
      weekday: "short",
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return String(iso);
  }
}

function reportKind(row: any): "pool" | "landscape" | "generic" {
  const raw = (
    row?.template ||
    row?.service_type ||
    row?.job?.service_type ||
    ""
  )
    .toString()
    .toLowerCase();
  if (raw.includes("landscap") || raw.includes("mow") || raw.includes("lawn"))
    return "landscape";
  if (raw.includes("pool") || raw.includes("chem")) return "pool";
  return "generic";
}

const KIND_META = {
  pool: { label: "Pool service", bg: "#E0F2FE", fg: "#0369A1", icon: "water-outline" as const },
  landscape: { label: "Landscape service", bg: "#DCFCE7", fg: "#166534", icon: "leaf-outline" as const },
  generic: { label: "Service", bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary, icon: "clipboard-outline" as const },
};

function SkeletonRows() {
  return (
    <View style={s.skeletonWrap} testID="service-reports-skeleton">
      {[1, 2, 3, 4].map((i) => (
        <View key={i} style={s.skeletonCard}>
          <View style={s.skeletonIcon} />
          <View style={{ flex: 1, gap: 8 }}>
            <View style={[s.skeletonBar, { width: "60%" }]} />
            <View style={[s.skeletonBar, { width: "80%" }]} />
            <View style={[s.skeletonBar, { width: "40%" }]} />
          </View>
        </View>
      ))}
    </View>
  );
}

export default function PortalServiceReports() {
  const router = useRouter();
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setErr("");
      const data = await api.get("/customers/me/service-reports");
      setRows(Array.isArray(data) ? data : []);
    } catch (e: any) {
      setErr(e?.message || "Failed to load service reports.");
      setRows([]);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const renderItem = ({ item }: { item: any }) => {
    const kind = reportKind(item);
    const km = KIND_META[kind];
    return (
      <Pressable
        testID={`portal-service-report-card-${item.id}`}
        style={({ pressed }) => [s.card, pressed && { opacity: 0.85 }]}
        onPress={() => router.push(`/portal/service-report/${item.id}` as any)}
      >
        <View style={[s.kindIcon, { backgroundColor: km.bg }]}>
          <Ionicons name={km.icon} size={18} color={km.fg} />
        </View>
        <View style={{ flex: 1 }}>
          <View style={s.chipRow}>
            <View style={[s.kindChip, { backgroundColor: km.bg }]}>
              <Text style={[s.kindChipText, { color: km.fg }]}>{km.label}</Text>
            </View>
            <Text style={s.dateText} testID={`portal-service-report-date-${item.id}`}>
              {fmtDate(item.submitted_at || item.scheduled_start)}
            </Text>
          </View>
          <Text style={s.title} numberOfLines={1}>
            {item.job_title || "Service visit"}
          </Text>
          <View style={s.techRow}>
            <Ionicons name="person-outline" size={11} color={colors.muted} />
            <Text style={s.techName}>
              {item.tech_name || "Technician not recorded"}
            </Text>
          </View>
        </View>
        <StatusChip status="completed" />
      </Pressable>
    );
  };

  return (
    <View style={s.root}>
      <Header title="Service Reports" subtitle="Reports from every visit" back />

      {err ? (
        <View style={s.errorBanner} testID="portal-service-reports-error">
          <Ionicons name="alert-circle-outline" size={16} color="#991B1B" />
          <Text style={s.errorText}>{err}</Text>
        </View>
      ) : null}

      {rows === null ? (
        <SkeletonRows />
      ) : rows.length === 0 ? (
        <EmptyState
          icon="clipboard-outline"
          title="No service reports yet"
          subtitle="Your first report will appear here after your next scheduled visit."
          testID="portal-service-reports-empty"
        />
      ) : (
        <FlatList
          testID="portal-service-reports-list"
          data={rows}
          keyExtractor={(item) => item.id}
          renderItem={renderItem}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); load(); }}
            />
          }
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  kindIcon: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  chipRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  kindChip: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
  },
  kindChipText: {
    fontFamily: font.bold,
    fontSize: 10,
    textTransform: "uppercase",
  },
  dateText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  title: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
    marginTop: 4,
  },
  techRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: 2,
  },
  techName: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  errorBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginHorizontal: spacing.lg,
    marginTop: spacing.md,
    padding: spacing.md,
    borderRadius: radius.lg,
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FCA5A5",
  },
  errorText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#991B1B",
    flex: 1,
  },
  skeletonWrap: { padding: spacing.lg, gap: spacing.sm },
  skeletonCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  skeletonIcon: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
  },
  skeletonBar: {
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.surfaceTertiary,
  },
});
