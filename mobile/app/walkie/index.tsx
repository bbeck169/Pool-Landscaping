/**
 * Phase 51c · Feb 2026 — Walkie-Talkie channel list (mobile).
 *
 * Mirrors ``frontend/src/pages/walkie/Walkie.jsx`` left rail on
 * mobile. Uses the standard ``<Header>`` + pull-to-refresh
 * ``<ScrollView>`` scaffold — we do NOT wrap in the
 * ``<AdminListPage>`` primitive because that gates to
 * ``dispatcher_plus`` by default and walkie must be reachable by
 * technicians (the whole point of the surface). Customers are
 * bounced to the tab-home via the ``isCustomer`` check.
 */
import React, { useCallback, useState } from "react";
import { RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, fontSize, radius } from "@/src/theme";
import { EmptyState, Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { useAuth } from "@/src/auth";
import { isCustomer } from "@/src/components/RoleGate";
import { sortChannels } from "@/src/pages/walkie/walkie-helpers";

type Channel = {
  id: string;
  kind: "all_hands" | "department" | "direct";
  department?: string;
  member_user_ids?: string[];
  unread_count?: number;
  created_at?: string;
};

const KIND_ICON: Record<string, any> = {
  all_hands: "radio-outline",
  department: "people-outline",
  direct: "person-outline",
};

function channelLabel(c: Channel): string {
  if (c.kind === "all_hands") return "All-Hands";
  if (c.kind === "department") {
    const d = (c.department || "").replace(/^\w/, (m) => m.toUpperCase());
    return `${d} Team`;
  }
  return "Direct message";
}

export default function WalkieChannelList() {
  const { user } = useAuth();
  const router = useRouter();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/walkie/channels");
      setChannels(sortChannels(r.channels || []));
    } catch {
      setChannels([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  if (user && isCustomer(user)) {
    return (
      <View style={styles.container} testID="walkie-page">
        <Header title="Walkie-Talkie" />
        <EmptyState
          icon="radio-outline"
          title="Walkie-Talkie"
          subtitle="Not available for your account."
          testID="walkie-empty-customer"
        />
      </View>
    );
  }

  return (
    <View style={styles.container} testID="walkie-page">
      <Header title="Walkie-Talkie" />
      <ScrollView
        contentContainerStyle={styles.body}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); }} />}
      >
        {loading ? (
          <Loading />
        ) : channels.length === 0 ? (
          <EmptyState
            icon="radio-outline"
            title="Walkie-Talkie"
            subtitle="No channels yet."
            testID="walkie-empty"
          />
        ) : (
          channels.map((c) => {
            const unread = Number(c.unread_count) || 0;
            return (
              <TouchableOpacity
                key={c.id}
                style={styles.row}
                onPress={() => router.push(`/walkie/${c.id}` as any)}
                testID={`walkie-channel-${c.kind}${c.department ? "-" + c.department : ""}`}
              >
                <View style={styles.iconWrap}>
                  <Ionicons name={KIND_ICON[c.kind] as any} size={22} color={colors.onSurfaceSecondary} />
                </View>
                <View style={styles.body2}>
                  <Text style={styles.title} numberOfLines={1}>{channelLabel(c)}</Text>
                  <Text style={styles.subtitle} numberOfLines={1}>
                    {c.kind === "all_hands"
                      ? "Broadcast to everyone"
                      : c.kind === "department"
                        ? "Your crew"
                        : "1:1 conversation"}
                  </Text>
                </View>
                {unread > 0 && (
                  <View style={styles.badge} testID={`walkie-channel-unread-${c.id}`}>
                    <Text style={styles.badgeText}>{unread}</Text>
                  </View>
                )}
              </TouchableOpacity>
            );
          })
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.md,
    backgroundColor: colors.surfaceElevated,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderMuted,
  },
  iconWrap: {
    height: 40, width: 40, borderRadius: 999,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceTertiary,
  },
  body2: { flex: 1, minWidth: 0 },
  title: { fontSize: fontSize.base, fontWeight: "600", color: colors.onSurface },
  subtitle: { fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 2 },
  badge: {
    minWidth: 22, height: 22, borderRadius: 999,
    paddingHorizontal: 6,
    backgroundColor: colors.error,
    alignItems: "center", justifyContent: "center",
  },
  badgeText: { color: "#fff", fontWeight: "700", fontSize: fontSize.sm },
});
