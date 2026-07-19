/**
 * Phase 5B · VideoMediaUploader — Reusable video tile grid + upload.
 * Integrates into job / estimate detail screens.
 */
import React, { useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Alert,
  ActivityIndicator,
  Dimensions,
} from "react-native";
import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import {
  VideoRecord,
  VideoEntity,
  uploadVideo,
  deleteVideo,
  patchVideoVisibility,
  bytesToLabel,
  durationLabel,
  relativeTime,
  OfflineError,
} from "@/src/api/media";
import VideoPlayerModal from "./VideoPlayerModal";

const MAX_DURATION_S = 180;
const TILE_W = (Dimensions.get("window").width - spacing.lg * 2 - spacing.md * 2) / 3;

type Props = {
  entityKind: VideoEntity;
  entityId: string;
  existingVideos: VideoRecord[];
  onUploaded: (video: VideoRecord) => void;
  onDeleted: (videoId: string) => void;
  onPatched?: (video: VideoRecord) => void;
  readonly?: boolean;
};

export default function VideoMediaUploader({
  entityKind,
  entityId,
  existingVideos = [],
  onUploaded,
  onDeleted,
  onPatched,
  readonly = false,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [err, setErr] = useState("");
  const [playingVideo, setPlayingVideo] = useState<VideoRecord | null>(null);

  const visibleVideos = useMemo(
    () => (existingVideos || []).filter((v) => !v?.is_deleted),
    [existingVideos],
  );
  const remaining = Math.max(0, 10 - visibleVideos.length);

  const pickAndUpload = async () => {
    setErr("");
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert(
          "Permission required",
          "Allow photo library access to pick a video.",
        );
        return;
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["videos"],
        allowsEditing: false,
        quality: 1,
      });
      if (result.canceled || !result.assets?.[0]) return;

      const asset = result.assets[0];
      const fileUri = asset.uri;
      const fileName = asset.fileName || fileUri.split("/").pop() || "video.mp4";
      const mimeType = asset.mimeType || "video/mp4";
      const fileSize = asset.fileSize || 0;
      const durationMs = asset.duration; // ms or undefined

      // Pre-flight: duration
      const durationSec = durationMs != null ? durationMs / 1000 : null;
      if (durationSec != null && durationSec > MAX_DURATION_S) {
        const m = Math.floor(durationSec / 60);
        const s = Math.round(durationSec % 60);
        setErr(
          `Video is ${m}:${String(s).padStart(2, "0")} — max 3:00.`,
        );
        return;
      }

      setBusy(true);
      setProgress(0);
      const body = await uploadVideo({
        kind: entityKind,
        entityId,
        fileUri,
        fileName,
        mimeType,
        fileSize,
        durationSeconds: durationSec,
        onProgress: setProgress,
      });
      onUploaded(body.video);
    } catch (e: any) {
      if (e instanceof OfflineError) {
        Alert.alert("Offline", e.message);
      } else {
        setErr(e.message || "Upload failed.");
      }
    } finally {
      setBusy(false);
      setProgress(0);
    }
  };

  const recordVideo = async () => {
    setErr("");
    try {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) {
        Alert.alert(
          "Permission required",
          "Allow camera access to record a video.",
        );
        return;
      }
      const result = await ImagePicker.launchCameraAsync({
        mediaTypes: ["videos"],
        allowsEditing: false,
        quality: 1,
        videoMaxDuration: MAX_DURATION_S,
      });
      if (result.canceled || !result.assets?.[0]) return;

      const asset = result.assets[0];
      const fileUri = asset.uri;
      const fileName = asset.fileName || "recording.mp4";
      const mimeType = asset.mimeType || "video/mp4";
      const fileSize = asset.fileSize || 0;
      const durationSec = asset.duration != null ? asset.duration / 1000 : null;

      setBusy(true);
      setProgress(0);
      const body = await uploadVideo({
        kind: entityKind,
        entityId,
        fileUri,
        fileName,
        mimeType,
        fileSize,
        durationSeconds: durationSec,
        onProgress: setProgress,
      });
      onUploaded(body.video);
    } catch (e: any) {
      if (e instanceof OfflineError) {
        Alert.alert("Offline", e.message);
      } else {
        setErr(e.message || "Upload failed.");
      }
    } finally {
      setBusy(false);
      setProgress(0);
    }
  };

  const handleToggleVisibility = async (v: VideoRecord) => {
    if (readonly) return;
    const nextVis = v.visibility === "customer" ? "internal" : "customer";
    try {
      const body = await patchVideoVisibility(
        entityKind,
        entityId,
        v.id,
        nextVis,
      );
      onPatched?.(body.video);
    } catch (e: any) {
      Alert.alert("Error", e.message || "Could not update visibility.");
    }
  };

  const handleDelete = (v: VideoRecord) => {
    if (readonly) return;
    Alert.alert("Delete video?", "This cannot be undone.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: async () => {
          try {
            await deleteVideo(entityKind, entityId, v.id);
            onDeleted(v.id);
          } catch (e: any) {
            Alert.alert("Error", e.message || "Delete failed.");
          }
        },
      },
    ]);
  };

  return (
    <View testID={`video-uploader-${entityKind}-${entityId}`}>
      {/* Section header */}
      <View style={styles.headerRow}>
        <View style={styles.headerLeft}>
          <Ionicons name="videocam-outline" size={14} color={colors.muted} />
          <Text style={styles.headerLabel}>
            Videos · {visibleVideos.length} of 10
          </Text>
        </View>
        {busy ? (
          <View style={styles.progressRow} testID="video-upload-progress">
            <ActivityIndicator size="small" color={colors.brand} />
            <Text style={styles.progressText}>{progress}%</Text>
          </View>
        ) : null}
      </View>

      {/* Error */}
      {err ? (
        <View style={styles.errorBox} testID="video-uploader-error">
          <Text style={styles.errorText}>{err}</Text>
        </View>
      ) : null}

      {/* Tile grid */}
      {visibleVideos.length > 0 ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.tileRow}
          testID="video-uploader-grid"
        >
          {visibleVideos.map((v) => (
            <VideoTile
              key={v.id}
              video={v}
              readonly={readonly}
              onPlay={() => setPlayingVideo(v)}
              onToggleVisibility={() => handleToggleVisibility(v)}
              onDelete={() => handleDelete(v)}
            />
          ))}
        </ScrollView>
      ) : null}

      {/* Upload buttons */}
      {!readonly && remaining > 0 ? (
        <View style={styles.uploadRow}>
          <TouchableOpacity
            style={[styles.uploadBtn, busy && { opacity: 0.5 }]}
            onPress={recordVideo}
            disabled={busy}
            activeOpacity={0.7}
            testID="video-upload-record"
          >
            <Ionicons name="videocam" size={14} color={colors.brand} />
            <Text style={styles.uploadBtnText}>Record</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.uploadBtn, busy && { opacity: 0.5 }]}
            onPress={pickAndUpload}
            disabled={busy}
            activeOpacity={0.7}
            testID="video-upload-pick"
          >
            <Ionicons name="folder-open-outline" size={14} color={colors.brand} />
            <Text style={styles.uploadBtnText}>
              {busy ? "Uploading…" : "Choose video"}
            </Text>
          </TouchableOpacity>
        </View>
      ) : null}

      {!readonly && remaining > 0 ? (
        <Text style={styles.hintText}>
          MP4 / MOV / WebM · up to 100 MB · up to 3 min
        </Text>
      ) : null}

      {/* Player modal */}
      <VideoPlayerModal
        visible={!!playingVideo}
        storagePath={playingVideo?.storage_path || null}
        caption={playingVideo?.caption}
        onClose={() => setPlayingVideo(null)}
      />
    </View>
  );
}

/* ── VideoTile ──────────────────────────────────────────────── */
function VideoTile({
  video,
  readonly,
  onPlay,
  onToggleVisibility,
  onDelete,
}: {
  video: VideoRecord;
  readonly: boolean;
  onPlay: () => void;
  onToggleVisibility: () => void;
  onDelete: () => void;
}) {
  const isCustomer = video.visibility === "customer";
  return (
    <View style={styles.tile} testID={`video-tile-${video.id}`}>
      {/* Poster / play area */}
      <TouchableOpacity
        style={styles.tilePoster}
        onPress={onPlay}
        activeOpacity={0.7}
        testID={`video-play-${video.id}`}
      >
        <Ionicons name="play-circle" size={36} color="rgba(255,255,255,0.85)" />
      </TouchableOpacity>

      {/* Meta */}
      <View style={styles.tileMeta}>
        <View style={styles.tileRow1}>
          <View
            style={[
              styles.visBadge,
              isCustomer ? styles.visBadgeCustomer : styles.visBadgeInternal,
            ]}
            testID={`video-vis-${video.id}`}
          >
            <Text
              style={[
                styles.visBadgeText,
                isCustomer && styles.visBadgeTextCustomer,
              ]}
            >
              {isCustomer ? "Shareable" : "Internal"}
            </Text>
          </View>
          <Text style={styles.sizeText}>
            {bytesToLabel(video.size_bytes)}
            {video.duration_seconds
              ? ` · ${durationLabel(video.duration_seconds)}`
              : ""}
          </Text>
        </View>
        <Text style={styles.uploaderText} numberOfLines={1}>
          {video.uploaded_by_name || "Uploaded"} · {relativeTime(video.uploaded_at)}
        </Text>
        {!readonly ? (
          <View style={styles.tileActions}>
            <TouchableOpacity
              onPress={onToggleVisibility}
              style={styles.tileActionBtn}
              testID={`video-toggle-vis-${video.id}`}
              hitSlop={6}
            >
              <Ionicons
                name={isCustomer ? "eye-off-outline" : "eye-outline"}
                size={13}
                color={colors.onSurface}
              />
              <Text style={styles.tileActionText}>
                {isCustomer ? "Internal" : "Share"}
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={onDelete}
              style={[styles.tileActionBtn, styles.tileActionDanger]}
              testID={`video-delete-${video.id}`}
              hitSlop={6}
            >
              <Ionicons name="trash-outline" size={13} color="#991B1B" />
              <Text style={[styles.tileActionText, { color: "#991B1B" }]}>
                Delete
              </Text>
            </TouchableOpacity>
          </View>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 6,
    marginTop: spacing.lg,
  },
  headerLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  headerLabel: {
    fontSize: 10,
    fontFamily: font.bold,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  progressRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  progressText: {
    fontSize: 11,
    fontFamily: font.semibold,
    color: colors.brand,
  },
  errorBox: {
    backgroundColor: "#FEE2E2",
    borderRadius: radius.sm,
    paddingHorizontal: 10,
    paddingVertical: 6,
    marginBottom: 8,
  },
  errorText: {
    fontSize: 11,
    fontFamily: font.regular,
    color: "#991B1B",
  },
  tileRow: {
    gap: spacing.sm,
    paddingBottom: 4,
  },
  tile: {
    width: TILE_W > 140 ? TILE_W : 140,
    borderRadius: radius.md,
    overflow: "hidden",
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  tilePoster: {
    height: 90,
    backgroundColor: "#111",
    alignItems: "center",
    justifyContent: "center",
  },
  tileMeta: {
    padding: 8,
  },
  tileRow1: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 2,
    flexWrap: "wrap",
  },
  visBadge: {
    paddingHorizontal: 5,
    paddingVertical: 1,
    borderRadius: 4,
    borderWidth: 1,
  },
  visBadgeInternal: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
  },
  visBadgeCustomer: {
    backgroundColor: "#DCFCE7",
    borderColor: "#86EFAC",
  },
  visBadgeText: {
    fontSize: 8,
    fontFamily: font.bold,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  visBadgeTextCustomer: {
    color: "#166534",
  },
  sizeText: {
    fontSize: 9,
    fontFamily: font.regular,
    color: colors.muted,
  },
  uploaderText: {
    fontSize: 9,
    fontFamily: font.regular,
    color: colors.muted,
    marginBottom: 4,
  },
  tileActions: {
    flexDirection: "row",
    gap: 6,
    marginTop: 2,
  },
  tileActionBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 4,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  tileActionDanger: {
    backgroundColor: "#FEF2F2",
    borderColor: "#FECACA",
  },
  tileActionText: {
    fontSize: 9,
    fontFamily: font.semibold,
    color: colors.onSurface,
  },
  uploadRow: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: 8,
  },
  uploadBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.md,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderStyle: "dashed",
    backgroundColor: colors.surfaceSecondary,
  },
  uploadBtnText: {
    fontSize: fontSize.sm,
    fontFamily: font.semibold,
    color: colors.onSurface,
  },
  hintText: {
    fontSize: 10,
    fontFamily: font.regular,
    color: colors.muted,
    marginTop: 4,
  },
});
