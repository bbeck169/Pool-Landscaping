/**
 * Phase F1 · FileUpload — mobile file picker + uploader.
 *
 * Mobile UX (per spec):
 *   - "Take Photo" (expo-image-picker camera mode)
 *   - "Choose from Library" (expo-image-picker library mode)
 *   - "Choose File" (expo-document-picker) — only shown when accept
 *     includes PDF/video
 *
 * Client-side validation:
 *   - Size > 25 MB → onError with size message
 *   - MIME not in accept → onError with MIME message
 *
 * Progress via XHR in the API layer. Post-upload shows thumbnail.
 */
import React, { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  StyleSheet,
  Text,
  View,
  Pressable,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";
import {
  uploadFile,
  deleteFile,
  humanBytes,
  mimeAllowed,
  MAX_UPLOAD_SIZE_BYTES,
  type FileRecord,
} from "@/src/api/files";
import { AuthedImage } from "./AuthedImage";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type UploadItem = {
  clientId: string;
  filename: string;
  size: number;
  content_type: string;
  progress: number;
  uploading: boolean;
  localUri?: string;
  id?: string;        // set after upload completes
  original_filename?: string;
};

type Props = {
  purpose?: string;
  linkedEntityType?: string;
  linkedEntityId?: string;
  accept?: string;
  multiple?: boolean;
  maxFiles?: number;
  onUploaded?: (payload: FileRecord) => void;
  onError?: (err: { code: string; message: string }) => void;
  disabled?: boolean;
  style?: any;
  buttonLabel?: string;
};

function iconFor(ct: string) {
  const type = (ct || "").toLowerCase();
  if (type.startsWith("image/")) return "image-outline" as const;
  if (type.startsWith("video/")) return "videocam-outline" as const;
  if (type === "application/pdf") return "document-text-outline" as const;
  return "document-outline" as const;
}

function acceptsNonImages(accept: string): boolean {
  const acc = (accept || "").toLowerCase();
  return acc.includes("pdf") || acc.includes("video") || acc.includes("*/*");
}

export function FileUpload({
  purpose,
  linkedEntityType,
  linkedEntityId,
  accept = "image/*",
  multiple = false,
  maxFiles = 1,
  onUploaded,
  onError,
  disabled = false,
  style,
  buttonLabel,
}: Props) {
  const [items, setItems] = useState<UploadItem[]>([]);

  const reject = useCallback(
    (code: string, message: string) => {
      onError?.({ code, message });
      Alert.alert("Upload Error", message);
    },
    [onError],
  );

  const doUpload = useCallback(
    async (uri: string, name: string, type: string, size: number) => {
      // Client-side gates
      if (size > MAX_UPLOAD_SIZE_BYTES) {
        reject("FILE_TOO_LARGE", `File "${name}" is ${humanBytes(size)} — max 25 MB.`);
        return;
      }
      if (!mimeAllowed(type, accept)) {
        reject("UNSUPPORTED_MIME", `File "${name}" (${type || "unknown"}) is not an allowed type.`);
        return;
      }

      const clientId = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      setItems((prev) => [
        ...prev,
        { clientId, filename: name, size, content_type: type, progress: 0, uploading: true, localUri: uri },
      ]);

      try {
        const payload = await uploadFile({
          uri,
          name,
          type,
          purpose,
          linkedEntityType,
          linkedEntityId,
          onProgress: (p) =>
            setItems((prev) =>
              prev.map((it) => (it.clientId === clientId ? { ...it, progress: p } : it)),
            ),
        });
        setItems((prev) =>
          prev.map((it) =>
            it.clientId === clientId
              ? { ...it, ...payload, uploading: false, progress: 100 }
              : it,
          ),
        );
        onUploaded?.(payload);
      } catch (e: any) {
        setItems((prev) => prev.filter((it) => it.clientId !== clientId));
        reject(e?.status ? String(e.status) : "UPLOAD_FAILED", e?.message || "Upload failed.");
      }
    },
    [accept, purpose, linkedEntityType, linkedEntityId, reject, onUploaded],
  );

  const roomLeft = () => Math.max(0, maxFiles - items.length);

  const pickFromCamera = async () => {
    if (disabled || roomLeft() <= 0) return;
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) {
      reject("PERMISSION_DENIED", "Camera permission is required to take a photo.");
      return;
    }
    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: ["images"],
      quality: 0.8,
    });
    if (result.canceled || !result.assets?.length) return;
    const asset = result.assets[0];
    doUpload(asset.uri, asset.fileName || "photo.jpg", asset.mimeType || "image/jpeg", asset.fileSize || 0);
  };

  const pickFromLibrary = async () => {
    if (disabled || roomLeft() <= 0) return;
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      reject("PERMISSION_DENIED", "Photo library permission is required.");
      return;
    }
    const count = multiple ? Math.min(roomLeft(), maxFiles) : 1;
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      allowsMultipleSelection: multiple && count > 1,
      selectionLimit: count,
      quality: 0.8,
    });
    if (result.canceled || !result.assets?.length) return;
    for (const asset of result.assets.slice(0, roomLeft())) {
      doUpload(asset.uri, asset.fileName || "image.jpg", asset.mimeType || "image/jpeg", asset.fileSize || 0);
    }
  };

  const pickDocument = async () => {
    if (disabled || roomLeft() <= 0) return;
    const result = await DocumentPicker.getDocumentAsync({
      type: accept.split(",").map((s) => s.trim()).filter(Boolean),
      multiple: multiple && roomLeft() > 1,
    });
    if (result.canceled || !result.assets?.length) return;
    for (const asset of result.assets.slice(0, roomLeft())) {
      doUpload(asset.uri, asset.name || "file", asset.mimeType || "application/octet-stream", asset.size || 0);
    }
  };

  const removeItem = async (it: UploadItem) => {
    if (it.id) {
      try { await deleteFile(it.id); } catch { /* swallow */ }
    }
    setItems((prev) => prev.filter((x) => x.clientId !== it.clientId));
  };

  const isFull = items.length >= maxFiles;
  const showDocPicker = acceptsNonImages(accept);

  return (
    <View style={[styles.root, style]} testID="file-upload-root">
      {/* Action buttons */}
      <View style={styles.btnRow}>
        <Pressable
          style={[styles.btn, (disabled || isFull) && styles.btnDisabled]}
          onPress={pickFromCamera}
          disabled={disabled || isFull}
          testID="file-upload-camera-btn"
        >
          <Ionicons name="camera-outline" size={20} color={disabled || isFull ? colors.muted : colors.brand} />
          <Text style={[styles.btnLabel, (disabled || isFull) && styles.btnLabelDisabled]}>
            Take Photo
          </Text>
        </Pressable>

        <Pressable
          style={[styles.btn, (disabled || isFull) && styles.btnDisabled]}
          onPress={pickFromLibrary}
          disabled={disabled || isFull}
          testID="file-upload-library-btn"
        >
          <Ionicons name="images-outline" size={20} color={disabled || isFull ? colors.muted : colors.brand} />
          <Text style={[styles.btnLabel, (disabled || isFull) && styles.btnLabelDisabled]}>
            {buttonLabel || "Choose from Library"}
          </Text>
        </Pressable>

        {showDocPicker && (
          <Pressable
            style={[styles.btn, (disabled || isFull) && styles.btnDisabled]}
            onPress={pickDocument}
            disabled={disabled || isFull}
            testID="file-upload-document-btn"
          >
            <Ionicons name="document-outline" size={20} color={disabled || isFull ? colors.muted : colors.brand} />
            <Text style={[styles.btnLabel, (disabled || isFull) && styles.btnLabelDisabled]}>
              Choose File
            </Text>
          </Pressable>
        )}
      </View>

      <Text style={styles.hint}>
        Images, MP4 video, or PDF · up to 25 MB
      </Text>

      {/* Uploaded items */}
      {items.map((it) => (
        <View key={it.clientId} style={styles.item} testID={`file-upload-item-${it.clientId}`}>
          {/* Thumbnail */}
          <View style={styles.thumb}>
            {it.id && it.content_type?.startsWith("image/") ? (
              <AuthedImage fileId={it.id} size={48} />
            ) : it.localUri && it.content_type?.startsWith("image/") ? (
              <Image source={{ uri: it.localUri }} style={styles.thumbImg} contentFit="cover" />
            ) : (
              <View style={styles.thumbPlaceholder}>
                <Ionicons name={iconFor(it.content_type)} size={22} color={colors.muted} />
              </View>
            )}
          </View>

          {/* Metadata */}
          <View style={styles.meta}>
            <Text style={styles.metaName} numberOfLines={1}>
              {it.original_filename || it.filename}
            </Text>
            <Text style={styles.metaSub}>
              {humanBytes(it.size || 0)} · {it.content_type || "unknown"}
              {it.uploading ? ` · ${it.progress}%` : ""}
            </Text>
            {it.uploading && (
              <View style={styles.progressTrack}>
                <View style={[styles.progressFill, { width: `${it.progress}%` }]} />
              </View>
            )}
          </View>

          {/* Remove */}
          <Pressable
            onPress={() => removeItem(it)}
            hitSlop={8}
            testID={`file-upload-remove-${it.clientId}`}
            style={styles.removeBtn}
          >
            {it.uploading ? (
              <ActivityIndicator size="small" color={colors.muted} />
            ) : (
              <Ionicons name="close-circle" size={22} color={colors.error} />
            )}
          </Pressable>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {},
  btnRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  btn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    backgroundColor: colors.surface,
  },
  btnDisabled: { opacity: 0.45 },
  btnLabel: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  btnLabelDisabled: { color: colors.muted },
  hint: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: spacing.sm,
    marginBottom: spacing.md,
  },
  item: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  thumb: { width: 48, height: 48 },
  thumbImg: { width: 48, height: 48, borderRadius: radius.sm },
  thumbPlaceholder: {
    width: 48,
    height: 48,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center",
    justifyContent: "center",
  },
  meta: { flex: 1 },
  metaName: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  metaSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  progressTrack: {
    height: 4,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: 2,
    marginTop: 4,
    overflow: "hidden",
  },
  progressFill: {
    height: 4,
    backgroundColor: colors.brand,
    borderRadius: 2,
  },
  removeBtn: { padding: 4 },
});

export default FileUpload;
