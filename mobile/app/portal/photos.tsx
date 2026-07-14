/**
 * Phase 20B mobile A.3 · Customer photo history.
 * Simple grid + full-screen viewer.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, Pressable, Modal, Dimensions,
  RefreshControl,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

const FILTERS = [
  { key: "",                        label: "All" },
  { key: "Weekly Pool Service",     label: "Pool" },
  { key: "Monthly Landscaping",     label: "Landscape" },
];

const SCREEN = Dimensions.get("window");
const GRID_COL = 3;
const TILE = (SCREEN.width - spacing.lg * 2 - spacing.sm * (GRID_COL - 1)) / GRID_COL;

export default function PortalPhotos() {
  const [photos, setPhotos] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState("");
  const [zoom, setZoom] = useState<any | null>(null);

  const load = useCallback(async () => {
    try {
      const q = filter ? `?service_type=${encodeURIComponent(filter)}` : "";
      const r = await api.get(`/portal/photos${q}`);
      setPhotos(r.photos || []);
    } finally { setLoading(false); setRefreshing(false); }
  }, [filter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={styles.root}>
      <Header title="Service Photos"
              subtitle={`${photos.length} photos from your visits`} />
      <View style={styles.filterRow}>
        {FILTERS.map((f) => (
          <Pressable key={f.key} onPress={() => setFilter(f.key)}
                     style={[styles.chip,
                             filter === f.key ? styles.chipActive : null]}
                     testID={`portal-photos-filter-${f.key || "all"}`}>
            <Text style={[styles.chipText,
                          filter === f.key ? { color: "#fff" } : null]}>
              {f.label}
            </Text>
          </Pressable>
        ))}
      </View>
      {loading ? <Loading /> : (
        <FlatList
          testID="portal-photos-grid"
          data={photos}
          numColumns={GRID_COL}
          keyExtractor={(_, i) => String(i)}
          contentContainerStyle={{ padding: spacing.lg,
                                    gap: spacing.sm,
                                    paddingBottom: 120 }}
          columnWrapperStyle={{ gap: spacing.sm }}
          refreshControl={
            <RefreshControl refreshing={refreshing}
                            onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item, index }) => (
            <Pressable onPress={() => setZoom(item)}
                       style={{ width: TILE, height: TILE, borderRadius: radius.md,
                                overflow: "hidden",
                                backgroundColor: colors.surface,
                                borderWidth: 1, borderColor: colors.border }}
                       testID={`portal-photo-${index}`}>
              <Image source={{ uri: item.thumb || item.url }}
                     style={{ width: "100%", height: "100%" }}
                     contentFit="cover" />
            </Pressable>
          )}
          ListEmptyComponent={() => (
            <View style={styles.empty}>
              <Ionicons name="image-outline" size={40} color={colors.muted} />
              <Text style={styles.emptyText}>
                No photos yet. After your next visit, they'll appear here.
              </Text>
            </View>
          )}
        />
      )}

      <Modal visible={!!zoom} transparent
             onRequestClose={() => setZoom(null)}>
        <View style={styles.viewer}>
          <Pressable onPress={() => setZoom(null)} style={styles.viewerClose}
                     testID="portal-photo-close">
            <Ionicons name="close" size={26} color="#fff" />
          </Pressable>
          {zoom ? (
            <Image source={{ uri: zoom.url }}
                   style={{ width: SCREEN.width, height: SCREEN.height * 0.7 }}
                   contentFit="contain" />
          ) : null}
          <View style={styles.viewerMeta}>
            <Text style={styles.viewerTitle}>
              {zoom?.job_title || "Service Photo"}
            </Text>
            <Text style={styles.viewerDate}>
              {(zoom?.submitted_at || "").slice(0, 10)}
            </Text>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  filterRow: { flexDirection: "row", gap: spacing.sm,
               paddingHorizontal: spacing.lg,
               paddingVertical: spacing.md },
  chip: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 20,
          borderWidth: 1, borderColor: colors.border,
          backgroundColor: colors.surface },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm,
              color: colors.onSurface },
  empty: { paddingVertical: 60, alignItems: "center" },
  emptyText: { color: colors.muted, marginTop: spacing.md,
               textAlign: "center", fontFamily: font.regular,
               fontSize: fontSize.base, paddingHorizontal: spacing.xl },
  viewer: { flex: 1, backgroundColor: "rgba(0,0,0,0.95)",
            justifyContent: "center", alignItems: "center" },
  viewerClose: { position: "absolute", top: 50, right: 20, zIndex: 5,
                 padding: 6 },
  viewerMeta: { position: "absolute", bottom: 50, left: 0, right: 0,
                paddingHorizontal: spacing.lg, alignItems: "center" },
  viewerTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff" },
  viewerDate: { fontFamily: font.regular, fontSize: fontSize.sm,
                color: "rgba(255,255,255,0.7)", marginTop: 4 },
});
