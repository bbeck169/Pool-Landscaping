/**
 * Phase 33 · Portal Photos — grouped by date.
 * TD-67 / TD-76 Phase A — canonical thumb_url / full_url (legacy url
 * fallback), backend-absolutized + `?auth=` on authed routes, and the
 * web date → visit grouping.
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, SectionList, Pressable, Modal, Dimensions,
  RefreshControl,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import {
  groupPhotosByDateAndVisit, portalPhotoFullRaw, portalPhotoThumbRaw,
  resolvePortalMediaUri, usePortalAuthToken,
} from "@/src/lib/portalMediaUri";

const FILTERS = [
  { key: "", label: "All" },
  { key: "Weekly Pool Service", label: "Pool" },
  { key: "Monthly Landscaping", label: "Landscape" },
];

const SCREEN = Dimensions.get("window");
const GRID_COL = 3;
const TILE = (SCREEN.width - spacing.lg * 2 - spacing.sm * (GRID_COL - 1)) / GRID_COL;

function formatDateHeader(dateKey: string): string {
  if (dateKey === "Unknown date") return dateKey;
  try {
    const d = new Date(dateKey + "T12:00:00Z");
    if (Number.isNaN(d.getTime())) return dateKey;
    return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  } catch { return dateKey; }
}

// TD-76 Phase A — web-parity grouping: date header → divider → visit
// sub-header → photos row. Photos with no resolvable URI are skipped
// (RN would render a blank tile; web renders a broken <img>).
function buildSections(photos: any[], token: string) {
  const usable = photos.filter((p) => resolvePortalMediaUri(portalPhotoThumbRaw(p), token));
  return groupPhotosByDateAndVisit(usable).map((g) => ({
    title: formatDateHeader(g.day), dateKey: g.day, data: g.visits,
  }));
}

export default function PortalPhotos() {
  const token = usePortalAuthToken();
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

  const sections = useMemo(() => buildSections(photos, token), [photos, token]);

  return (
    <View style={styles.root}>
      <Header title="Service Photos" subtitle={`${photos.length} photos from your visits`} />
      <View style={styles.filterRow}>
        {FILTERS.map((f) => (
          <Pressable key={f.key} onPress={() => setFilter(f.key)}
                     style={[styles.chip, filter === f.key ? styles.chipActive : null]}
                     testID={`portal-photos-filter-${f.key || "all"}`}>
            <Text style={[styles.chipText, filter === f.key ? { color: "#fff" } : null]}>{f.label}</Text>
          </Pressable>
        ))}
      </View>
      {loading ? <Loading /> : (
        <SectionList
          testID="portal-photos-grouped"
          sections={sections}
          keyExtractor={(visit) => visit.visitKey}
          stickySectionHeadersEnabled={false}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: 120 }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />
          }
          renderSectionHeader={({ section }) => (
            <View>
              <Text
                style={styles.dateHeader}
                testID={`portal-photos-date-header-${section.dateKey}`}
              >
                {section.title}
              </Text>
              <View style={styles.dateDivider} testID={`portal-photos-date-divider-${section.dateKey}`} />
            </View>
          )}
          renderItem={({ item: visit, section }) => (
            <View style={styles.visit} testID={`portal-photos-visit-${section.dateKey}-${visit.visitKey}`}>
              <Text style={styles.visitHeader} testID={`portal-photos-visit-header-${section.dateKey}-${visit.visitKey}`}>
                {visit.jobTitle}
              </Text>
              <View style={styles.gridRow}>
                {visit.photos.map((photo: any, idx: number) => (
                  <Pressable
                    key={photo.id || idx}
                    onPress={() => setZoom(photo)}
                    style={styles.tile}
                    testID={`portal-photos-item-${photo.id || `${section.dateKey}-${visit.visitKey}-${idx}`}`}
                  >
                    <Image
                      source={{ uri: resolvePortalMediaUri(portalPhotoThumbRaw(photo), token) }}
                      style={{ width: "100%", height: "100%" }}
                      contentFit="cover"
                    />
                  </Pressable>
                ))}
              </View>
            </View>
          )}
          ListEmptyComponent={() => (
            <View style={styles.empty}>
              <Ionicons name="image-outline" size={40} color={colors.muted} />
              <Text style={styles.emptyText}>No photos yet. After your next visit, they&apos;ll appear here.</Text>
            </View>
          )}
        />
      )}

      <Modal visible={!!zoom} transparent onRequestClose={() => setZoom(null)}>
        <View style={styles.viewer}>
          <Pressable onPress={() => setZoom(null)} style={styles.viewerClose} testID="portal-photo-close">
            <Ionicons name="close" size={26} color="#fff" />
          </Pressable>
          {zoom ? (
            <Image
              source={{ uri: resolvePortalMediaUri(portalPhotoFullRaw(zoom), token) }}
              style={{ width: SCREEN.width, height: SCREEN.height * 0.7 }}
              contentFit="contain"
              testID="portal-photo-zoom-image"
            />
          ) : null}
          <View style={styles.viewerMeta}>
            <Text style={styles.viewerTitle}>{zoom?.job_title || "Service Photo"}</Text>
            <Text style={styles.viewerDate}>{(zoom?.submitted_at || "").slice(0, 10)}</Text>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  filterRow: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  chip: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 20, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  dateHeader: {
    fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface,
    marginTop: spacing.lg, marginBottom: spacing.sm,
  },
  dateDivider: { height: 1, backgroundColor: colors.border, marginBottom: spacing.md },
  visit: { marginBottom: spacing.md },
  visitHeader: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary,
    marginBottom: spacing.sm,
  },
  gridRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  tile: {
    width: TILE, height: TILE, borderRadius: radius.md, overflow: "hidden",
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  empty: { paddingVertical: 60, alignItems: "center" },
  emptyText: { color: colors.muted, marginTop: spacing.md, textAlign: "center", fontFamily: font.regular, fontSize: fontSize.base, paddingHorizontal: spacing.xl },
  viewer: { flex: 1, backgroundColor: "rgba(0,0,0,0.95)", justifyContent: "center", alignItems: "center" },
  viewerClose: { position: "absolute", top: 50, right: 20, zIndex: 5, padding: 6 },
  viewerMeta: { position: "absolute", bottom: 50, left: 0, right: 0, paddingHorizontal: spacing.lg, alignItems: "center" },
  viewerTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#fff" },
  viewerDate: { fontFamily: font.regular, fontSize: fontSize.sm, color: "rgba(255,255,255,0.7)", marginTop: 4 },
});
