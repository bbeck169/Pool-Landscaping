/**
 * Phase B2 mobile · Customer portal chat thread detail.
 *
 * Mirrors web PortalChatsPage.jsx thread pane:
 *   - Polls every 4s for new messages while focused
 *   - Paperclip button → ActionSheet → camera/library/document picker
 *   - Upload via F0 files/upload with purpose=portal_chat_attachment
 *   - pending[] queue → attachment_ids sent with message
 *   - Inline attachment rendering: images as thumbnails, files as cards
 *   - Tap non-image → download + share via expo-file-system/Sharing
 *   - Error handling: 403 → toast, 413 → toast, permission → toast
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TextInput, Pressable,
  KeyboardAvoidingView, Platform, Alert, ActivityIndicator,
  ActionSheetIOS, Linking,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";

import { api, api_base, getAuthToken } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { AuthedImage } from "@/src/components/files/AuthedImage";
import { humanBytes, buildAuthedDownloadUrl } from "@/src/api/files";

const POLL_MS = 4000;

// ── Types ──────────────────────────────────────────────────────────
type PendingAtt = {
  id: string;
  filename: string;
  mime: string;
  size: number;
};

type HydratedAtt = {
  id: string;
  filename?: string;
  name?: string;
  mime?: string;
  content_type?: string;
  size?: number;
  size_bytes?: number;
  signed_url?: string;
  storage_url?: string;
  url?: string;
  type?: string;
};

// ── Helpers ────────────────────────────────────────────────────────
function attName(a: HydratedAtt): string {
  return a.filename || a.name || "attachment";
}
function attMime(a: HydratedAtt): string {
  return (a.mime || a.content_type || "").toLowerCase();
}
function attSize(a: HydratedAtt): number {
  return Number(a.size || a.size_bytes || 0);
}
function isImage(a: HydratedAtt): boolean {
  if ((a as any).type === "image") return true;
  return attMime(a).startsWith("image/");
}
/** Extract file id from /api/files/{id}/download */
function extractFileId(url?: string): string | null {
  if (!url) return null;
  const m = url.match(/\/api\/files\/([^/?#]+)\/download/);
  return m ? m[1] : null;
}
function attUrl(a: HydratedAtt): string {
  return a.signed_url || a.storage_url || a.url || "";
}

export default function ChatThread() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";

  const [msgs, setMsgs] = useState<any[]>([]);
  const [chat, setChat] = useState<any>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<PendingAtt[]>([]);
  const [uploading, setUploading] = useState(false);
  const listRef = useRef<FlatList>(null);

  // ─── Load messages ───
  const load = useCallback(async () => {
    try {
      const d = await api.get(`/portal/chats/${id}/messages`);
      setChat(d.chat);
      setMsgs(d.messages || []);
      api.post(`/portal/chats/${id}/read`, {}).catch(() => {});
    } catch {}
  }, [id]);

  useFocusEffect(
    useCallback(() => {
      load();
      const t = setInterval(load, POLL_MS);
      return () => clearInterval(t);
    }, [load]),
  );

  useEffect(() => {
    setTimeout(
      () => listRef.current?.scrollToEnd({ animated: true }),
      100,
    );
  }, [msgs.length]);

  // ─── Upload attachment via F0 files/upload ───
  const uploadAttachment = async (
    uri: string,
    name: string,
    type: string,
    size: number,
  ) => {
    setUploading(true);
    const token = await getAuthToken();
    const form = new FormData();
    form.append("file", {
      uri,
      name: name || "file",
      type: type || "application/octet-stream",
    } as any);
    form.append("purpose", "portal_chat_attachment");
    if (user?.customer_id) {
      form.append("linked_entity_type", "customer");
      form.append("linked_entity_id", user.customer_id);
    }

    try {
      const res = await fetch(`${api_base()}/files/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        const detail =
          body?.detail && typeof body.detail === "string"
            ? body.detail
            : `Upload failed (${res.status})`;
        if (res.status === 413) {
          Alert.alert("File too large", detail);
        } else if (res.status === 403) {
          Alert.alert("Permission denied", detail);
        } else {
          Alert.alert("Upload failed", detail);
        }
        return;
      }
      const doc = await res.json();
      setPending((p) => [
        ...p,
        {
          id: doc.id,
          filename: doc.original_filename || name,
          mime: doc.content_type || type,
          size: doc.size || size,
        },
      ]);
    } catch (e: any) {
      Alert.alert("Upload failed", e?.message || "Network error — tap to retry.");
    } finally {
      setUploading(false);
    }
  };

  const removePending = (fid: string) => {
    setPending((p) => p.filter((x) => x.id !== fid));
  };

  // ─── Send message ───
  const send = async () => {
    if ((!text.trim() && pending.length === 0) || sending) return;
    setSending(true);
    try {
      const body: any = {
        body: text,
        attachment_ids: pending.map((p) => p.id),
      };
      const m = await api.post(`/portal/chats/${id}/messages`, body);
      setMsgs((prev) => [...prev, m]);
      setText("");
      setPending([]);
    } catch (e: any) {
      Alert.alert("Send failed", e?.message || "");
    } finally {
      setSending(false);
    }
  };

  // ─── Picker ───
  const pickAttachment = () => {
    if (Platform.OS === "ios") {
      ActionSheetIOS.showActionSheetWithOptions(
        {
          options: ["Photo / Video", "File", "Cancel"],
          cancelButtonIndex: 2,
        },
        (idx) => {
          if (idx === 0) pickFromLibrary();
          else if (idx === 1) pickDocument();
        },
      );
    } else {
      Alert.alert("Attach", "Choose an option", [
        { text: "Photo / Video", onPress: pickFromLibrary },
        { text: "File", onPress: pickDocument },
        { text: "Cancel", style: "cancel" },
      ]);
    }
  };

  const pickFromLibrary = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert(
        "Permission needed",
        "Enable photo library access in Settings.",
        [
          { text: "Open Settings", onPress: () => Linking.openSettings() },
          { text: "Cancel", style: "cancel" },
        ],
      );
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images", "videos"],
      quality: 0.8,
    });
    if (result.canceled || !result.assets?.length) return;
    const a = result.assets[0];
    uploadAttachment(
      a.uri,
      a.fileName || "photo.jpg",
      a.mimeType || "image/jpeg",
      a.fileSize || 0,
    );
  };

  const pickDocument = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: ["image/*", "application/pdf", "video/*"],
      multiple: false,
    });
    if (result.canceled || !result.assets?.length) return;
    const a = result.assets[0];
    uploadAttachment(
      a.uri,
      a.name || "file",
      a.mimeType || "application/octet-stream",
      a.size || 0,
    );
  };

  // ─── Download / share a non-image attachment ───
  const downloadAndShare = async (att: HydratedAtt) => {
    try {
      const token = await getAuthToken();
      const fid = extractFileId(attUrl(att));
      if (!fid) {
        Alert.alert("Error", "No download URL available.");
        return;
      }
      const url = buildAuthedDownloadUrl(fid, token);
      const localUri = `${FileSystem.cacheDirectory}portal_chat_${fid}`;
      const dl = await FileSystem.downloadAsync(url, localUri);
      if (dl.status < 200 || dl.status >= 300) {
        Alert.alert("Download failed", `Status ${dl.status}`);
        return;
      }
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(dl.uri);
      } else {
        Alert.alert("Downloaded", `File saved to cache.`);
      }
    } catch (e: any) {
      Alert.alert("Download failed", e?.message || "");
    }
  };

  // ─── Render attachment inline ───
  const renderAttachment = (att: HydratedAtt) => {
    const fid = extractFileId(attUrl(att));
    const name = attName(att);
    const size = attSize(att);

    if (isImage(att) && fid) {
      return (
        <Pressable
          key={att.id}
          testID={`portal-chat-att-${att.id}`}
          style={styles.attImageWrap}
          onPress={() => downloadAndShare(att)}
        >
          <AuthedImage fileId={fid} size={140} style={styles.attImage} />
        </Pressable>
      );
    }

    // Non-image file card
    return (
      <Pressable
        key={att.id}
        testID={`portal-chat-att-${att.id}`}
        style={styles.attFileCard}
        onPress={() => downloadAndShare(att)}
      >
        <Ionicons name="document-outline" size={18} color={colors.brand} />
        <View style={{ flex: 1 }}>
          <Text style={styles.attFileName} numberOfLines={1}>
            {name}
          </Text>
          {size > 0 && (
            <Text style={styles.attFileSize}>{humanBytes(size)}</Text>
          )}
        </View>
        <Ionicons name="download-outline" size={16} color={colors.muted} />
      </Pressable>
    );
  };

  // ─── Render ───
  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={80}
    >
      {/* Header */}
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="chat-back">
          <Ionicons name="chevron-back" size={22} color={colors.brand} />
        </Pressable>
        <Text style={styles.headerTitle} numberOfLines={1}>
          {chat?.subject || "Thread"}
        </Text>
        <View style={{ width: 22 }} />
      </View>

      {/* Messages */}
      <FlatList
        ref={listRef}
        testID="chat-messages"
        data={msgs}
        keyExtractor={(m) => m.id}
        contentContainerStyle={{ padding: spacing.md, gap: spacing.sm }}
        renderItem={({ item }) => {
          const mine = item.sender_role === "customer";
          return (
            <View
              style={[
                styles.bubbleWrap,
                mine ? { alignItems: "flex-end" } : { alignItems: "flex-start" },
              ]}
            >
              <View
                style={[
                  styles.bubble,
                  mine ? styles.bubbleMine : styles.bubbleOther,
                ]}
                testID={`portal-chat-msg-${item.id}`}
              >
                <Text
                  style={[
                    styles.sender,
                    mine
                      ? { color: "rgba(255,255,255,0.7)" }
                      : { color: colors.muted },
                  ]}
                >
                  {item.sender_name || item.sender_role}
                </Text>
                {item.body ? (
                  <Text
                    style={[
                      styles.body,
                      mine ? { color: "#fff" } : { color: colors.onSurface },
                    ]}
                  >
                    {item.body}
                  </Text>
                ) : null}
                {/* Inline attachments */}
                {(item.attachments || []).map((a: HydratedAtt) =>
                  renderAttachment(a),
                )}
              </View>
            </View>
          );
        }}
        style={{ backgroundColor: colors.surfaceSecondary }}
      />

      {/* Pending attachment chips */}
      {pending.length > 0 && (
        <View style={styles.pendingStrip} testID="portal-chats-pending-strip">
          {pending.map((p) => (
            <View
              key={p.id}
              style={styles.pendingChip}
              testID={`portal-chats-pending-${p.id}`}
            >
              <Ionicons name="attach" size={12} color={colors.brand} />
              <Text style={styles.pendingName} numberOfLines={1}>
                {p.filename}
              </Text>
              <Pressable
                onPress={() => removePending(p.id)}
                hitSlop={6}
                testID={`portal-chats-pending-remove-${p.id}`}
              >
                <Ionicons name="close-circle" size={16} color={colors.error} />
              </Pressable>
            </View>
          ))}
        </View>
      )}

      {/* Composer */}
      <View style={styles.composer}>
        {/* Paperclip — customers only (web mirrors this guard) */}
        {!isAdmin && (
          <Pressable
            style={styles.attachBtn}
            onPress={pickAttachment}
            disabled={uploading}
            testID="portal-chats-upload-btn"
          >
            {uploading ? (
              <ActivityIndicator size="small" color={colors.brand} />
            ) : (
              <Ionicons name="attach" size={22} color={colors.brand} />
            )}
          </Pressable>
        )}

        <TextInput
          value={text}
          onChangeText={setText}
          placeholder="Type a message…"
          placeholderTextColor={colors.muted}
          style={styles.input}
          multiline
          testID="chat-input"
        />
        <Pressable
          style={[
            styles.send,
            (uploading || (!text.trim() && pending.length === 0)) &&
              styles.sendDisabled,
          ]}
          onPress={send}
          disabled={sending || uploading || (!text.trim() && pending.length === 0)}
          testID="chat-send"
        >
          <Ionicons name="send" size={18} color="#fff" />
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderColor: colors.border,
    gap: spacing.md,
  },
  headerTitle: {
    flex: 1,
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  bubbleWrap: {},
  bubble: {
    maxWidth: "82%",
    padding: spacing.md,
    borderRadius: radius.lg,
  },
  bubbleMine: {
    backgroundColor: colors.brand,
    borderBottomRightRadius: 4,
  },
  bubbleOther: {
    backgroundColor: colors.surface,
    borderBottomLeftRadius: 4,
    borderWidth: 1,
    borderColor: colors.border,
  },
  sender: { fontFamily: font.semibold, fontSize: 11, marginBottom: 2 },
  body: { fontFamily: font.regular, fontSize: fontSize.base },

  // Attachment: image thumbnail
  attImageWrap: { marginTop: spacing.sm, borderRadius: radius.md, overflow: "hidden" },
  attImage: { borderRadius: radius.md },

  // Attachment: non-image file card
  attFileCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: spacing.sm,
    paddingVertical: 6,
    paddingHorizontal: 8,
    backgroundColor: "rgba(0,0,0,0.06)",
    borderRadius: radius.sm,
  },
  attFileName: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  attFileSize: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 1,
  },

  // Pending strip
  pendingStrip: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  pendingChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  pendingName: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    maxWidth: 120,
  },

  // Composer
  composer: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: spacing.sm,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderColor: colors.border,
  },
  attachBtn: {
    width: 42,
    height: 42,
    borderRadius: 21,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  input: {
    flex: 1,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.md,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    maxHeight: 100,
    borderWidth: 1,
    borderColor: colors.border,
  },
  send: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: colors.brand,
    alignItems: "center",
    justifyContent: "center",
  },
  sendDisabled: { opacity: 0.5 },
});
