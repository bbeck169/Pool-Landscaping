/**
 * Phase 20B mobile A.1 · Customer chat thread detail.
 * Polls every 4s for new messages while focused.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, TextInput, Pressable,
  KeyboardAvoidingView, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

const POLL_MS = 4000;

export default function ChatThread() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [msgs, setMsgs] = useState<any[]>([]);
  const [chat, setChat] = useState<any>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const listRef = useRef<FlatList>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.get(`/portal/chats/${id}/messages`);
      setChat(d.chat); setMsgs(d.messages || []);
      api.post(`/portal/chats/${id}/read`, {}).catch(() => {});
    } catch {}
  }, [id]);

  useFocusEffect(useCallback(() => {
    load();
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [load]));

  useEffect(() => {
    setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 100);
  }, [msgs.length]);

  const send = async () => {
    if (!text.trim() || sending) return;
    setSending(true);
    try {
      const m = await api.post(`/portal/chats/${id}/messages`, { body: text });
      setMsgs([...msgs, m]); setText("");
    } catch {}
    finally { setSending(false); }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }}
                          behavior={Platform.OS === "ios" ? "padding" : undefined}
                          keyboardVerticalOffset={80}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} testID="chat-back">
          <Ionicons name="chevron-back" size={22} color={colors.brand}/>
        </Pressable>
        <Text style={styles.headerTitle} numberOfLines={1}>
          {chat?.subject || "Thread"}
        </Text>
        <View style={{ width: 22 }} />
      </View>

      <FlatList
        ref={listRef}
        testID="chat-messages"
        data={msgs}
        keyExtractor={(m) => m.id}
        contentContainerStyle={{ padding: spacing.md, gap: spacing.sm }}
        renderItem={({ item }) => {
          const mine = item.sender_role === "customer";
          return (
            <View style={[styles.bubbleWrap,
                          mine ? { alignItems: "flex-end" }
                               : { alignItems: "flex-start" }]}>
              <View style={[styles.bubble,
                            mine ? styles.bubbleMine : styles.bubbleOther]}>
                <Text style={[styles.sender,
                              mine ? { color: "rgba(255,255,255,0.7)" }
                                   : { color: colors.muted }]}>
                  {item.sender_name || item.sender_role}
                </Text>
                <Text style={[styles.body,
                              mine ? { color: "#fff" }
                                   : { color: colors.onSurface }]}>
                  {item.body}
                </Text>
              </View>
            </View>
          );
        }}
        style={{ backgroundColor: colors.surfaceSecondary }}
      />

      <View style={styles.composer}>
        <TextInput value={text} onChangeText={setText}
                   placeholder="Type a message…"
                   placeholderTextColor={colors.muted}
                   style={styles.input}
                   multiline testID="chat-input" />
        <Pressable style={styles.send} onPress={send} disabled={sending}
                   testID="chat-send">
          <Ionicons name="send" size={18} color="#fff" />
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center",
            paddingHorizontal: spacing.md, paddingVertical: spacing.md,
            backgroundColor: colors.surface,
            borderBottomWidth: 1, borderColor: colors.border,
            gap: spacing.md },
  headerTitle: { flex: 1, fontFamily: font.bold, fontSize: fontSize.lg,
                 color: colors.onSurface },
  bubbleWrap: {},
  bubble: { maxWidth: "82%", padding: spacing.md, borderRadius: radius.lg },
  bubbleMine: { backgroundColor: colors.brand,
                borderBottomRightRadius: 4 },
  bubbleOther: { backgroundColor: colors.surface,
                 borderBottomLeftRadius: 4,
                 borderWidth: 1, borderColor: colors.border },
  sender: { fontFamily: font.semibold, fontSize: 11, marginBottom: 2 },
  body: { fontFamily: font.regular, fontSize: fontSize.base },
  composer: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm,
              padding: spacing.md, backgroundColor: colors.surface,
              borderTopWidth: 1, borderColor: colors.border },
  input: { flex: 1, backgroundColor: colors.surfaceSecondary,
           borderRadius: radius.md, padding: spacing.md,
           fontFamily: font.regular, fontSize: fontSize.base,
           color: colors.onSurface, maxHeight: 100,
           borderWidth: 1, borderColor: colors.border },
  send: { width: 42, height: 42, borderRadius: 21,
          backgroundColor: colors.brand, alignItems: "center",
          justifyContent: "center" },
});
