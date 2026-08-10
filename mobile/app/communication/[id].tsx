import React, { useCallback, useRef, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TextInput, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useFocusEffect, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading } from "@/src/components/ui";

export default function CommunicationThread() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [name, setName] = useState("Customer");
  const [aiPaused, setAiPaused] = useState(false);
  const [msgs, setMsgs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<ScrollView>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.get(`/communications/${id}`);
      setName(d.customer_name);
      setAiPaused(!!d.ai_paused);
      setMsgs(d.messages || []);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const toggleAi = async () => {
    const next = !aiPaused;
    setAiPaused(next);
    try {
      await api.post(`/communications/${id}/ai-toggle?paused=${next}`);
    } catch {
      setAiPaused(!next);
    }
  };

  const send = async () => {
    const t = text.trim();
    if (!t || sending) return;
    setSending(true);
    setText("");
    try {
      const m = await api.post(`/communications/${id}/reply`, { text: t });
      setMsgs((prev) => [...prev, m]);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 50);
    } catch {
      setText(t);
    } finally {
      setSending(false);
    }
  };

  return (
    <View style={styles.root}>
      <Header
        title={name}
        subtitle="Conversation"
        back
        right={
          <Pressable style={[styles.aiToggle, aiPaused && styles.aiToggleOff]} onPress={toggleAi} testID="ai-toggle">
            <Ionicons name={aiPaused ? "pause" : "sparkles"} size={13} color={aiPaused ? colors.muted : colors.brand} />
            <Text style={[styles.aiToggleText, aiPaused && { color: colors.muted }]}>AI {aiPaused ? "Off" : "On"}</Text>
          </Pressable>
        }
      />
      {aiPaused ? (
        <View style={styles.pausedBanner} testID="ai-paused-banner">
          <Ionicons name="person" size={14} color={colors.brand} />
          <Text style={styles.pausedText}>AI paused — you&apos;re replying as a human.</Text>
        </View>
      ) : null}
      {loading ? (
        <Loading testID="thread-loading" />
      ) : (
        <KeyboardAwareScrollView
          ref={scrollRef as any}
          contentContainerStyle={{ padding: spacing.lg, flexGrow: 1, justifyContent: msgs.length ? "flex-end" : "center" }}
          bottomOffset={80}
          keyboardShouldPersistTaps="handled"
        >
          {msgs.map((m) => {
            const staff = m.sender === "business";
            return (
              <View key={m.id} style={[styles.bubbleRow, staff ? styles.rowMine : styles.rowTheirs]} testID={`thread-message-${m.id}`}>
                <View style={[styles.bubble, staff ? styles.mine : styles.theirs]}>
                  <View style={styles.senderRow}>
                    {m.ai ? <Ionicons name="sparkles" size={12} color={staff ? "#fff" : colors.brand} /> : null}
                    <Text style={[styles.sender, staff && { color: "rgba(255,255,255,0.9)" }]}>{m.sender_name}</Text>
                  </View>
                  <Text style={[styles.bubbleText, staff && { color: "#fff" }]}>{m.text}</Text>
                </View>
              </View>
            );
          })}
        </KeyboardAwareScrollView>
      )}
      <View style={styles.composer}>
        <TextInput
          style={styles.input}
          value={text}
          onChangeText={setText}
          placeholder="Reply…"
          placeholderTextColor={colors.muted}
          multiline
          testID="thread-input"
        />
        <Pressable style={styles.sendBtn} onPress={send} disabled={sending || !text.trim()} testID="thread-send">
          <Ionicons name="send" size={18} color="#fff" />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  aiToggle: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brandTertiary, paddingHorizontal: 10, height: 32, borderRadius: radius.pill },
  aiToggleOff: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  aiToggleText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  pausedBanner: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.brandTertiary, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  pausedText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand },
  bubbleRow: { flexDirection: "row", marginBottom: spacing.sm },
  rowMine: { justifyContent: "flex-end" },
  rowTheirs: { justifyContent: "flex-start" },
  bubble: { maxWidth: "80%", borderRadius: radius.lg, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  mine: { backgroundColor: colors.brand, borderBottomRightRadius: 4 },
  theirs: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderBottomLeftRadius: 4 },
  sender: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand, marginBottom: 2 },
  senderRow: { flexDirection: "row", alignItems: "center", gap: 3, marginBottom: 2 },
  bubbleText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 20 },
  composer: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, padding: spacing.md, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
  input: { flex: 1, maxHeight: 120, minHeight: 44, backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, paddingHorizontal: spacing.md, paddingTop: spacing.sm, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  sendBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
});
