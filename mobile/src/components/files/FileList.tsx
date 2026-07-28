/**
 * Phase F1 · FileList — list files linked to an entity.
 *
 * Mirrors web FileList: fetches via listFilesByEntity, renders grid
 * with AuthedImage thumbnails for images, icons for other types.
 * Supports delete and pull-to-refresh.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import {
  listFilesByEntity,
  deleteFile,
  humanBytes,
  type FileRecord,
} from "@/src/api/files";
import { AuthedImage } from "./AuthedImage";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type Props = {
  linkedEntityType: string;
  linkedEntityId: string;
  purpose?: string;
  canDelete?: boolean;
  onChange?: (items: FileRecord[]) => void;
};

function isImage(ct: string) {
  return (ct || "").toLowerCase().startsWith("image/");
}

function iconFor(ct: string): keyof typeof Ionicons.glyphMap {
  const type = (ct || "").toLowerCase();
  if (type.startsWith("video/")) return "videocam-outline";
  if (type === "application/pdf") return "document-text-outline";
  return "document-outline";
}

export function FileList({ linkedEntityType, linkedEntityId, purpose, canDelete = false, onChange }: Props) {
  const [rows, setRows] = useState<FileRecord[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const reload = useCallback(async () => {
    setErr(null);
    try {
      const items = await listFilesByEntity(linkedEntityType, linkedEntityId, purpose);
      setRows(items);
      onChange?.(items);
    } catch (e: any) {
      setRows([]);
      setErr(e?.message || "Failed to load files.");
    }
  }, [linkedEntityType, linkedEntityId, purpose, onChange]);

  useEffect(() => {
    reload();
  }, [reload]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await reload();
    setRefreshing(false);
  }, [reload]);

  const remove = useCallback(
    async (id: string, filename: string) => {
      Alert.alert("Delete File", `Remove "${filename}"?`, [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            try {
              await deleteFile(id);
              await reload();
            } catch (e: any) {
              Alert.alert("Error", e?.message || "Delete failed.");
            }
          },
        },
      ]);
    },
    [reload],
  );

  // Loading
  if (rows === null) {
    return (
      <View style={styles.center} testID="file-list-loading">
        <ActivityIndicator size="small" color={colors.muted} />
        <Text style={styles.statusText}>Loading files…</Text>
      </View>
    );
  }

  // Error
  if (err) {
    return (
      <View style={styles.center} testID="file-list-error">
        <Ionicons name="alert-circle-outline" size={20} color={colors.error} />
        <Text style={[styles.statusText, { color: colors.error }]}>{err}</Text>
      </View>
    );
  }

  // Empty
  if (rows.length === 0) {
    return (
      <View style={styles.center} testID="file-list-empty">
        <Ionicons name="folder-open-outline" size={24} color={colors.muted} />
        <Text style={styles.statusText}>No files yet.</Text>
      </View>
    );
  }

  const renderItem = ({ item: r }: { item: FileRecord }) => (
    <View style={styles.item} testID={`file-list-item-${r.id}`}>
      {/* Thumbnail */}
      <View style={styles.thumb}>
        {isImage(r.content_type) ? (
          <AuthedImage fileId={r.id} alt={r.original_filename} size={48} />
        ) : (
          <View style={styles.thumbPlaceholder}>
            <Ionicons name={iconFor(r.content_type)} size={22} color={colors.muted} />
          </View>
        )}
      </View>

      {/* Metadata */}
      <View style={styles.meta}>
        <Text style={styles.metaName} numberOfLines={1}>
          {r.original_filename}
        </Text>
        <Text style={styles.metaSub}>
          {humanBytes(r.size)} · {r.content_type || "unknown"}
          {r.created_at ? ` · ${String(r.created_at).slice(0, 10)}` : ""}
        </Text>
      </View>

      {/* Delete */}
      {canDelete && (
        <Pressable
          onPress={() => remove(r.id, r.original_filename)}
          hitSlop={8}
          testID={`file-list-delete-${r.id}`}
          style={styles.deleteBtn}
        >
          <Ionicons name="trash-outline" size={18} color={colors.error} />
        </Pressable>
      )}
    </View>
  );

  return (
    <FlatList
      data={rows}
      keyExtractor={(r) => r.id}
      renderItem={renderItem}
      scrollEnabled={false}
      testID="file-list"
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand} />
      }
    />
  );
}

const styles = StyleSheet.create({
  center: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: spacing.xl,
    gap: spacing.sm,
  },
  statusText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
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
  thumbPlaceholder: {
    width: 48,
    height: 48,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center",
    justifyContent: "center",
  },
  meta: { flex: 1 },
  metaName: {
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  metaSub: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 1,
  },
  deleteBtn: {
    padding: 6,
    borderRadius: radius.sm,
  },
});

export default FileList;
