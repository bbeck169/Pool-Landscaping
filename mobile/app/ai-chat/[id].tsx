import React, { useCallback, useRef, useState } from "react";
import { View, Text, StyleSheet, FlatList, TextInput, Pressable, KeyboardAvoidingView, Platform, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import PersonaAvatar from "@/src/components/personas/PersonaAvatar";

type Msg = { id: string; role: "user" | "assistant"; text: string };

const SUGGESTIONS: Record<string, string[]> = {
  sales: ["Draft a follow-up for an unpaid quote", "Write a win-back offer for a lapsed customer"],
  support: ["Explain our weekly pool service", "Reply to a late-arrival complaint"],
  ops: ["How should I route 3 techs across 9 jobs?", "Tips to cut drive time"],
  marketing: ["Write a summer SMS promo", "Reply to a 4-star Google review"],
};

export default function AIChat() {
  const params = useLocalSearchParams<{ id: string; name?: string; role?: string }>();
  const insets = useSafeAreaInsets();
  const employeeId = String(params.id || "");
  const name = String(params.name || "AI Employee");
  const role = String(params.role || "");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [toolRunning, setToolRunning] = useState(false);
  const sessionRef = useRef<string | null>(null);
  const listRef = useRef<FlatList>(null);

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setInput("");
    const userMsg: Msg = { id: `u-${Date.now()}`, role: "user", text: trimmed };
    setMessages((m) => [...m, userMsg]);
    setSending(true);
    setToolRunning(false);
    try {
      const res = await api.post("/ai-employees/chat", {
        employee_id: employeeId,
        message: trimmed,
        session_id: sessionRef.current,
      });
      sessionRef.current = res.session_id;
      // Phase 34: If tool calls happened, the reply might include tool_calls metadata
      if (res.tool_calls?.length) {
        setToolRunning(true);
        // brief pause to show tool indicator before displaying reply
        await new Promise((r) => setTimeout(r, 400));
        setToolRunning(false);
      }
      setMessages((m) => [...m, { id: `a-${Date.now()}`, role: "assistant", text: res.reply }]);
    } catch (e: any) {
      setMessages((m) => [...m, { id: `e-${Date.now()}`, role: "assistant", text: `⚠️ ${e?.message || "Something went wrong. Try again."}` }]);
    } finally {
      setSending(false);
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 100);
    }
  }, [employeeId, sending]);

  return (
    <View style={styles.root}>
      <Header
        title={name}
        back
        subtitle={role}
        left={<PersonaAvatar personaId={employeeId} size={36} />}
      />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={0}>
        {messages.length === 0 ? (
          <View style={styles.empty}>
            <View style={styles.emptyAvatar}>
              <Ionicons name="sparkles" size={28} color={colors.brand} />
            </View>
            <Text style={styles.emptyTitle}>Hi, I&apos;m {name} 👋</Text>
            <Text style={styles.emptySub}>Ask me anything or try one of these:</Text>
            <View style={styles.suggestions}>
              {(SUGGESTIONS[employeeId] || []).map((s) => (
                <Pressable key={s} style={styles.suggestion} onPress={() => send(s)} testID="ai-suggestion">
                  <Text style={styles.suggestionText}>{s}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        ) : (
          <FlatList
            ref={listRef}
            testID="ai-chat-messages"
            data={messages}
            keyExtractor={(m) => m.id}
            contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing.md }}
            onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
            renderItem={({ item }) => (
              <View style={[styles.bubbleRow, item.role === "user" ? styles.rowRight : styles.rowLeft]}>
                <View style={[styles.bubble, item.role === "user" ? styles.userBubble : styles.aiBubble]}>
                  <Text style={[styles.bubbleText, item.role === "user" && { color: "#fff" }]}>{item.text}</Text>
                </View>
              </View>
            )}
          />
        )}

        {toolRunning ? (
          <View style={styles.typing} testID="tool-running-indicator">
            <Ionicons name="search" size={14} color={colors.brand} />
            <Text style={styles.typingText}>Looking up your account…</Text>
          </View>
        ) : sending ? (
          <View style={styles.typing}>
            <ActivityIndicator size="small" color={colors.brand} />
            <Text style={styles.typingText}>{name} is typing…</Text>
          </View>
        ) : null}

        <View style={[styles.inputBar, { paddingBottom: Math.max(insets.bottom, spacing.sm) }]}>
          <TextInput
            style={styles.input}
            value={input}
            onChangeText={setInput}
            placeholder="Type a message…"
            placeholderTextColor={colors.muted}
            multiline
            testID="ai-input"
          />
          <Pressable
            style={[styles.sendBtn, (!input.trim() || sending) && { opacity: 0.4 }]}
            onPress={() => send(input)}
            disabled={!input.trim() || sending}
            testID="ai-send-button"
          >
            <Ionicons name="arrow-up" size={20} color="#fff" />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  empty: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl },
  emptyAvatar: { width: 72, height: 72, borderRadius: 36, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center", marginBottom: spacing.lg },
  emptyTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  emptySub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: spacing.xs, textAlign: "center" },
  suggestions: { marginTop: spacing.lg, gap: spacing.sm, width: "100%" },
  suggestion: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border },
  suggestionText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  bubbleRow: { marginBottom: spacing.sm, flexDirection: "row" },
  rowRight: { justifyContent: "flex-end" },
  rowLeft: { justifyContent: "flex-start" },
  bubble: { maxWidth: "82%", borderRadius: radius.lg, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  userBubble: { backgroundColor: colors.brand, borderBottomRightRadius: 4 },
  aiBubble: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderBottomLeftRadius: 4 },
  bubbleText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 21 },
  typing: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingBottom: spacing.sm },
  typingText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  inputBar: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.sm, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
  input: { flex: 1, maxHeight: 120, minHeight: 44, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingTop: spacing.sm, paddingBottom: spacing.sm, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  sendBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
});
