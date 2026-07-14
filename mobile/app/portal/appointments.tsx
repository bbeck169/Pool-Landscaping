/**
 * Phase 20B mobile A.2 · Customer's own appointments list.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, RefreshControl, Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

const STATUS_META: Record<string, { bg: string; fg: string; label: string }> = {
  pending:   { bg: "#FEF3C7", fg: "#92400E", label: "Pending" },
  confirmed: { bg: "#DCFCE7", fg: "#166534", label: "Confirmed" },
  rejected:  { bg: "#FEE2E2", fg: "#991B1B", label: "Rejected" },
};

export default function PortalAppointments() {
  const router = useRouter();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try { setRows(await api.get("/portal/appointments")); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={styles.root}>
      <Header title="My Appointments"
              subtitle="Track pending, confirmed, or rejected requests"
              right={
                <Pressable onPress={() => router.push("/portal/book" as any)}
                           style={styles.newBtn} testID="portal-appts-new">
                  <Ionicons name="add" size={16} color="#fff" />
                  <Text style={styles.newBtnText}>Book</Text>
                </Pressable>
              } />
      {loading ? <Loading /> : (
        <FlatList
          testID="portal-appts-list"
          data={rows}
          keyExtractor={(r) => r.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: 120 }}
          refreshControl={
            <RefreshControl refreshing={refreshing}
                            onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => {
            const m = STATUS_META[item.status] || STATUS_META.pending;
            return (
              <View style={styles.row} testID={`appt-row-${item.id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowTitle} numberOfLines={1}>
                    {item.service_type}
                  </Text>
                  <Text style={styles.rowMeta}>
                    {item.preferred_date} · {item.preferred_window}
                  </Text>
                  {item.reject_reason ? (
                    <Text style={styles.rejectText}>
                      Reason: {item.reject_reason}
                    </Text>
                  ) : null}
                </View>
                <View style={[styles.pill, { backgroundColor: m.bg }]}>
                  <Text style={[styles.pillText, { color: m.fg }]}>{m.label}</Text>
                </View>
              </View>
            );
          }}
          ListEmptyComponent={() => (
            <View style={styles.empty}>
              <Ionicons name="calendar-outline" size={40} color={colors.muted} />
              <Text style={styles.emptyText}>
                No appointments yet. Tap Book to schedule one.
              </Text>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md,
         backgroundColor: colors.surface, padding: spacing.md,
         borderRadius: radius.lg, marginBottom: spacing.sm,
         borderWidth: 1, borderColor: colors.border },
  rowTitle: { fontFamily: font.semibold, fontSize: fontSize.base,
              color: colors.onSurface },
  rowMeta: { fontFamily: font.regular, fontSize: fontSize.sm,
             color: colors.muted, marginTop: 2 },
  rejectText: { fontFamily: font.regular, fontSize: 12,
                color: "#991B1B", marginTop: 4 },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  pillText: { fontFamily: font.bold, fontSize: 10,
              textTransform: "uppercase", letterSpacing: 0.6 },
  newBtn: { flexDirection: "row", alignItems: "center", gap: 4,
            backgroundColor: colors.brand,
            paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999 },
  newBtnText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.sm },
  empty: { paddingVertical: 60, alignItems: "center" },
  emptyText: { color: colors.muted, marginTop: spacing.md,
               textAlign: "center", fontFamily: font.regular,
               fontSize: fontSize.base },
});
