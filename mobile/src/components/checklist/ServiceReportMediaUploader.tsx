/**
 * Phase 27 · ServiceReportMediaUploader
 *
 * Unified photo + video media grid for service-report checkout.
 *
 * Features:
 * - Photo picker (camera / library) — up to 10 photos
 * - Video picker (camera / library) — up to 3 videos, ≤ 60s each
 * - Poster generation via expo-video-thumbnails
 * - Drag-reorder (long-press move up/down)
 * - Upload via POST /api/service-reports/{id}/media
 * - Reorder via PATCH /api/service-reports/{id}/media/reorder
 * - Tap video → native playback
 */
import React, { useState } from "react";
import {
  View, Text, StyleSheet, Pressable, Alert, ActivityIndicator, Dimensions,
} from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import * as VideoThumbnails from "expo-video-thumbnails";
import { Ionicons } from "@expo/vector-icons";

import { api_base, getAuthToken } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import {
  uploadServiceReportMedia, reorderServiceReportMedia,
  PHOTO_CAP, VIDEO_CAP, VIDEO_MAX_DURATION_S,
  PHOTO_MIMES, VIDEO_MIMES,
  SRMedia, OfflineError,
} from "@/src/api/serviceReportMedia";
import VideoPlayerModal from "@/src/components/media/VideoPlayerModal";

const W = Dimensions.get("window").width;
const TILE_W = (W - spacing.lg * 2 - spacing.sm * 2) / 3;

type Props = {
  reportId: string;
  photos: SRMedia[];
  videos: SRMedia[];
  onPhotosChange: (next: SRMedia[]) => void;
  onVideosChange: (next: SRMedia[]) => void;
  readonly?: boolean;
};

export default function ServiceReportMediaUploader({
  reportId, photos, videos, onPhotosChange, onVideosChange, readonly = false,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [err, setErr] = useState("");
  const [playingUrl, setPlayingUrl] = useState<string | null>(null);
  const [reorderMode, setReorderMode] = useState(false);

  const photoCount = photos.length;
  const videoCount = videos.length;

  /* ── Photo picker ──────────────────────────────────────────── */
  const pickPhoto = async (fromCamera: boolean) => {
    if (readonly || photoCount >= PHOTO_CAP) {
      Alert.alert("Limit reached", `Maximum ${PHOTO_CAP} photos per visit.`);
      return;
    }
    setErr("");
    const perm = fromCamera
      ? await ImagePicker.requestCameraPermissionsAsync()
      : await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) { Alert.alert("Permission needed"); return; }

    const result = fromCamera
      ? await ImagePicker.launchCameraAsync({ quality: 0.7, mediaTypes: ["images"] })
      : await ImagePicker.launchImageLibraryAsync({ quality: 0.7, mediaTypes: ["images"] });
    if (result.canceled || !result.assets?.[0]) return;

    const asset = result.assets[0];
    const mime = asset.mimeType || "image/jpeg";
    if (!PHOTO_MIMES.has(mime)) {
      setErr(`Unsupported format: ${mime}. Use JPG, PNG, WebP, or HEIC.`);
      return;
    }

    setBusy(true); setProgress(0);
    try {
      const resp = await uploadServiceReportMedia({
        reportId,
        fileUri: asset.uri,
        fileName: asset.fileName || "photo.jpg",
        mimeType: mime,
        fileSize: asset.fileSize || 0,
        kind: "photo",
        onProgress: setProgress,
      });
      const newMedia: SRMedia = { url: resp.url || resp.media?.url, kind: "photo" };
      onPhotosChange([...photos, newMedia]);
    } catch (e: any) {
      if (e instanceof OfflineError) Alert.alert("Offline", e.message);
      else setErr(e.message || "Photo upload failed.");
    } finally { setBusy(false); setProgress(0); }
  };

  /* ── Video picker ──────────────────────────────────────────── */
  const pickVideo = async (fromCamera: boolean) => {
    if (readonly || videoCount >= VIDEO_CAP) {
      Alert.alert("Limit reached", `Maximum ${VIDEO_CAP} videos per visit.`);
      return;
    }
    setErr("");
    const perm = fromCamera
      ? await ImagePicker.requestCameraPermissionsAsync()
      : await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) { Alert.alert("Permission needed"); return; }

    const result = fromCamera
      ? await ImagePicker.launchCameraAsync({
          mediaTypes: ["videos"],
          videoMaxDuration: VIDEO_MAX_DURATION_S,
          allowsEditing: false,
          quality: 1,
        })
      : await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ["videos"],
          allowsEditing: false,
          quality: 1,
        });
    if (result.canceled || !result.assets?.[0]) return;

    const asset = result.assets[0];
    const mime = asset.mimeType || "video/mp4";
    if (!VIDEO_MIMES.has(mime)) {
      setErr(`Unsupported format: ${mime}. Use MP4, MOV, WebM, M4V, or AVI.`);
      return;
    }

    // Client-side duration validation
    const durationS = asset.duration != null ? asset.duration / 1000 : null;
    if (durationS != null && durationS > VIDEO_MAX_DURATION_S) {
      const m = Math.floor(durationS / 60);
      const s = Math.round(durationS % 60);
      setErr(`Video is ${m}:${String(s).padStart(2, "0")} — max 1:00.`);
      Alert.alert(
        "Video too long",
        `Maximum duration is ${VIDEO_MAX_DURATION_S} seconds. This video is ${m}:${String(s).padStart(2, "0")}.`,
      );
      return;
    }

    // Generate poster thumbnail
    let posterUrl: string | null = null;
    try {
      const thumb = await VideoThumbnails.getThumbnailAsync(asset.uri, { time: 500 });
      if (thumb?.uri) posterUrl = thumb.uri;
    } catch { /* poster generation failed — acceptable, backend handles null */ }

    setBusy(true); setProgress(0);
    try {
      const resp = await uploadServiceReportMedia({
        reportId,
        fileUri: asset.uri,
        fileName: asset.fileName || "video.mp4",
        mimeType: mime,
        fileSize: asset.fileSize || 0,
        kind: "video",
        durationSeconds: durationS,
        posterUrl,
        onProgress: setProgress,
      });
      const newMedia: SRMedia = {
        url: resp.url || resp.media?.url,
        kind: "video",
        poster_url: resp.poster_url || resp.media?.poster_url || posterUrl,
        duration_seconds: durationS,
        content_type: mime,
      };
      onVideosChange([...videos, newMedia]);
    } catch (e: any) {
      if (e instanceof OfflineError) Alert.alert("Offline", e.message);
      else setErr(e.message || "Video upload failed.");
    } finally { setBusy(false); setProgress(0); }
  };

  /* ── Reorder helpers ───────────────────────────────────────── */
  const moveItem = (list: SRMedia[], idx: number, dir: -1 | 1, setter: (l: SRMedia[]) => void) => {
    const next = [...list];
    const target = idx + dir;
    if (target < 0 || target >= next.length) return;
    [next[idx], next[target]] = [next[target], next[idx]];
    setter(next);
  };

  const saveOrder = async () => {
    try {
      await reorderServiceReportMedia(
        reportId,
        photos.map((p) => p.url),
        videos.map((v) => v.url),
      );
      setReorderMode(false);
      Alert.alert("Order saved");
    } catch (e: any) {
      Alert.alert("Reorder failed", e.message || "Try again.");
    }
  };

  /* ── Build streaming URL ───────────────────────────────────── */
  const buildStreamUrl = async (url: string): Promise<string> => {
    if (url.startsWith("http")) return url;
    const token = await getAuthToken();
    const base = api_base().replace(/\/api\/?$/, "");
    return `${base}${url}?auth=${encodeURIComponent(token)}`;
  };

  const playVideo = async (v: SRMedia) => {
    try {
      const streamUrl = await buildStreamUrl(v.url);
      setPlayingUrl(streamUrl);
    } catch { setPlayingUrl(v.url); }
  };

  /* ── Resolve image URL ─────────────────────────────────────── */
  const resolveUrl = (u: string) => {
    if (!u) return "";
    if (u.startsWith("http") || u.startsWith("data:")) return u;
    const base = api_base().replace(/\/api\/?$/, "");
    return `${base}${u}`;
  };

  /* ── Render ────────────────────────────────────────────────── */
  return (
    <View testID="svc-report-media-uploader">
      {/* Section header */}
      <View style={s.headerRow}>
        <View style={s.headerLeft}>
          <Ionicons name="images-outline" size={14} color={colors.muted} />
          <Text style={s.headerLabel}>
            Photos {photoCount}/{PHOTO_CAP} · Videos {videoCount}/{VIDEO_CAP}
          </Text>
        </View>
        {busy && (
          <View style={s.progressRow}>
            <ActivityIndicator size="small" color={colors.brand} />
            <Text style={s.progressText}>{progress}%</Text>
          </View>
        )}
      </View>

      {/* Error */}
      {err ? (
        <View style={s.errorBox} testID="svc-report-video-duration-error">
          <Text style={s.errorText}>{err}</Text>
          <Pressable onPress={() => setErr("")} hitSlop={8}>
            <Ionicons name="close" size={14} color="#991B1B" />
          </Pressable>
        </View>
      ) : null}

      {/* Photo grid */}
      {photos.length > 0 && (
        <View style={s.sectionLabel}>
          <Text style={s.sectionLabelText}>PHOTOS</Text>
        </View>
      )}
      <View style={s.grid}>
        {photos.map((p, i) => (
          <Pressable
            key={p.url + i}
            style={s.tile}
            testID={`svc-report-media-tile-${i}`}
            onLongPress={() => !readonly && setReorderMode(true)}
          >
            <Image source={{ uri: resolveUrl(p.url) }} style={s.tileImage} contentFit="cover" />
            {reorderMode && !readonly && (
              <View style={s.reorderOverlay} testID={`svc-report-media-reorder-handle-${i}`}>
                <Pressable
                  style={s.reorderBtn}
                  onPress={() => moveItem(photos, i, -1, onPhotosChange)}
                  disabled={i === 0}
                >
                  <Ionicons name="chevron-up" size={16} color={i === 0 ? "#999" : "#fff"} />
                </Pressable>
                <Pressable
                  style={s.reorderBtn}
                  onPress={() => moveItem(photos, i, 1, onPhotosChange)}
                  disabled={i === photos.length - 1}
                >
                  <Ionicons name="chevron-down" size={16} color={i === photos.length - 1 ? "#999" : "#fff"} />
                </Pressable>
              </View>
            )}
          </Pressable>
        ))}
      </View>

      {/* Video grid */}
      {videos.length > 0 && (
        <View style={s.sectionLabel}>
          <Text style={s.sectionLabelText}>VIDEOS</Text>
        </View>
      )}
      <View style={s.grid}>
        {videos.map((v, i) => {
          const vidIdx = photos.length + i;
          return (
            <Pressable
              key={v.url + i}
              style={s.tile}
              testID={`svc-report-media-tile-${vidIdx}`}
              onPress={() => playVideo(v)}
              onLongPress={() => !readonly && setReorderMode(true)}
            >
              {v.poster_url ? (
                <Image source={{ uri: resolveUrl(v.poster_url) }} style={s.tileImage} contentFit="cover" />
              ) : (
                <View style={[s.tileImage, s.videoPosterFallback]} />
              )}
              <View style={s.playOverlay}>
                <Ionicons name="play-circle" size={28} color="rgba(255,255,255,0.9)" />
              </View>
              {v.duration_seconds != null && (
                <View style={s.durationBadge}>
                  <Text style={s.durationText}>
                    {Math.floor(v.duration_seconds / 60)}:{String(Math.round(v.duration_seconds % 60)).padStart(2, "0")}
                  </Text>
                </View>
              )}
              {reorderMode && !readonly && (
                <View style={s.reorderOverlay} testID={`svc-report-media-reorder-handle-${vidIdx}`}>
                  <Pressable
                    style={s.reorderBtn}
                    onPress={() => moveItem(videos, i, -1, onVideosChange)}
                    disabled={i === 0}
                  >
                    <Ionicons name="chevron-up" size={16} color={i === 0 ? "#999" : "#fff"} />
                  </Pressable>
                  <Pressable
                    style={s.reorderBtn}
                    onPress={() => moveItem(videos, i, 1, onVideosChange)}
                    disabled={i === videos.length - 1}
                  >
                    <Ionicons name="chevron-down" size={16} color={i === videos.length - 1 ? "#999" : "#fff"} />
                  </Pressable>
                </View>
              )}
            </Pressable>
          );
        })}
      </View>

      {/* Reorder save / cancel */}
      {reorderMode && !readonly && (
        <View style={s.reorderBar}>
          <Pressable style={s.reorderCancelBtn} onPress={() => setReorderMode(false)}>
            <Text style={s.reorderCancelText}>Cancel</Text>
          </Pressable>
          <Pressable style={s.reorderSaveBtn} onPress={saveOrder}>
            <Ionicons name="checkmark" size={14} color="#fff" />
            <Text style={s.reorderSaveText}>Save order</Text>
          </Pressable>
        </View>
      )}

      {/* Upload buttons */}
      {!readonly && !reorderMode && (
        <View style={s.uploadSection}>
          <View style={s.uploadRow}>
            <Pressable
              style={[s.uploadBtn, busy && { opacity: 0.5 }]}
              onPress={() => pickPhoto(true)}
              disabled={busy}
              testID="svc-report-photo-picker"
            >
              <Ionicons name="camera-outline" size={16} color={colors.brand} />
              <Text style={s.uploadBtnText}>Photo</Text>
            </Pressable>
            <Pressable
              style={[s.uploadBtn, busy && { opacity: 0.5 }]}
              onPress={() => pickPhoto(false)}
              disabled={busy}
              testID="svc-report-photo-library"
            >
              <Ionicons name="images-outline" size={16} color={colors.brand} />
              <Text style={s.uploadBtnText}>Library</Text>
            </Pressable>
            <Pressable
              style={[s.uploadBtn, s.uploadBtnVideo, busy && { opacity: 0.5 }]}
              onPress={() => pickVideo(true)}
              disabled={busy}
              testID="svc-report-video-picker"
            >
              <Ionicons name="videocam-outline" size={16} color="#7C3AED" />
              <Text style={[s.uploadBtnText, { color: "#7C3AED" }]}>Record</Text>
            </Pressable>
            <Pressable
              style={[s.uploadBtn, s.uploadBtnVideo, busy && { opacity: 0.5 }]}
              onPress={() => pickVideo(false)}
              disabled={busy}
              testID="svc-report-video-library"
            >
              <Ionicons name="film-outline" size={16} color="#7C3AED" />
              <Text style={[s.uploadBtnText, { color: "#7C3AED" }]}>Video</Text>
            </Pressable>
          </View>
          <Text style={s.hintText}>
            Photos: JPG/PNG/WebP/HEIC (20 MB) · Videos: MP4/MOV/WebM (100 MB, 60s max)
          </Text>
        </View>
      )}

      {/* Video player modal */}
      <VideoPlayerModal
        visible={!!playingUrl}
        storagePath={playingUrl || ""}
        onClose={() => setPlayingUrl(null)}
      />
    </View>
  );
}

/* ── Styles ──────────────────────────────────────────────────────── */
const s = StyleSheet.create({
  headerRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginBottom: 6,
  },
  headerLeft: { flexDirection: "row", alignItems: "center", gap: 6 },
  headerLabel: {
    fontSize: 10, fontFamily: font.bold, color: colors.muted,
    textTransform: "uppercase", letterSpacing: 0.5,
  },
  progressRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  progressText: { fontSize: 11, fontFamily: font.semibold, color: colors.brand },
  errorBox: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: "#FEE2E2", borderRadius: radius.sm,
    paddingHorizontal: 10, paddingVertical: 6, marginBottom: 8,
  },
  errorText: { flex: 1, fontSize: 11, fontFamily: font.regular, color: "#991B1B" },
  sectionLabel: { marginTop: spacing.sm, marginBottom: 4 },
  sectionLabelText: {
    fontSize: 9, fontFamily: font.bold, color: colors.muted,
    textTransform: "uppercase", letterSpacing: 1,
  },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  tile: {
    width: TILE_W, height: TILE_W, borderRadius: radius.md, overflow: "hidden",
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
  },
  tileImage: { width: "100%", height: "100%", backgroundColor: colors.surfaceSecondary },
  videoPosterFallback: { backgroundColor: "#1a1a2e" },
  playOverlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center", justifyContent: "center",
    backgroundColor: "rgba(0,0,0,0.2)",
  },
  durationBadge: {
    position: "absolute", bottom: 4, right: 4,
    backgroundColor: "rgba(0,0,0,0.7)", borderRadius: 4,
    paddingHorizontal: 5, paddingVertical: 1,
  },
  durationText: { fontSize: 9, fontFamily: font.bold, color: "#fff" },
  reorderOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.45)",
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  reorderBtn: {
    width: 28, height: 28, borderRadius: 14,
    backgroundColor: "rgba(0,0,0,0.5)", alignItems: "center", justifyContent: "center",
  },
  reorderBar: {
    flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm,
    justifyContent: "flex-end",
  },
  reorderCancelBtn: { paddingHorizontal: 12, paddingVertical: 8 },
  reorderCancelText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted },
  reorderSaveBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brand, paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: radius.md,
  },
  reorderSaveText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  uploadSection: { marginTop: spacing.sm },
  uploadRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  uploadBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 8,
    borderRadius: radius.md, borderWidth: 1.5, borderStyle: "dashed",
    borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  uploadBtnVideo: { borderColor: "#DDD6FE" },
  uploadBtnText: { fontSize: fontSize.sm, fontFamily: font.semibold, color: colors.onSurface },
  hintText: { fontSize: 9, fontFamily: font.regular, color: colors.muted, marginTop: 4 },
});
