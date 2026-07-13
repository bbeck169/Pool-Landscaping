import React, { useCallback, useRef, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TextInput, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading } from "@/src/components/ui";

export default function PortalMessages() {
  const [msgs, setMsgs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [booking, setBooking] = useState<string | null>(null);
  const scrollRef = useRef<ScrollView>(null);

  const load = useCallback(async () => {
    try {
      setMsgs(await api.get("/me/messages"));
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const send = async () => {
    const t = text.trim();
    if (!t || sending) return;
    setSending(true);
    setText("");
    const temp = { id: `temp-${Date.now()}`, sender: "customer", sender_name: "You", text: t };
    setMsgs((prev) => [...prev, temp]);
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 50);
    try {
      const res = await api.post("/me/messages", { text: t });
      setMsgs((prev) => {
        const base = prev.filter((m) => m.id !== temp.id);
        const next = [...base, res.message];
        if (res.ai_reply) next.push(res.ai_reply);
        return next;
      });
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 50);
    } catch {
      setMsgs((prev) => prev.filter((m) => m.id !== temp.id));
      setText(t);
    } finally {
      setSending(false);
    }
  };

  const book = async (slot: any) => {
    if (booking) return;
    setBooking(slot.date);
    try {
      const res = await api.post("/me/book", { date: slot.date, label: slot.label });
      setMsgs((prev) => {
        const cleared = prev.map((m) => (m.slots ? { ...m, slots: undefined } : m));
        return [...cleared, res.message];
      });
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 50);
    } catch {}
    finally { setBooking(null); }
  };

  return (
    <View style={styles.root}>
      <Header title="Messages" subtitle="Chat with our team" back />
      {loading ? (
        <Loading testID="portal-messages-loading" />
      ) : (
        <KeyboardAwareScrollView
          ref={scrollRef as any}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing.lg, flexGrow: 1, justifyContent: msgs.length ? "flex-end" : "center" }}
          bottomOffset={80}
          keyboardShouldPersistTaps="handled"
          testID="portal-messages-scroll"
        >
          {msgs.length === 0 ? (
            <View style={styles.empty}>
              <Ionicons name="chatbubbles-outline" size={48} color={colors.muted} />
              <Text style={styles.emptyText}>Send us a message — our AI assistant Marina replies instantly, and our team can jump in anytime.</Text>
            </View>
          ) : (
            msgs.map((m) => {
              const mine = m.sender === "customer";
              return (
                <View key={m.id} style={[styles.bubbleRow, mine ? styles.rowMine : styles.rowTheirs]} testID={`message-${m.id}`}>
                  <View style={[styles.bubble, mine ? styles.mine : styles.theirs]}>
                    {!mine ? (
                      <View style={styles.senderRow}>
                        {m.ai ? <Ionicons name="sparkles" size={12} color={colors.brand} /> : null}
                        <Text style={styles.sender}>{m.sender_name}</Text>
                      </View>
                    ) : null}
                    <Text style={[styles.bubbleText, mine && { color: "#fff" }]}>{m.text}</Text>
                    {m.slots?.length ? (
                      <View style={styles.slotsWrap}>
                        {m.slots.map((s: any) => (
                          <Pressable
                            key={s.date + s.window}
                            style={styles.slotChip}
                            onPress={() => book(s)}
                            disabled={!!booking}
                            testID={`book-slot-${s.date}`}
                          >
                            <Ionicons name="calendar-outline" size={14} color="#fff" />
                            <Text style={styles.slotText}>{booking === s.date ? "Requesting…" : `Book ${s.label}`}</Text>
                          </Pressable>
                        ))}
                      </View>
                    ) : null}
                  </View>
                </View>
              );
            })
          )}
          {sending ? (
            <View style={[styles.bubbleRow, styles.rowTheirs]}>
              <View style={[styles.bubble, styles.theirs]}>
                <Text style={styles.typing}>Marina is typing…</Text>
              </View>
            </View>
          ) : null}
        </KeyboardAwareScrollView>
      )}
      <View style={styles.composer}>
        <TextInput
          style={styles.input}
          value={text}
          onChangeText={setText}
          placeholder="Type a message…"
          placeholderTextColor={colors.muted}
          multiline
          testID="message-input"
        />
        <Pressable style={styles.sendBtn} onPress={send} disabled={sending || !text.trim()} testID="message-send">
          <Ionicons name="send" size={18} color="#fff" />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  empty: { alignItems: "center", gap: spacing.md, padding: spacing.xl },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center" },
  bubbleRow: { flexDirection: "row", marginBottom: spacing.sm },
  rowMine: { justifyContent: "flex-end" },
  rowTheirs: { justifyContent: "flex-start" },
  bubble: { maxWidth: "80%", borderRadius: radius.lg, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  mine: { backgroundColor: colors.brand, borderBottomRightRadius: 4 },
  theirs: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderBottomLeftRadius: 4 },
  sender: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand, marginBottom: 2 },
  senderRow: { flexDirection: "row", alignItems: "center", gap: 3, marginBottom: 2 },
  typing: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, fontStyle: "italic" },
  slotsWrap: { gap: 6, marginTop: spacing.sm },
  slotChip: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.brand, paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.md },
  slotText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  bubbleText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 20 },
  composer: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, padding: spacing.md, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border },
  input: { flex: 1, maxHeight: 120, minHeight: 44, backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, paddingHorizontal: spacing.md, paddingTop: spacing.sm, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  sendBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
});
