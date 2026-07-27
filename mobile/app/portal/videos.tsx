/**
 * Phase 33 · Portal Videos — grouped by date.
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, SectionList, TouchableOpacity,
  RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import {
  fetchPortalVideos, bytesToLabel, durationLabel, relativeTime,
} from "@/src/api/media";
import VideoPlayerModal from "@/src/components/media/VideoPlayerModal";

type PortalVideo = {
  video_id: string;
  storage_path: string;
  size_bytes: number;
  duration_seconds: number | null;
  caption: string;
  uploaded_by_name: string;
  uploaded_at: string;
  kind: string;
  entity_id: string;
  entity_title: string;
  job_scheduled_date?: string;
};

function formatDateHeader(dateKey: string): string {
  try {
    const d = new Date(dateKey + "T12:00:00Z");
    if (Number.isNaN(d.getTime())) return dateKey;
    return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  } catch { return dateKey; }
}

function groupByDate(videos: PortalVideo[]): { title: string; dateKey: string; data: PortalVideo[] }[] {
  const map = new Map<string, PortalVideo[]>();
  for (const v of videos) {
    const key = (v.uploaded_at || "").slice(0, 10);
    if (!key) continue;
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(v);
  }
  const sorted = Array.from(map.entries()).sort((a, b) => b[0].localeCompare(a[0]));
  return sorted.map(([dateKey, items]) => {
    items.sort((a, b) => (b.uploaded_at || "").localeCompare(a.uploaded_at || ""));
    return { title: formatDateHeader(dateKey), dateKey, data: items };
  });
}

export default function PortalVideosScreen() {
  const [data, setData] = useState<{ videos: PortalVideo[]; total: number }>({ videos: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [playingVideo, setPlayingVideo] = useState<PortalVideo | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await fetchPortalVideos();
      setData(d || { videos: [], total: 0 });
    } catch {
      setData({ videos: [], total: 0 });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const sections = useMemo(() => groupByDate(data.videos || []), [data]);

  if (loading) {
    return (
      <View style={s.root} testID="portal-videos-loading">
        <Header title="Service Videos" subtitle="Videos shared by your team" />
        <Loading />
      </View>
    );
  }

  return (
    <View style={s.root} testID="portal-videos-page">
      <Header title="Service Videos" subtitle={`${data.total} video${data.total !== 1 ? "s" : ""} shared`} />
      <SectionList
        testID="portal-videos-grouped"
        sections={sections}
        keyExtractor={(item) => item.video_id}
        stickySectionHeadersEnabled={false}
        contentContainerStyle={s.list}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />
        }
        renderSectionHeader={({ section }) => (
          <Text style={s.dateHeader} testID={`portal-videos-date-header-${section.dateKey}`}>
            {section.title}
          </Text>
        )}
        renderItem={({ item: v }) => (
          <TouchableOpacity
            style={s.videoRow}
            onPress={() => setPlayingVideo(v)}
            activeOpacity={0.7}
            testID={`portal-videos-item-${v.video_id}`}
          >
            <View style={s.playIcon}>
              <Ionicons name="play-circle" size={28} color="rgba(255,255,255,0.85)" />
            </View>
            <View style={{ flex: 1 }}>
              {v.caption ? <Text style={s.caption} numberOfLines={1}>{v.caption}</Text> : null}
              <Text style={s.meta}>
                {bytesToLabel(v.size_bytes)}
                {v.duration_seconds ? ` · ${durationLabel(v.duration_seconds)}` : ""}
                {v.uploaded_by_name ? ` · ${v.uploaded_by_name}` : ""}
              </Text>
              <Text style={s.date}>{relativeTime(v.uploaded_at)}</Text>
            </View>
            <Ionicons name="chevron-forward" size={18} color={colors.muted} />
          </TouchableOpacity>
        )}
        ListEmptyComponent={
          <View style={s.empty} testID="portal-videos-empty">
            <Ionicons name="videocam-off-outline" size={40} color={colors.muted} />
            <Text style={s.emptyTitle}>No videos shared yet</Text>
            <Text style={s.emptyBody}>
              When our team shares a video from a job or estimate, it will appear here.
            </Text>
          </View>
        }
      />
      <VideoPlayerModal
        visible={!!playingVideo}
        storagePath={playingVideo?.storage_path || null}
        caption={playingVideo?.caption}
        onClose={() => setPlayingVideo(null)}
      />
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  list: { padding: spacing.lg, paddingBottom: 120 },
  dateHeader: {
    fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface,
    marginTop: spacing.lg, marginBottom: spacing.sm,
  },
  videoRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 10, paddingHorizontal: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm,
  },
  playIcon: {
    width: 48, height: 36, backgroundColor: "#111",
    borderRadius: 6, alignItems: "center", justifyContent: "center",
  },
  caption: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, marginBottom: 1 },
  meta: { fontFamily: font.regular, fontSize: 10, color: colors.muted },
  date: { fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 1 },
  empty: { paddingVertical: 60, alignItems: "center" },
  emptyTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginTop: spacing.md },
  emptyBody: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4, textAlign: "center", paddingHorizontal: spacing.xl },
});
