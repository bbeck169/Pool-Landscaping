/**
 * Phase 20B mobile A.1 · Customer chat threads — list.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, Pressable, RefreshControl,
  Modal } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";

export default function PortalChats() {
  const router = useRouter();
  const [threads, setThreads] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [subject, setSubject] = useState("");
  const [firstMsg, setFirstMsg] = useState("");

  const load = useCallback(async () => {
    try { setThreads(await api.get("/portal/chats")); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const create = async () => {
    if (!subject.trim()) return;
    const c = await api.post("/portal/chats",
                              { subject, first_message: firstMsg });
    setShowNew(false); setSubject(""); setFirstMsg("");
    router.push({ pathname: "/portal/chats/[id]", params: { id: c.id } } as any);
  };

  return (
    <View style={styles.root}>
      <Header title="Chat Threads" subtitle="Ongoing conversations with support" />
      {loading ? <Loading testID="portal-chats-loading" /> : (
        <FlatList
          testID="portal-chats-list"
          data={threads}
          keyExtractor={(t) => t.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: 120 }}
          refreshControl={
            <RefreshControl refreshing={refreshing}
                            onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <Pressable style={styles.row} testID={`chat-row-${item.id}`}
                       onPress={() => router.push({
                         pathname: "/portal/chats/[id]",
                         params: { id: item.id },
                       } as any)}>
              <View style={styles.rowIcon}>
                <Ionicons name="chatbubble-ellipses-outline"
                          size={20} color={colors.brand}/>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle} numberOfLines={1}>{item.subject}</Text>
                <Text style={styles.rowMeta}>{(item.last_message_at || "").slice(0, 10)}</Text>
              </View>
              {item.unread_by_customer > 0 && (
                <View style={styles.badge}>
                  <Text style={styles.badgeText}>{item.unread_by_customer}</Text>
                </View>
              )}
              <Ionicons name="chevron-forward" size={16} color={colors.muted}/>
            </Pressable>
          )}
          ListEmptyComponent={() => (
            <View style={styles.empty}>
              <Ionicons name="chatbubbles-outline" size={40} color={colors.muted}/>
              <Text style={styles.emptyText}>
                No threads yet. Tap New to reach the team.
              </Text>
            </View>
          )}
        />
      )}

      <Pressable style={styles.fab} onPress={() => setShowNew(true)}
                 testID="portal-chats-new-fab">
        <Ionicons name="add" size={26} color="#fff" />
      </Pressable>

      <Modal visible={showNew} transparent animationType="slide"
             onRequestClose={() => setShowNew(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalBody}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>New Message</Text>
              <Pressable onPress={() => setShowNew(false)}>
                <Ionicons name="close" size={22} color={colors.muted}/>
              </Pressable>
            </View>
            <AppTextInput value={subject} onChangeText={setSubject}
                       placeholder="Subject"
                       placeholderTextColor={colors.muted}
                       style={styles.input}
                       testID="chat-new-subject" />
            <AppTextInput value={firstMsg} onChangeText={setFirstMsg}
                       placeholder="Your message…" multiline
                       placeholderTextColor={colors.muted}
                       style={[styles.input, { minHeight: 100 }]}
                       testID="chat-new-body" />
            <Pressable style={styles.submit} onPress={create}
                       testID="chat-new-submit">
              <Text style={styles.submitText}>Send</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md,
         backgroundColor: colors.surface, padding: spacing.md,
         borderRadius: radius.lg, marginBottom: spacing.sm,
         borderWidth: 1, borderColor: colors.border },
  rowIcon: { width: 40, height: 40, borderRadius: 20,
             backgroundColor: colors.brandTertiary, alignItems: "center",
             justifyContent: "center" },
  rowTitle: { fontFamily: font.semibold, fontSize: fontSize.base,
              color: colors.onSurface },
  rowMeta: { fontFamily: font.regular, fontSize: fontSize.sm,
             color: colors.muted, marginTop: 2 },
  badge: { minWidth: 22, height: 22, paddingHorizontal: 6, borderRadius: 11,
           backgroundColor: colors.brand, alignItems: "center",
           justifyContent: "center" },
  badgeText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.sm },
  fab: { position: "absolute", right: 24, bottom: 24, width: 56, height: 56,
         borderRadius: 28, backgroundColor: colors.brand, alignItems: "center",
         justifyContent: "center", elevation: 4 },
  empty: { paddingVertical: 60, alignItems: "center" },
  emptyText: { color: colors.muted, marginTop: spacing.md,
               textAlign: "center", fontFamily: font.regular,
               fontSize: fontSize.base },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)",
             justifyContent: "flex-end" },
  modalBody: { backgroundColor: colors.surface, padding: spacing.lg,
               borderTopLeftRadius: 20, borderTopRightRadius: 20 },
  modalHeader: { flexDirection: "row", justifyContent: "space-between",
                 alignItems: "center", marginBottom: spacing.md },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.xl,
                color: colors.onSurface },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
           padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base,
           color: colors.onSurface, marginBottom: spacing.sm,
           borderWidth: 1, borderColor: colors.border },
  submit: { backgroundColor: colors.brand, borderRadius: radius.md,
            paddingVertical: 12, alignItems: "center", marginTop: spacing.sm },
  submitText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.base },
});
