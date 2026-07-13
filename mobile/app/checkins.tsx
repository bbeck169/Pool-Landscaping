import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

function relTime(iso?: string) {
  if (!iso) return "";
  try {
    const diff = Math.max(0, Date.now() - new Date(iso).getTime());
    const m = Math.floor(diff / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  } catch { return ""; }
}

export default function Checkins() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems(await api.get("/checkins"));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={styles.root}>
      <Header title="Map Check-ins" back subtitle="Field crew locations" />
      {loading ? (
        <Loading testID="checkins-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="map-outline" title="No check-ins yet" subtitle="Technician site check-ins appear here." testID="checkins-empty" />
      ) : (
        <FlatList
          testID="checkins-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`checkin-${item.id}`}>
              <View style={styles.pin}>
                <Ionicons name="location" size={20} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.tech}>{item.technician_name || "Technician"}</Text>
                <Text style={styles.address} numberOfLines={1}>{item.address || "Unknown location"}</Text>
                {item.note ? <Text style={styles.note}>{item.note}</Text> : null}
                {item.lat != null && item.lng != null ? (
                  <Text style={styles.coords}>{item.lat.toFixed(4)}, {item.lng.toFixed(4)}</Text>
                ) : null}
              </View>
              <Text style={styles.time}>{relTime(item.created_at)}</Text>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: { flexDirection: "row", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  pin: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  tech: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  address: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, marginTop: 2 },
  note: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  coords: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand, marginTop: 4 },
  time: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
});
