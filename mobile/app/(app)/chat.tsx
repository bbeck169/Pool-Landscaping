/**
 * Internal Team Messaging — Mobile chat tab.
 *
 * F2d · Chat attachments: paperclip button → upload to
 * POST /api/chat/attachments/upload → pending[] queue →
 * attachment_ids sent with message → inline attachment links.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TextInput, Pressable, Alert,
  KeyboardAvoidingView, Platform, ActionSheetIOS, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";

import { api, api_base, getAuthToken } from "@/src/api";
import { colors, spacing, radius, fontSize, font } from "@/src/theme";
import { Header } from "@/src/components/widgets";

type ChatAttachment = {
  id: string;
  name: string;
  content_type?: string;
  storage_url?: string;
};

export default function ChatMobile() {
  const [convos, setConvos] = useState<any[]>([]);
  const [selected, setSelected] = useState<any | null>(null);
  const [msgs, setMsgs] = useState<any[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<ChatAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const listRef = useRef<FlatList>(null);
  // Web-only: hidden file input ref
  const webFileInputRef = useRef<HTMLInputElement | null>(null);

  const loadConvos = useCallback(async () => {
    try {
      const r = await api.get("/chat/conversations");
      setConvos(r.conversations || []);
    } catch {}
  }, []);
  useEffect(() => { loadConvos(); }, [loadConvos]);

  const openConvo = async (c: any) => {
    setSelected(c);
    setPending([]);
    try {
      const r = await api.get(`/chat/conversations/${c.id}/messages?limit=100`);
      setMsgs((r.messages || []).slice().reverse());
    } catch {}
  };

  const send = async () => {
    if ((!draft.trim() && pending.length === 0) || !selected) return;
    try {
      const body: any = { body_markdown: draft };
      if (pending.length > 0) {
        body.attachment_ids = pending.map((p) => p.id);
      }
      const m = await api.post(
        `/chat/conversations/${selected.id}/messages`,
        body,
      );
      setMsgs((cur) => [...cur, m]);
      setDraft("");
      setPending([]);
    } catch (e: any) {
      Alert.alert("Send failed", e?.message || "");
    }
  };

  const react = async (mid: string, emoji: string) => {
    try {
      const r = await api.post(`/chat/messages/${mid}/reactions`, { emoji });
      setMsgs((cur) =>
        cur.map((m) =>
          m.id === mid ? { ...m, reactions: r.reactions } : m,
        ),
      );
    } catch {}
  };

  // ─── F2d: Chat attachment upload ───
  const uploadChatAttachment = async (
    uri: string,
    name: string,
    type: string,
  ) => {
    setUploading(true);
    const token = await getAuthToken();
    const form = new FormData();
    form.append("file", {
      uri,
      name: name || "file",
      type: type || "application/octet-stream",
    } as any);

    try {
      const res = await fetch(`${api_base()}/chat/attachments/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      if (!res.ok) {
        Alert.alert("Upload failed", `Status ${res.status}`);
        return;
      }
      const att: ChatAttachment = await res.json();
      setPending((prev) => [...prev, att]);
    } catch (e: any) {
      Alert.alert("Upload failed", e?.message || "Network error");
    } finally {
      setUploading(false);
    }
  };

  const removePending = (id: string) => {
    setPending((prev) => prev.filter((x) => x.id !== id));
  };

  // ─── Web-only: upload a browser File object directly ───
  const uploadWebFile = async (file: File) => {
    setUploading(true);
    const token = await getAuthToken();
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(`${api_base()}/chat/attachments/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      if (!res.ok) {
        Alert.alert("Upload failed", `Status ${res.status}`);
        return;
      }
      const att: ChatAttachment = await res.json();
      setPending((prev) => [...prev, att]);
    } catch (e: any) {
      Alert.alert("Upload failed", e?.message || "Network error");
    } finally {
      setUploading(false);
    }
  };

  const handleWebFileChange = (e: any) => {
    const files = e?.target?.files;
    if (!files || files.length === 0) return;
    for (const f of Array.from(files) as File[]) {
      uploadWebFile(f);
    }
    if (webFileInputRef.current) webFileInputRef.current.value = "";
  };

  const pickAttachment = () => {
    if (Platform.OS === "web") {
      // On Expo Web, trigger the hidden <input type="file"> element
      webFileInputRef.current?.click();
      return;
    }
    if (Platform.OS === "ios") {
      ActionSheetIOS.showActionSheetWithOptions(
        {
          options: ["Take Photo", "Choose from Library", "Choose File", "Cancel"],
          cancelButtonIndex: 3,
        },
        async (idx) => {
          if (idx === 0) pickCamera();
          else if (idx === 1) pickLibrary();
          else if (idx === 2) pickDocument();
        },
      );
    } else {
      // Android: show Alert as action sheet
      Alert.alert("Attach File", "Choose an option", [
        { text: "Take Photo", onPress: pickCamera },
        { text: "Choose from Library", onPress: pickLibrary },
        { text: "Choose File", onPress: pickDocument },
        { text: "Cancel", style: "cancel" },
      ]);
    }
  };

  const pickCamera = async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) {
      Alert.alert("Permission required", "Camera permission is needed.");
      return;
    }
    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: ["images"],
      quality: 0.8,
    });
    if (result.canceled || !result.assets?.length) return;
    const a = result.assets[0];
    uploadChatAttachment(a.uri, a.fileName || "photo.jpg", a.mimeType || "image/jpeg");
  };

  const pickLibrary = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert("Permission required", "Photo library permission is needed.");
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      quality: 0.8,
    });
    if (result.canceled || !result.assets?.length) return;
    const a = result.assets[0];
    uploadChatAttachment(a.uri, a.fileName || "image.jpg", a.mimeType || "image/jpeg");
  };

  const pickDocument = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: ["image/*", "video/mp4", "application/pdf"],
    });
    if (result.canceled || !result.assets?.length) return;
    const a = result.assets[0];
    uploadChatAttachment(a.uri, a.name || "file", a.mimeType || "application/octet-stream");
  };

  // ─── Conversation list ───
  if (!selected) {
    return (
      <View style={styles.root}>
        <Header title="Chat" />
        <FlatList
          data={convos}
          keyExtractor={(x) => x.id}
          contentContainerStyle={{ padding: spacing.md }}
          renderItem={({ item }) => (
            <Pressable
              style={styles.convoRow}
              onPress={() => openConvo(item)}
              testID={`chat-mobile-convo-${item.id}`}
            >
              <Ionicons
                name={item.type === "channel" ? "chatbubbles-outline" : "person-outline"}
                size={18}
                color={colors.brand}
              />
              <View style={{ flex: 1 }}>
                <Text style={styles.convoName}>{item.name || "DM"}</Text>
                {item.last_message_preview && (
                  <Text style={styles.convoPreview} numberOfLines={1}>
                    {item.last_message_preview}
                  </Text>
                )}
              </View>
              {item.unread_count > 0 && (
                <View style={styles.badge}>
                  <Text style={styles.badgeTxt}>{item.unread_count}</Text>
                </View>
              )}
            </Pressable>
          )}
          ListEmptyComponent={
            <Text style={styles.empty}>No conversations yet.</Text>
          }
        />
      </View>
    );
  }

  // ─── Thread view ───
  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <Header title={selected.name || "DM"} back />
      <FlatList
        ref={listRef}
        data={msgs}
        keyExtractor={(x) => x.id}
        contentContainerStyle={{ padding: spacing.md }}
        renderItem={({ item }) => (
          <View style={styles.msg}>
            <Text style={styles.msgAuthor}>
              {item.author_name || (item.author_user_id || "").slice(0, 6)}
            </Text>
            <Text
              style={item.deleted_at ? styles.msgDeleted : styles.msgBody}
            >
              {item.deleted_at ? "(deleted)" : item.body_markdown}
            </Text>

            {/* F2d: inline attachment links */}
            {(item.attachments || []).map((a: ChatAttachment) => (
              <View key={a.id} style={styles.attachRow} testID={`chat-attachment-${a.id}`}>
                <Ionicons name="attach" size={14} color={colors.brand} />
                <Text style={styles.attachName} numberOfLines={1}>
                  {a.name || "attachment"}
                </Text>
              </View>
            ))}

            <View style={styles.reactRow}>
              {Object.entries(item.reactions || {}).map(
                ([e, r]: any) => (
                  <Pressable
                    key={e}
                    onPress={() => react(item.id, e)}
                    style={styles.reactChip}
                  >
                    <Text style={{ fontSize: 12 }}>
                      {e} {r.count}
                    </Text>
                  </Pressable>
                ),
              )}
              <Pressable
                onPress={() => react(item.id, "👍")}
                style={styles.reactPlus}
              >
                <Text style={{ fontSize: 12, opacity: 0.6 }}>+ 👍</Text>
              </Pressable>
            </View>
          </View>
        )}
      />

      {/* Composer area */}
      <View style={styles.composerArea}>
        {/* F2d: Pending attachment chips */}
        {pending.length > 0 && (
          <View style={styles.pendingStrip} testID="chat-pending-strip">
            {pending.map((p) => (
              <View
                key={p.id}
                style={styles.pendingChip}
                testID={`chat-pending-${p.id}`}
              >
                <Ionicons name="attach" size={12} color={colors.brand} />
                <Text style={styles.pendingName} numberOfLines={1}>
                  {p.name || "attachment"}
                </Text>
                <Pressable
                  onPress={() => removePending(p.id)}
                  hitSlop={6}
                  testID={`chat-pending-remove-${p.id}`}
                >
                  <Ionicons name="close-circle" size={16} color={colors.error} />
                </Pressable>
              </View>
            ))}
          </View>
        )}

        <View style={styles.composerRow}>
          {/* Web-only: hidden file input for browser file picker */}
          {Platform.OS === "web" && (
            <input
              ref={webFileInputRef as any}
              type="file"
              multiple
              accept="image/*,video/mp4,application/pdf"
              onChange={handleWebFileChange}
              style={{ display: "none" }}
              data-testid="chat-web-file-input"
            />
          )}
          {/* Paperclip button */}
          <Pressable
            style={styles.attachBtn}
            onPress={pickAttachment}
            disabled={uploading}
            testID="chat-upload-btn"
          >
            {uploading ? (
              <ActivityIndicator size="small" color={colors.brand} />
            ) : (
              <Ionicons name="attach" size={22} color={colors.brand} />
            )}
          </Pressable>

          <TextInput
            value={draft}
            onChangeText={setDraft}
            placeholder="Message"
            style={styles.composer}
            testID="chat-mobile-composer"
          />
          <Pressable
            style={[
              styles.sendBtn,
              (!draft.trim() && pending.length === 0) && styles.sendBtnDisabled,
            ]}
            onPress={send}
            disabled={uploading || (!draft.trim() && pending.length === 0)}
            testID="chat-mobile-send"
          >
            <Ionicons name="send" size={18} color="#fff" />
          </Pressable>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  convoRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    marginBottom: 6,
  },
  convoName: { fontFamily: font.semibold, color: colors.onSurface },
  convoPreview: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 2,
  },
  badge: {
    backgroundColor: colors.brand,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 8,
    minWidth: 20,
    alignItems: "center",
  },
  badgeTxt: { color: "#fff", fontFamily: font.bold, fontSize: 10 },
  empty: { textAlign: "center", padding: 40, color: colors.muted },
  msg: {
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    marginBottom: 6,
  },
  msgAuthor: {
    fontFamily: font.semibold,
    color: colors.muted,
    fontSize: fontSize.sm,
    marginBottom: 4,
  },
  msgBody: {
    fontFamily: font.regular,
    color: colors.onSurface,
    fontSize: fontSize.base,
  },
  msgDeleted: {
    fontFamily: font.regular,
    color: colors.muted,
    fontStyle: "italic",
    fontSize: fontSize.sm,
  },
  attachRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: 6,
    paddingVertical: 4,
    paddingHorizontal: 8,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    alignSelf: "flex-start",
  },
  attachName: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.brand,
    maxWidth: 200,
  },
  reactRow: {
    flexDirection: "row",
    gap: 6,
    marginTop: 6,
    flexWrap: "wrap",
  },
  reactChip: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  reactPlus: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
  },
  composerArea: {
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  pendingStrip: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
  },
  pendingChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.pill,
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
  composerRow: {
    flexDirection: "row",
    padding: spacing.md,
    alignItems: "center",
  },
  attachBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    marginRight: 8,
  },
  composer: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 20,
    paddingHorizontal: 14,
    paddingVertical: 8,
    marginRight: 8,
    backgroundColor: colors.surfaceSecondary,
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.brand,
    alignItems: "center",
    justifyContent: "center",
  },
  sendBtnDisabled: {
    opacity: 0.5,
  },
});
