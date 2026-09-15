/** Phase 17B · Mobile — Atlas Agent chat. */
import React, { useCallback, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, KeyboardAvoidingView, Platform, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { AdminOnlyGate, BrandPill } from "./_shared";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Msg = { role: "user" | "assistant"; content: string;
              tool_calls?: any[]; at?: string };

export default function AtlasAgentMobile() {
  return (
    <AdminOnlyGate title="Atlas Agent">
      <Inner />
    </AdminOnlyGate>
  );
}

function Inner() {
  const [conversations, setConversations] = useState<any[]>([]);
  const [convId, setConvId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const scrollRef = useRef<ScrollView>(null);

  const loadConvs = async () => {
    try {
      const rows = await api.get("/seo/atlas/conversations");
      setConversations(Array.isArray(rows) ? rows : (rows.items || []));
    } catch { /* ignore */ }
  };
  useFocusEffect(useCallback(() => { loadConvs(); }, []));

  const loadConv = async (cid: string) => {
    const c = await api.get(`/seo/atlas/conversations/${cid}`);
    setConvId(cid);
    setMsgs(c.messages || []);
    setDrawerOpen(false);
  };

  const send = async () => {
    if (!input.trim()) return;
    const userText = input;
    setInput("");
    setMsgs((prev) => [...prev, { role: "user", content: userText }]);
    setSending(true);
    try {
      const r = await api.post("/seo/atlas/chat",
                                 { message: userText,
                                    conversation_id: convId }, 90000);
      setConvId(r.conversation_id);
      setMsgs((prev) => [...prev, r.assistant]);
      await loadConvs();
    } catch (e: any) {
      setMsgs((prev) => [...prev, {
        role: "assistant",
        content: `Error: ${e?.message || "unknown"}`,
      }]);
    } finally {
      setSending(false);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 100);
    }
  };

  const newConv = () => {
    setConvId(null);
    setMsgs([]);
    setDrawerOpen(false);
  };

  return (
    <KeyboardAvoidingView style={styles.root}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={80}>
      <Header title="Atlas Agent" />

      <View style={styles.topBar}>
        <Pressable style={styles.topBtn}
                   onPress={() => setDrawerOpen(!drawerOpen)}
                   testID="atlas-history-toggle">
          <Ionicons name="chatbubbles-outline" size={16}
                     color={colors.brand} />
          <Text style={styles.topBtnText}>
            {drawerOpen ? "Hide history" : `History (${conversations.length})`}
          </Text>
        </Pressable>
        <Pressable style={styles.topBtn} onPress={newConv}
                    testID="atlas-new-conv">
          <Ionicons name="add" size={16} color={colors.brand} />
          <Text style={styles.topBtnText}>New</Text>
        </Pressable>
      </View>

      {drawerOpen && (
        <ScrollView style={styles.drawer}
                     contentContainerStyle={{ padding: spacing.md }}>
          {conversations.length === 0 ? (
            <Text style={styles.emptyDrawer}>No conversations yet.</Text>
          ) : (
            conversations.map((c) => (
              <Pressable key={c.id} style={styles.drawerRow}
                          onPress={() => loadConv(c.id)}
                          testID={`atlas-conv-${c.id}`}>
                <Ionicons name="chatbubble-outline" size={14}
                           color={colors.brand} />
                <Text style={styles.drawerText} numberOfLines={1}>
                  {(c.last_message_at || c.created_at || "").slice(0, 16)
                     .replace("T", " ")}
                </Text>
              </Pressable>
            ))
          )}
        </ScrollView>
      )}

      <ScrollView ref={scrollRef}
                   contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 100 }}>
        {msgs.length === 0 ? (
          <View style={styles.hero}>
            <Ionicons name="sparkles" size={32} color={colors.brand} />
            <Text style={styles.heroTitle}>Ask Atlas</Text>
            <Text style={styles.heroBody}>
              Try: “Run an audit on https://example.com” or
              “Generate a topical map for pool cleaning phoenix”.
            </Text>
          </View>
        ) : (
          msgs.map((m, i) => (
            <View key={i}
                  style={[styles.msg,
                          m.role === "user" ? styles.msgUser
                                              : styles.msgBot]}>
              <Text style={[styles.msgText,
                            m.role === "user" && { color: "#fff" }]}>
                {m.content}
              </Text>
              {(m.tool_calls || []).map((tc: any, j: number) => (
                <View key={j} style={styles.toolCard}>
                  <View style={styles.toolHead}>
                    <Ionicons name="construct-outline" size={12}
                               color={colors.brand} />
                    <Text style={styles.toolName}>{tc.name}</Text>
                    <BrandPill text={tc.status || "?"}
                                tone={tc.status === "ok" ? "green"
                                        : tc.status === "error" ? "red"
                                        : "amber"} />
                  </View>
                  <Text style={styles.toolArgs}
                         numberOfLines={4}>
                    {JSON.stringify(tc.args || {}, null, 2)}
                  </Text>
                  {tc.result && (
                    <Text style={styles.toolResult} numberOfLines={6}>
                      {JSON.stringify(tc.result, null, 2)}
                    </Text>
                  )}
                </View>
              ))}
            </View>
          ))
        )}
        {sending && (
          <View style={styles.thinking}>
            <ActivityIndicator color={colors.brand} size="small" />
            <Text style={styles.thinkingText}>Atlas is thinking…</Text>
          </View>
        )}
      </ScrollView>

      <View style={styles.composer}>
        <AppTextInput style={styles.composerInput}
                    placeholder="Ask Atlas…" placeholderTextColor={colors.muted}
                    value={input} onChangeText={setInput}
                    multiline
                    testID="atlas-input" />
        <Pressable style={[styles.sendBtn,
                            (sending || !input.trim()) && { opacity: 0.5 }]}
                    disabled={sending || !input.trim()}
                    onPress={send}
                    testID="atlas-send">
          <Ionicons name="send" size={18} color="#fff" />
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  topBar: {
    flexDirection: "row", gap: spacing.sm,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  topBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: spacing.md, paddingVertical: 8,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
  },
  topBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm,
                 color: colors.brand },
  drawer: {
    maxHeight: 200,
    backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  drawerRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.sm, borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  drawerText: { flex: 1, fontFamily: font.regular,
                 fontSize: fontSize.sm, color: colors.onSurface },
  emptyDrawer: { fontFamily: font.regular, fontSize: fontSize.sm,
                  color: colors.muted, padding: spacing.md,
                  textAlign: "center" },
  hero: {
    alignItems: "center", gap: spacing.sm,
    padding: spacing["2xl"],
  },
  heroTitle: { fontFamily: font.bold, fontSize: fontSize.xl,
                color: colors.onSurface, marginTop: spacing.sm },
  heroBody: { fontFamily: font.regular, fontSize: fontSize.base,
               color: colors.muted, textAlign: "center" },
  msg: { marginBottom: spacing.md, borderRadius: radius.lg,
          padding: spacing.md, maxWidth: "92%" },
  msgUser: { alignSelf: "flex-end", backgroundColor: colors.brand },
  msgBot: { alignSelf: "flex-start", backgroundColor: colors.surface,
             borderWidth: 1, borderColor: colors.border },
  msgText: { fontFamily: font.regular, fontSize: fontSize.base,
              color: colors.onSurface, lineHeight: 20 },
  toolCard: {
    marginTop: spacing.sm, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary, padding: spacing.sm,
  },
  toolHead: { flexDirection: "row", alignItems: "center",
               gap: 6, marginBottom: 4 },
  toolName: { flex: 1, fontFamily: font.bold,
               fontSize: fontSize.sm, color: colors.brand },
  toolArgs: { fontFamily: "Courier", fontSize: 10,
               color: colors.muted },
  toolResult: {
    marginTop: 6, padding: 6, borderRadius: 4,
    backgroundColor: "#0F172A", color: "#E2E8F0",
    fontFamily: "Courier", fontSize: 10,
  },
  thinking: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md,
  },
  thinkingText: { fontFamily: font.regular, fontSize: fontSize.sm,
                   color: colors.muted },
  composer: {
    flexDirection: "row", gap: spacing.sm, padding: spacing.md,
    backgroundColor: colors.surface,
    borderTopWidth: 1, borderTopColor: colors.border,
    alignItems: "flex-end",
  },
  composerInput: {
    flex: 1, backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, padding: spacing.md,
    maxHeight: 120, fontFamily: font.regular,
    fontSize: fontSize.base, color: colors.onSurface,
    borderWidth: 1, borderColor: colors.border,
  },
  sendBtn: {
    width: 46, height: 46, borderRadius: 23,
    backgroundColor: colors.brand, alignItems: "center",
    justifyContent: "center",
  },
});
