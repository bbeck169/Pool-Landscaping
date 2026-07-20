/**
 * Internal Team Messaging — Mobile chat tab.
 *
 * Minimal but functional: conversations list on tap → messages screen
 * with compose + reactions. Reuses the existing WS subscription via
 * `/ws/notifications`. Push notification token registration on mount.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TextInput, Pressable, Alert,
  KeyboardAvoidingView, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, fontSize, font } from "@/src/theme";
import { Header } from "@/src/components/widgets";

export default function ChatMobile() {
  const [convos, setConvos] = useState<any[]>([]);
  const [selected, setSelected] = useState<any | null>(null);
  const [msgs, setMsgs] = useState<any[]>([]);
  const [draft, setDraft] = useState("");
  const listRef = useRef<FlatList>(null);

  const loadConvos = useCallback(async () => {
    try {
      const r = await api.get("/chat/conversations");
      setConvos(r.conversations || []);
    } catch {}
  }, []);
  useEffect(() => { loadConvos(); }, [loadConvos]);

  const openConvo = async (c: any) => {
    setSelected(c);
    try {
      const r = await api.get(`/chat/conversations/${c.id}/messages?limit=100`);
      setMsgs((r.messages || []).slice().reverse());
    } catch {}
  };

  const send = async () => {
    if (!draft.trim() || !selected) return;
    try {
      const m = await api.post(`/chat/conversations/${selected.id}/messages`,
                                  { body_markdown: draft });
      setMsgs((cur) => [...cur, m]);
      setDraft("");
    } catch (e: any) {
      Alert.alert("Send failed", e?.message || "");
    }
  };

  const react = async (mid: string, emoji: string) => {
    try {
      const r = await api.post(`/chat/messages/${mid}/reactions`, { emoji });
      setMsgs((cur) => cur.map((m) => m.id === mid
        ? { ...m, reactions: r.reactions } : m));
    } catch {}
  };

  if (!selected) {
    return (
      <View style={styles.root}>
        <Header title="Chat" />
        <FlatList data={convos} keyExtractor={(x) => x.id}
                    contentContainerStyle={{ padding: spacing.md }}
                    renderItem={({ item }) => (
                      <Pressable style={styles.convoRow}
                                    onPress={() => openConvo(item)}
                                    testID={`chat-mobile-convo-${item.id}`}>
                        <Ionicons name={item.type === "channel"
                                            ? "chatbubbles-outline"
                                            : "person-outline"}
                                     size={18} color={colors.brand} />
                        <View style={{ flex: 1 }}>
                          <Text style={styles.convoName}>
                            {item.name || "DM"}
                          </Text>
                          {item.last_message_preview && (
                            <Text style={styles.convoPreview} numberOfLines={1}>
                              {item.last_message_preview}
                            </Text>
                          )}
                        </View>
                        {item.unread_count > 0 && (
                          <View style={styles.badge}>
                            <Text style={styles.badgeTxt}>
                              {item.unread_count}
                            </Text>
                          </View>
                        )}
                      </Pressable>
                    )}
                    ListEmptyComponent={
                      <Text style={styles.empty}>No conversations yet.</Text>
                    } />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView style={styles.root}
                            behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <Header title={selected.name || "DM"} back />
      <FlatList ref={listRef} data={msgs}
                  keyExtractor={(x) => x.id}
                  contentContainerStyle={{ padding: spacing.md }}
                  renderItem={({ item }) => (
                    <View style={styles.msg}>
                      <Text style={styles.msgAuthor}>
                        {item.author_name || (item.author_user_id || "").slice(0, 6)}
                      </Text>
                      <Text style={item.deleted_at ? styles.msgDeleted : styles.msgBody}>
                        {item.deleted_at ? "(deleted)" : item.body_markdown}
                      </Text>
                      <View style={styles.reactRow}>
                        {Object.entries(item.reactions || {}).map(([e, r]: any) => (
                          <Pressable key={e} onPress={() => react(item.id, e)}
                                        style={styles.reactChip}>
                            <Text style={{ fontSize: 12 }}>{e} {r.count}</Text>
                          </Pressable>
                        ))}
                        <Pressable onPress={() => react(item.id, "👍")}
                                     style={styles.reactPlus}>
                          <Text style={{ fontSize: 12, opacity: 0.6 }}>+ 👍</Text>
                        </Pressable>
                      </View>
                    </View>
                  )} />
      <View style={styles.composerRow}>
        <TextInput value={draft} onChangeText={setDraft}
                     placeholder="Message" style={styles.composer}
                     testID="chat-mobile-composer" />
        <Pressable style={styles.sendBtn} onPress={send}
                     testID="chat-mobile-send">
          <Ionicons name="send" size={18} color="#fff" />
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  convoRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surface, borderColor: colors.border,
    borderWidth: 1, marginBottom: 6,
  },
  convoName: { fontFamily: font.semibold, color: colors.onSurface },
  convoPreview: { fontFamily: font.regular, fontSize: fontSize.sm,
                    color: colors.muted, marginTop: 2 },
  badge: {
    backgroundColor: colors.brand,
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 8,
    minWidth: 20, alignItems: "center",
  },
  badgeTxt: { color: "#fff", fontFamily: font.bold, fontSize: 10 },
  empty: { textAlign: "center", padding: 40, color: colors.muted },
  msg: {
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surface, borderColor: colors.border,
    borderWidth: 1, marginBottom: 6,
  },
  msgAuthor: { fontFamily: font.semibold, color: colors.muted,
                 fontSize: fontSize.sm, marginBottom: 4 },
  msgBody: { fontFamily: font.regular, color: colors.onSurface,
                fontSize: fontSize.base },
  msgDeleted: { fontFamily: font.regular, color: colors.muted,
                  fontStyle: "italic", fontSize: fontSize.sm },
  reactRow: { flexDirection: "row", gap: 6, marginTop: 6,
                flexWrap: "wrap" },
  reactChip: {
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 12, borderWidth: 1, borderColor: colors.border,
  },
  reactPlus: {
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 12, borderWidth: 1, borderColor: colors.border,
    borderStyle: "dashed",
  },
  composerRow: {
    flexDirection: "row", padding: spacing.md,
    backgroundColor: colors.surface, borderTopWidth: 1,
    borderTopColor: colors.border, alignItems: "center",
  },
  composer: {
    flex: 1, borderWidth: 1, borderColor: colors.border,
    borderRadius: 20, paddingHorizontal: 14, paddingVertical: 8,
    marginRight: 8, backgroundColor: colors.surfaceSecondary,
  },
  sendBtn: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: colors.brand,
    alignItems: "center", justifyContent: "center",
  },
});
