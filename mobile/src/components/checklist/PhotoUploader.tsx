/**
 * Phase 31 · Step 2a — PhotoUploader (mobile checklist).
 *
 * Uploads up to `max` photos against a job. Uses the existing endpoints
 * from Step 1 discovery:
 *   POST   /api/jobs/{jid}/photos
 *   DELETE /api/jobs/{jid}/photos/{pid}
 *
 * Photos are base64 data-URLs (same pattern as service-report/[id].tsx).
 * No new endpoints invented; delete uses the DELETE endpoint verified
 * in openapi.json.
 */
import React, { useState } from "react";
import { View, Text, Pressable, StyleSheet, Alert, ActivityIndicator } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import * as writeQueue from "@/src/services/writeQueue";
import { useOnline } from "@/src/offline";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export type ChecklistPhoto = {
  id: string;
  url?: string;
  data?: string;
  label?: string;
};

export type PhotoUploaderProps = {
  jobId: string;
  photos: ChecklistPhoto[];
  onPhotosChange: (next: ChecklistPhoto[]) => void;
  max?: number;
  disabled?: boolean;
};

export default function PhotoUploader({
  jobId, photos, onPhotosChange, max = 10, disabled = false,
}: PhotoUploaderProps) {
  const [busy, setBusy] = useState(false);
  const online = useOnline();
  const remaining = Math.max(0, max - photos.length);

  const pick = async (fromCamera: boolean) => {
    if (disabled || remaining <= 0) return;
    const perm = fromCamera
      ? await ImagePicker.requestCameraPermissionsAsync()
      : await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) { Alert.alert("Permission needed"); return; }
    const pick = fromCamera
      ? await ImagePicker.launchCameraAsync({ quality: 0.6, base64: true })
      : await ImagePicker.launchImageLibraryAsync({ quality: 0.6, base64: true });
    if (pick.canceled || !pick.assets?.length) return;
    const a: any = pick.assets[0];
    const dataUrl = `data:${a.mimeType || "image/jpeg"};base64,${a.base64}`;
    const label = `checklist-${new Date().toISOString()}`;
    setBusy(true);
    try {
      // Phase 40 · Step 2 — offline path: enqueue for later replay and
      // optimistically show the photo in the grid so the tech can carry
      // on. The queued POST carries an X-Idempotency-Key so a mid-flush
      // retry can't duplicate the image.
      if (!online) {
        await writeQueue.enqueue({
          kind: "upload-photo",
          jobId,
          body: { data: dataUrl, label },
        });
        const optimistic = {
          id: `pending-${Date.now()}`,
          data: dataUrl,
          label,
        };
        onPhotosChange([...(photos || []), optimistic]);
        return;
      }
      const updated = await api.post(`/jobs/${jobId}/photos`, {
        data: dataUrl,
        label,
      });
      onPhotosChange(updated.photos || []);
    } catch (e: any) {
      Alert.alert("Upload failed", e?.message || "Try again.");
    } finally { setBusy(false); }
  };

  const remove = async (pid: string) => {
    if (disabled) return;
    try {
      const updated = await api.del(`/jobs/${jobId}/photos/${pid}`);
      onPhotosChange(updated.photos || []);
    } catch (e: any) {
      Alert.alert("Delete failed", e?.message || "Try again.");
    }
  };

  return (
    <View testID="checklist-photo-uploader">
      <View style={styles.row}>
        <Text style={styles.counter}>{photos.length} of {max}</Text>
        {busy && <ActivityIndicator size="small" color={colors.brand} />}
      </View>
      <View style={styles.grid}>
        {photos.map((p) => (
          <View key={p.id} style={styles.cell}>
            <Image source={{ uri: p.data || p.url }} style={styles.img} contentFit="cover" />
            {!disabled && (
              <Pressable
                style={styles.del}
                onPress={() => remove(p.id)}
                testID={`checklist-photo-del-${p.id}`}
              >
                <Ionicons name="close" size={12} color="#fff" />
              </Pressable>
            )}
          </View>
        ))}
      </View>
      {/* Upload buttons — styled to match Visit Media (ServiceReportMediaUploader) */}
      {!disabled && remaining > 0 && (
        <View style={styles.uploadRow}>
          <Pressable
            style={[styles.uploadBtn, busy && { opacity: 0.5 }]}
            onPress={() => pick(true)}
            disabled={busy}
            testID="checklist-photo-camera"
          >
            <Ionicons name="camera-outline" size={16} color={colors.brand} />
            <Text style={styles.uploadBtnText}>Photo</Text>
          </Pressable>
          <Pressable
            style={[styles.uploadBtn, busy && { opacity: 0.5 }]}
            onPress={() => pick(false)}
            disabled={busy}
            testID="checklist-photo-library"
          >
            <Ionicons name="images-outline" size={16} color={colors.brand} />
            <Text style={styles.uploadBtnText}>Library</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  counter: { fontFamily: font.semibold, fontSize: fontSize.xs, color: colors.muted },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  cell: { width: "31%", aspectRatio: 1 },
  img: {
    width: "100%", height: "100%", borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
  },
  del: {
    position: "absolute", top: 4, right: 4, backgroundColor: "rgba(0,0,0,0.7)",
    borderRadius: 12, padding: 4, alignItems: "center", justifyContent: "center",
  },
  // Phase M4 — Upload buttons styled to match Visit Media (ServiceReportMediaUploader).
  uploadRow: {
    flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginTop: spacing.sm,
  },
  uploadBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 8,
    borderRadius: radius.md, borderWidth: 1.5, borderStyle: "dashed",
    borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  uploadBtnText: {
    fontSize: fontSize.sm, fontFamily: font.semibold, color: colors.onSurface,
  },
});
