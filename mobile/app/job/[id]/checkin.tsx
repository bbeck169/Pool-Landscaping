/**
 * Check-In Composer · Tech check-in flow for public customer feed.
 *
 * Route: /job/{id}/checkin
 *
 * Two-step submission:
 *   1. POST /api/checkins  { job_id, latitude, longitude, note, photo_file_ids }
 *   2. POST /api/checkins/{checkin_id}/submit-public  (empty body)
 *
 * Photos upload via /api/files/upload with purpose='public_checkin'.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView,
  ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useToast } from "@/src/components/ToastProvider";
import { geolocate, GeolocateResult } from "@/src/utils/geolocate";
import { uploadFile, FileRecord } from "@/src/api/files";
import { pickImagesMulti } from "@/src/lib/pickImages";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";

const MAX_PHOTOS = 5;
const NOTE_MAX = 2000;

type PhotoSlot = {
  localUri: string;
  fileId: string | null;
  uploading: boolean;
  progress: number;
  error: string | null;
};

export default function CheckinComposer() {
  const { id: jobId } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { showToast } = useToast();

  // GPS
  const [gps, setGps] = useState<GeolocateResult | null>(null);
  const [gpsLoading, setGpsLoading] = useState(true);

  // Note
  const [note, setNote] = useState("");

  // Photos
  const [photos, setPhotos] = useState<PhotoSlot[]>([]);

  // Submit
  const [submitting, setSubmitting] = useState(false);

  // ── AI Write state ──────────────────────────────────────────────
  // Pattern A: create a draft check-in on first AI Write press,
  // then reuse it for the final submit-public step.
  const [draftCheckinId, setDraftCheckinId] = useState<string | null>(null);
  const [aiState, setAiState] = useState<"write" | "busy" | "undo">("write");
  const [preAiValue, setPreAiValue] = useState<string | null>(null);

  // ── GPS capture on mount ────────────────────────────────────────
  const captureGps = useCallback(async () => {
    setGpsLoading(true);
    const result = await geolocate(6000);
    setGps(result);
    setGpsLoading(false);
  }, []);

  useEffect(() => { captureGps(); }, [captureGps]);

  const gpsLocked = gps?.lat != null && gps?.lng != null;

  // ── Photo picking ───────────────────────────────────────────────
  const pickPhoto = async (source: "camera" | "library") => {
    if (photos.length >= MAX_PHOTOS) return;
    try {
      const perm = source === "camera"
        ? await ImagePicker.requestCameraPermissionsAsync()
        : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        showToast("Permission required to add photos");
        return;
      }
      // TD-88e — library is multi-select (cap = MAX_PHOTOS - photos.length);
      // camera stays single-shot.
      let uris: string[];
      if (source === "camera") {
        const opts: ImagePicker.ImagePickerOptions = { quality: 0.7, allowsEditing: false };
        const result = await ImagePicker.launchCameraAsync(opts);
        if (result.canceled || !result.assets?.[0]) return;
        uris = [result.assets[0].uri];
      } else {
        const assets = await pickImagesMulti({ remainingCap: MAX_PHOTOS - photos.length, quality: 0.7 });
        if (!assets) return;
        uris = assets.map((a) => a.uri);
      }

      const base = photos.length; // index of the first new slot
      const slots: PhotoSlot[] = uris.map((localUri) => ({
        localUri,
        fileId: null,
        uploading: true,
        progress: 0,
        error: null,
      }));
      setPhotos((prev) => [...prev, ...slots]);

      // Upload each via /api/files/upload with purpose='public_checkin'
      for (let i = 0; i < uris.length; i++) {
        const idx = base + i;
        try {
          const rec: FileRecord = await uploadFile({
            uri: uris[i],
            name: `checkin_${Date.now()}_${i}.jpg`,
            type: "image/jpeg",
            purpose: "public_checkin",
            onProgress: (pct) => {
              setPhotos((prev) => prev.map((p, j) =>
                j === idx ? { ...p, progress: pct } : p
              ));
            },
          });
          setPhotos((prev) => prev.map((p, j) =>
            j === idx ? { ...p, fileId: rec.id, uploading: false, progress: 100 } : p
          ));
        } catch (e: any) {
          setPhotos((prev) => prev.map((p, j) =>
            j === idx ? { ...p, uploading: false, error: e?.message || "Upload failed" } : p
          ));
        }
      }
    } catch {
      // swallow — user can retry
    }
  };

  const removePhoto = (idx: number) => {
    setPhotos((prev) => prev.filter((_, i) => i !== idx));
  };

  const retryPhoto = async (idx: number) => {
    const slot = photos[idx];
    if (!slot) return;
    setPhotos((prev) => prev.map((p, i) =>
      i === idx ? { ...p, uploading: true, error: null, progress: 0 } : p
    ));
    try {
      const rec = await uploadFile({
        uri: slot.localUri,
        name: `checkin_${Date.now()}.jpg`,
        type: "image/jpeg",
        purpose: "public_checkin",
        onProgress: (pct) => {
          setPhotos((prev) => prev.map((p, i) =>
            i === idx ? { ...p, progress: pct } : p
          ));
        },
      });
      setPhotos((prev) => prev.map((p, i) =>
        i === idx ? { ...p, fileId: rec.id, uploading: false, progress: 100 } : p
      ));
    } catch (e: any) {
      setPhotos((prev) => prev.map((p, i) =>
        i === idx ? { ...p, uploading: false, error: e?.message || "Upload failed" } : p
      ));
    }
  };

  // ── AI Write: ensure draft exists ────────────────────────────────
  const ensureDraft = async (): Promise<string | null> => {
    if (draftCheckinId) return draftCheckinId;
    if (!gps?.lat || !gps?.lng) {
      showToast("GPS required before AI Write", "error");
      return null;
    }
    if (photos.length === 0 || !photos.every((p) => p.fileId && !p.uploading && !p.error)) {
      showToast("Upload at least 1 photo before AI Write", "error");
      return null;
    }
    try {
      const body = {
        job_id: jobId,
        latitude: gps.lat,
        longitude: gps.lng,
        note: note.trim() || "(pending AI description)",
        photo_file_ids: photos.map((p) => p.fileId).filter(Boolean),
      };
      const checkin: any = await api.post("/checkins", body);
      const id = checkin?.id;
      if (!id) throw new Error("No checkin_id in response");
      setDraftCheckinId(id);
      return id;
    } catch (e: any) {
      showToast(e?.message || "Failed to create draft check-in", "error");
      return null;
    }
  };

  // ── AI Write handler ────────────────────────────────────────────
  const handleAiWrite = async () => {
    if (aiState === "busy") return;
    if (aiState === "undo") {
      // Undo: restore pre-AI text
      setNote(preAiValue ?? "");
      setPreAiValue(null);
      setAiState("write");
      return;
    }
    // Write mode: create draft if needed, then call AI endpoint
    setAiState("busy");
    try {
      const checkinId = await ensureDraft();
      if (!checkinId) { setAiState("write"); return; }

      const res: any = await api.post(`/checkins/${checkinId}/ai-description`, {});
      const text = res?.description;
      if (!text) {
        showToast("AI Write failed. Please write manually.", "error");
        setAiState("write");
        return;
      }
      setPreAiValue(note); // stash current text for undo
      setNote(text);
      setAiState("undo");
    } catch (e: any) {
      const detail = e?.detail || e?.body?.detail;
      if (e?.status === 429 || detail?.code === "rate_limit_exceeded") {
        const retryAfter = detail?.retry_after_seconds;
        const mins = retryAfter ? Math.ceil(retryAfter / 60) : 60;
        showToast(`AI Write rate limit reached. Try again in ${mins} minutes.`, "error");
      } else {
        showToast("AI Write failed. Please write manually.", "error");
      }
      setAiState("write");
    }
  };

  // ── Submit validation ───────────────────────────────────────────
  const allPhotosUploaded = photos.length > 0 && photos.every((p) => p.fileId && !p.uploading && !p.error);
  const noteValid = note.trim().length >= 1 && note.trim().length <= NOTE_MAX;
  const canSubmit = gpsLocked && noteValid && allPhotosUploaded && !submitting;

  // ── Two-step submission ─────────────────────────────────────────
  const handleSubmit = async () => {
    if (!canSubmit || !gps?.lat || !gps?.lng) return;
    setSubmitting(true);
    try {
      let checkinId = draftCheckinId;

      if (checkinId) {
        // Draft already exists (AI Write created it) — update with final note + photos.
        await api.patch(`/checkins/${checkinId}`, {
          note: note.trim(),
          photo_file_ids: photos.map((p) => p.fileId).filter(Boolean),
          latitude: gps.lat,
          longitude: gps.lng,
        });
      } else {
        // No draft yet — create the check-in from scratch.
        const body = {
          job_id: jobId,
          latitude: gps.lat,
          longitude: gps.lng,
          note: note.trim(),
          photo_file_ids: photos.map((p) => p.fileId).filter(Boolean),
        };
        const checkin: any = await api.post("/checkins", body);
        checkinId = checkin?.id;
        if (!checkinId) throw new Error("No checkin_id in response");
      }

      // Step 2: Submit for public review
      try {
        await api.post(`/checkins/${checkinId}/submit-public`, {});
        showToast("Check-in submitted for review");
        router.back();
      } catch {
        // Step 2 failed — check-in saved but not submitted
        showToast("Check-in saved but not submitted for review — retry later", "warning");
        router.back();
      }
    } catch (e: any) {
      // Step 1 failed — stay on composer
      showToast(e?.message || "Failed to create check-in", "error");
    } finally {
      setSubmitting(false);
    }
  };

  // ── GPS status text ─────────────────────────────────────────────
  const gpsStatusText = gpsLoading
    ? "Acquiring GPS…"
    : gpsLocked
      ? `${gps!.lat!.toFixed(5)}, ${gps!.lng!.toFixed(5)}`
      : `GPS unavailable: ${gps?.reason || "unknown"}`;

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: colors.background }}
      behavior={Platform.OS === "ios" ? "padding" : "height"}
    >
      <View style={[s.header, { paddingTop: insets.top + 8 }]}>
        <Pressable onPress={() => router.back()} style={s.backBtn} testID="checkin-back-btn">
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={s.headerTitle}>Log Check-In</Text>
        <View style={{ width: 36 }} />
      </View>

      <ScrollView
        contentContainerStyle={[s.content, { paddingBottom: insets.bottom + 100 }]}
        keyboardShouldPersistTaps="handled"
        testID="checkin-scroll"
      >
        {/* GPS section */}
        <View style={s.section} testID="checkin-gps-section">
          <View style={s.sectionHeader}>
            <Ionicons name="location" size={18} color={gpsLocked ? colors.success : colors.muted} />
            <Text style={s.sectionLabel}>Location</Text>
          </View>
          <View style={s.gpsRow}>
            {gpsLoading ? (
              <ActivityIndicator size="small" color={colors.brand} testID="checkin-gps-loading" />
            ) : (
              <Ionicons
                name={gpsLocked ? "checkmark-circle" : "alert-circle"}
                size={16}
                color={gpsLocked ? colors.success : "#B91C1C"}
              />
            )}
            <Text style={[s.gpsText, !gpsLocked && !gpsLoading && { color: "#B91C1C" }]} testID="checkin-gps-status">
              {gpsStatusText}
            </Text>
          </View>
          <Pressable onPress={captureGps} disabled={gpsLoading} style={s.recaptureBtn} testID="checkin-gps-recapture-btn">
            <Ionicons name="refresh" size={14} color={colors.brand} />
            <Text style={s.recaptureText}>Recapture</Text>
          </Pressable>
        </View>

        {/* Note section */}
        <View style={s.section} testID="checkin-note-section">
          <View style={s.sectionHeader}>
            <Ionicons name="document-text-outline" size={18} color={colors.muted} />
            <Text style={s.sectionLabel}>Note</Text>
            <Pressable
              style={[
                s.aiWriteBtn,
                aiState === "undo" && s.aiWriteBtnUndo,
                aiState === "busy" && { opacity: 0.6 },
              ]}
              onPress={handleAiWrite}
              disabled={aiState === "busy" || submitting}
              accessibilityState={{ selected: aiState === "undo" }}
              testID="checkin-ai-write-btn"
            >
              {aiState === "busy" ? (
                <ActivityIndicator size={12} color="#7C3AED" testID="checkin-ai-write-btn-icon" />
              ) : aiState === "undo" ? (
                <Ionicons name="arrow-undo" size={14} color="#7C3AED" testID="checkin-ai-write-btn-icon" />
              ) : (
                <Text style={s.aiWriteSparkle} testID="checkin-ai-write-btn-icon">✨</Text>
              )}
              <Text style={s.aiWriteBtnText}>
                {aiState === "undo" ? "Undo AI" : "AI Write"}
              </Text>
            </Pressable>
            <Text style={s.charCount}>{note.length}/{NOTE_MAX}</Text>
          </View>
          <AppTextInput
            style={s.noteInput}
            value={note}
            onChangeText={(t) => setNote(t.slice(0, NOTE_MAX))}
            placeholder="Describe the work performed, observations, conditions…"
            placeholderTextColor={colors.muted}
            multiline
            numberOfLines={5}
            textAlignVertical="top"
            testID="checkin-note-input"
          />
        </View>

        {/* Photo section */}
        <View style={s.section} testID="checkin-photo-section">
          <View style={s.sectionHeader}>
            <Ionicons name="camera-outline" size={18} color={colors.muted} />
            <Text style={s.sectionLabel}>Photos ({photos.length}/{MAX_PHOTOS})</Text>
          </View>

          {/* Photo thumbnails */}
          <View style={s.photoGrid} testID="checkin-photo-picker">
            {photos.map((p, i) => (
              <View key={`photo-${i}`} style={s.thumbWrap} testID={`checkin-photo-thumb-${i}`}>
                <Image source={{ uri: p.localUri }} style={s.thumbImg} contentFit="cover" />
                {p.uploading ? (
                  <View style={s.thumbOverlay}>
                    <ActivityIndicator size="small" color="#fff" />
                    <Text style={s.thumbProgressText}>{p.progress}%</Text>
                  </View>
                ) : p.error ? (
                  <Pressable style={s.thumbOverlayError} onPress={() => retryPhoto(i)} testID={`checkin-photo-retry-${i}`}>
                    <Ionicons name="refresh" size={18} color="#fff" />
                    <Text style={s.thumbErrorText}>Retry</Text>
                  </Pressable>
                ) : null}
                <Pressable
                  style={s.thumbRemove}
                  onPress={() => removePhoto(i)}
                  hitSlop={8}
                  testID={`checkin-photo-remove-${i}`}
                >
                  <Ionicons name="close-circle" size={22} color="#fff" />
                </Pressable>
              </View>
            ))}

            {/* Add photo buttons */}
            {photos.length < MAX_PHOTOS ? (
              <View style={s.addPhotoBtns}>
                <Pressable style={s.addPhotoBtn} onPress={() => pickPhoto("camera")} testID="checkin-photo-camera-btn">
                  <Ionicons name="camera" size={22} color={colors.brand} />
                  <Text style={s.addPhotoBtnText}>Camera</Text>
                </Pressable>
                <Pressable style={s.addPhotoBtn} onPress={() => pickPhoto("library")} testID="checkin-photo-library-btn">
                  <Ionicons name="images" size={22} color={colors.brand} />
                  <Text style={s.addPhotoBtnText}>Library</Text>
                </Pressable>
              </View>
            ) : null}
          </View>

          {photos.some((p) => p.error) ? (
            <Text style={s.photoError} testID="checkin-photo-error">
              Some photos failed to upload. Retry or remove them before submitting.
            </Text>
          ) : null}
        </View>

        {/* Validation hints */}
        {!gpsLocked && !gpsLoading ? (
          <View style={s.hintRow}>
            <Ionicons name="warning" size={14} color="#B45309" />
            <Text style={s.hintText}>GPS required — tap Recapture</Text>
          </View>
        ) : null}
        {note.trim().length === 0 ? (
          <View style={s.hintRow}>
            <Ionicons name="warning" size={14} color="#B45309" />
            <Text style={s.hintText}>Note is required</Text>
          </View>
        ) : null}
        {photos.length === 0 ? (
          <View style={s.hintRow}>
            <Ionicons name="warning" size={14} color="#B45309" />
            <Text style={s.hintText}>At least 1 photo required</Text>
          </View>
        ) : null}
      </ScrollView>

      {/* Submit footer */}
      <View style={[s.footer, { paddingBottom: insets.bottom + spacing.md }]}>
        <Pressable
          style={[s.submitBtn, !canSubmit && s.submitBtnDisabled]}
          onPress={handleSubmit}
          disabled={!canSubmit}
          testID="checkin-submit-btn"
        >
          {submitting ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <>
              <Ionicons name="send" size={18} color="#fff" />
              <Text style={s.submitBtnText}>Submit Check-In</Text>
            </>
          )}
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  backBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  headerTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  content: { padding: spacing.md, gap: spacing.md },
  section: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: spacing.sm,
  },
  sectionLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, flex: 1 },
  charCount: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  aiWriteBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingVertical: 5,
    paddingHorizontal: 10,
    borderRadius: 14,
    backgroundColor: "#F3EAFF",
    borderWidth: 1,
    borderColor: "#D8B4FE",
  },
  aiWriteBtnUndo: {
    backgroundColor: "#EDE9FE",
    borderColor: "#C4B5FD",
  },
  aiWriteSparkle: { fontSize: 12 },
  aiWriteBtnText: { fontFamily: font.bold, fontSize: 11, color: "#7C3AED", letterSpacing: 0.3 },
  gpsRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  gpsText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  recaptureBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: spacing.sm,
    alignSelf: "flex-start",
    paddingVertical: 4,
    paddingHorizontal: 8,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  recaptureText: { fontFamily: font.medium, fontSize: fontSize.xs, color: colors.brand },
  noteInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    padding: spacing.sm,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    minHeight: 120,
    backgroundColor: colors.background,
  },
  photoGrid: { gap: spacing.sm },
  thumbWrap: {
    width: "100%",
    height: 180,
    borderRadius: radius.md,
    overflow: "hidden",
    backgroundColor: colors.surfaceMuted,
    marginBottom: spacing.xs,
  },
  thumbImg: { width: "100%", height: "100%" },
  thumbOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.5)",
    alignItems: "center",
    justifyContent: "center",
  },
  thumbOverlayError: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(185,28,28,0.7)",
    alignItems: "center",
    justifyContent: "center",
  },
  thumbProgressText: { fontFamily: font.bold, fontSize: 12, color: "#fff", marginTop: 4 },
  thumbErrorText: { fontFamily: font.bold, fontSize: 12, color: "#fff", marginTop: 4 },
  thumbRemove: {
    position: "absolute",
    top: 6,
    right: 6,
  },
  addPhotoBtns: { flexDirection: "row", gap: spacing.sm },
  addPhotoBtn: {
    flex: 1,
    minHeight: 52,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    backgroundColor: colors.background,
  },
  addPhotoBtnText: { fontFamily: font.medium, fontSize: fontSize.xs, color: colors.brand },
  photoError: { fontFamily: font.regular, fontSize: fontSize.xs, color: "#B91C1C", marginTop: 4 },
  hintRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 4 },
  hintText: { fontFamily: font.regular, fontSize: fontSize.xs, color: "#B45309" },
  footer: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    padding: spacing.md,
  },
  submitBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.brand,
    minHeight: 52,
    borderRadius: radius.md,
  },
  submitBtnDisabled: { opacity: 0.45 },
  submitBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
});
