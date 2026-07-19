/**
 * Phase 5B · Customer Portal — Videos screen.
 * Groups shareable videos by entity title, tap to play.
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import {
  fetchPortalVideos,
  bytesToLabel,
  durationLabel,
  relativeTime,
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

type VideoGroup = {
  kind: string;
  entity_id: string;
  entity_title: string;
  job_scheduled_date?: string;
  videos: PortalVideo[];
};

export default function PortalVideosScreen() {
  const [data, setData] = useState<{ videos: PortalVideo[]; total: number }>({
    videos: [],
    total: 0,
  });
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

  const groups: VideoGroup[] = useMemo(() => {
    const map = new Map<string, VideoGroup>();
    for (const v of data.videos || []) {
      const key = `${v.kind}:${v.entity_id}`;
      if (!map.has(key)) {
        map.set(key, {
          kind: v.kind,
          entity_id: v.entity_id,
          entity_title: v.entity_title,
          job_scheduled_date: v.job_scheduled_date,
          videos: [],
        });
      }
      map.get(key)!.videos.push(v);
    }
    const arr = Array.from(map.values());
    arr.sort((a, b) => {
      const ax = a.videos[0]?.uploaded_at || "";
      const bx = b.videos[0]?.uploaded_at || "";
      return bx.localeCompare(ax);
    });
    return arr;
  }, [data]);

  if (loading) {
    return (
      <View style={styles.root} testID="portal-videos-loading">
        <Header title="Service Videos" subtitle="Videos shared by your team" />
        <Loading />
      </View>
    );
  }

  return (
    <View style={styles.root} testID="portal-videos-page">
      <Header
        title="Service Videos"
        subtitle={`${data.total} video${data.total !== 1 ? "s" : ""} shared`}
      />
      <FlatList
        data={groups}
        keyExtractor={(g) => `${g.kind}:${g.entity_id}`}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              load();
            }}
          />
        }
        renderItem={({ item: g }) => (
          <View
            style={styles.groupCard}
            testID={`portal-video-group-${g.entity_id}`}
          >
            <View style={styles.groupHeader}>
              <Text style={styles.groupTitle} numberOfLines={1}>
                {g.entity_title}
              </Text>
              <Text style={styles.groupKind}>
                {g.kind === "estimate" ? "Estimate" : "Job"}
                {g.job_scheduled_date
                  ? ` · ${g.job_scheduled_date.slice(0, 10)}`
                  : ""}
              </Text>
            </View>
            {g.videos.map((v) => (
              <TouchableOpacity
                key={v.video_id}
                style={styles.videoRow}
                onPress={() => setPlayingVideo(v)}
                activeOpacity={0.7}
                testID={`portal-video-tile-${v.video_id}`}
              >
                <View style={styles.playIcon}>
                  <Ionicons
                    name="play-circle"
                    size={28}
                    color="rgba(255,255,255,0.85)"
                  />
                </View>
                <View style={{ flex: 1 }}>
                  {v.caption ? (
                    <Text style={styles.caption} numberOfLines={1}>
                      {v.caption}
                    </Text>
                  ) : null}
                  <Text style={styles.meta}>
                    {bytesToLabel(v.size_bytes)}
                    {v.duration_seconds
                      ? ` · ${durationLabel(v.duration_seconds)}`
                      : ""}
                    {v.uploaded_by_name ? ` · ${v.uploaded_by_name}` : ""}
                  </Text>
                  <Text style={styles.date}>
                    {relativeTime(v.uploaded_at)}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={18} color={colors.muted} />
              </TouchableOpacity>
            ))}
          </View>
        )}
        ListEmptyComponent={
          <View style={styles.empty} testID="portal-videos-empty">
            <Ionicons name="videocam-off-outline" size={40} color={colors.muted} />
            <Text style={styles.emptyTitle}>No videos shared yet</Text>
            <Text style={styles.emptyBody}>
              When our team shares a video from a job or estimate, it will
              appear here.
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

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  list: {
    padding: spacing.lg,
    paddingBottom: 120,
  },
  groupCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  groupHeader: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: 8,
    marginBottom: spacing.sm,
  },
  groupTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
    flex: 1,
  },
  groupKind: {
    fontFamily: font.semibold,
    fontSize: 10,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  videoRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  playIcon: {
    width: 48,
    height: 36,
    backgroundColor: "#111",
    borderRadius: 6,
    alignItems: "center",
    justifyContent: "center",
  },
  caption: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    marginBottom: 1,
  },
  meta: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
  },
  date: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
    marginTop: 1,
  },
  empty: {
    paddingVertical: 60,
    alignItems: "center",
  },
  emptyTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    marginTop: spacing.md,
  },
  emptyBody: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 4,
    textAlign: "center",
    paddingHorizontal: spacing.xl,
  },
});
