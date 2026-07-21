/**
 * AIDockDrawer — full-screen modal with employee picker + chat (B1).
 * Admin/super_admin only.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput,
  ActivityIndicator, FlatList, KeyboardAvoidingView, Platform, Modal, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import {
  listAIEmployees, getAICreditsBalance, chatSimple,
  listPendingActions, approveAction, rejectAction,
  AIEmployee, AIAction,
} from "@/src/api/aiDock";

type Msg = { id: string; role: "user" | "assistant"; text: string };

type Props = { visible: boolean; onClose: () => void };

export default function AIDockDrawer({ visible, onClose }: Props) {
  const insets = useSafeAreaInsets();
  const [employees, setEmployees] = useState<AIEmployee[]>([]);
  const [balance, setBalance] = useState<number | null>(null);
  const [actions, setActions] = useState<AIAction[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeEmp, setActiveEmp] = useState<AIEmployee | null>(null);

  const loadRoster = useCallback(async () => {
    setLoading(true);
    try {
      const [emps, bal, acts] = await Promise.all([
        listAIEmployees().catch(() => []),
        getAICreditsBalance().catch(() => null),
        listPendingActions().catch(() => []),
      ]);
      setEmployees((emps || []).filter((e: any) => e.active !== false));
      setBalance(bal?.balance ?? null);
      setActions(Array.isArray(acts) ? acts.filter((a: any) => a.status === "pending") : []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (visible) loadRoster();
  }, [visible, loadRoster]);

  const onApprove = async (aid: string) => {
    try {
      await approveAction(aid);
      setActions((prev) => prev.filter((a) => a.id !== aid));
      const bal = await getAICreditsBalance().catch(() => null);
      if (bal) setBalance(bal.balance);
    } catch (e: any) {
      Alert.alert("Error", e.message || "Approval failed");
    }
  };

  const onReject = async (aid: string) => {
    try {
      await rejectAction(aid);
      setActions((prev) => prev.filter((a) => a.id !== aid));
    } catch (e: any) {
      Alert.alert("Error", e.message || "Rejection failed");
    }
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} testID="ai-dock-drawer">
      <View style={[styles.root, { paddingTop: insets.top || 16 }]}>
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <Ionicons name="sparkles" size={20} color={colors.brand} />
            <Text style={styles.headerTitle}>AI Dock</Text>
            {balance !== null && (
              <View testID="ai-dock-credits-pill" style={styles.creditsPill}>
                <Text style={styles.creditsText}>{balance}c</Text>
              </View>
            )}
          </View>
          <TouchableOpacity onPress={onClose} hitSlop={12}>
            <Ionicons name="close" size={24} color={colors.muted} />
          </TouchableOpacity>
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} />
        ) : activeEmp ? (
          <ChatView
            employee={activeEmp}
            onBack={() => { setActiveEmp(null); loadRoster(); }}
            insets={insets}
          />
        ) : (
          <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
            {/* Pending actions */}
            {actions.length > 0 && (
              <View style={styles.actionsSection}>
                <Text style={styles.sectionLabel}>Pending Approvals ({actions.length})</Text>
                {actions.map((a) => (
                  <View key={a.id} style={styles.actionCard} testID={`ai-action-${a.id}`}>
                    <Text style={styles.actionLabel}>{a.label || a.action_type}</Text>
                    <Text style={styles.actionDesc} numberOfLines={2}>{a.description || ""}</Text>
                    <View style={styles.actionBtns}>
                      <TouchableOpacity
                        testID={`ai-action-approve-${a.id}`}
                        style={styles.approveBtn}
                        onPress={() => onApprove(a.id)}
                      >
                        <Ionicons name="checkmark" size={14} color="#fff" />
                        <Text style={styles.approveBtnText}>Approve</Text>
                      </TouchableOpacity>
                      <TouchableOpacity style={styles.rejectBtn} onPress={() => onReject(a.id)}>
                        <Ionicons name="close" size={14} color={colors.error} />
                        <Text style={styles.rejectBtnText}>Discard</Text>
                      </TouchableOpacity>
                    </View>
                  </View>
                ))}
              </View>
            )}

            {/* Employee grid */}
            <Text style={styles.sectionLabel}>AI Team</Text>
            <View style={styles.empGrid}>
              {employees.map((e) => (
                <TouchableOpacity
                  key={e.id}
                  testID={`ai-employee-${e.key || e.id}`}
                  style={styles.empCard}
                  activeOpacity={0.7}
                  onPress={() => setActiveEmp(e)}
                >
                  <View style={styles.empAvatar}>
                    <Ionicons name={(e.icon || "sparkles") as any} size={22} color="#fff" />
                  </View>
                  <Text style={styles.empName}>{e.name}</Text>
                  <Text style={styles.empRole} numberOfLines={1}>{e.role}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </ScrollView>
        )}
      </View>
    </Modal>
  );
}

function ChatView({ employee, onBack, insets }: { employee: AIEmployee; onBack: () => void; insets: any }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const sessionRef = useRef<string | null>(null);
  const listRef = useRef<FlatList>(null);

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setInput("");
    setMessages((m) => [...m, { id: `u-${Date.now()}`, role: "user", text: trimmed }]);
    setSending(true);
    try {
      const res = await chatSimple(employee.id, trimmed, sessionRef.current);
      sessionRef.current = res.session_id;
      setMessages((m) => [...m, { id: `a-${Date.now()}`, role: "assistant", text: res.reply }]);
    } catch (e: any) {
      setMessages((m) => [...m, { id: `e-${Date.now()}`, role: "assistant", text: `⚠️ ${e?.message || "Error"}` }]);
    } finally {
      setSending(false);
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 100);
    }
  }, [employee.id, sending]);

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <View style={styles.chatHeader}>
        <TouchableOpacity onPress={onBack} hitSlop={12}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <View style={styles.chatEmpAvatar}>
          <Ionicons name={(employee.icon || "sparkles") as any} size={16} color="#fff" />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.chatEmpName}>{employee.name}</Text>
          <Text style={styles.chatEmpRole}>{employee.role}</Text>
        </View>
      </View>
      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(m) => m.id}
        contentContainerStyle={styles.chatList}
        renderItem={({ item }) => (
          <View style={[styles.bubble, item.role === "user" ? styles.bubbleUser : styles.bubbleAI]}>
            <Text style={[styles.bubbleText, item.role === "user" && styles.bubbleTextUser]}>
              {item.text}
            </Text>
          </View>
        )}
        ListEmptyComponent={
          <View style={styles.chatEmpty}>
            <Ionicons name="sparkles" size={28} color={colors.brand} />
            <Text style={styles.chatEmptyText}>Start chatting with {employee.name}</Text>
          </View>
        }
      />
      <View style={[styles.composer, { paddingBottom: insets.bottom || 12 }]}>
        <TextInput
          style={styles.composerInput}
          value={input}
          onChangeText={setInput}
          placeholder={`Message ${employee.name}…`}
          placeholderTextColor={colors.muted}
          multiline
          returnKeyType="send"
          onSubmitEditing={() => send(input)}
        />
        <TouchableOpacity
          style={[styles.sendBtn, (!input.trim() || sending) && styles.sendBtnDisabled]}
          onPress={() => send(input)}
          disabled={!input.trim() || sending}
        >
          {sending ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Ionicons name="send" size={16} color="#fff" />
          )}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  headerLeft: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  headerTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  creditsPill: { backgroundColor: "#DCFCE7", borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  creditsText: { fontFamily: font.bold, fontSize: 11, color: "#166534" },
  content: { padding: spacing.lg, paddingBottom: 40 },
  sectionLabel: { fontFamily: font.bold, fontSize: 11, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: spacing.sm },
  actionsSection: { marginBottom: spacing.xl },
  actionCard: { backgroundColor: "#FEF3C7", borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.sm, borderWidth: 1, borderColor: "#FDE68A" },
  actionLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#92400E" },
  actionDesc: { fontFamily: font.regular, fontSize: fontSize.sm, color: "#78350F", marginTop: 2 },
  actionBtns: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  approveBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brand, paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.sm },
  approveBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  rejectBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.surface, paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  rejectBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.error },
  empGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  empCard: { width: "30%", flexGrow: 1, alignItems: "center", backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border },
  empAvatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center", marginBottom: spacing.xs },
  empName: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, textAlign: "center" },
  empRole: { fontFamily: font.regular, fontSize: 10, color: colors.muted, textAlign: "center" },
  /* Chat */
  chatHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  chatEmpAvatar: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  chatEmpName: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  chatEmpRole: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  chatList: { padding: spacing.lg, paddingBottom: spacing.md },
  chatEmpty: { alignItems: "center", paddingTop: 60, gap: 8 },
  chatEmptyText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted },
  bubble: { maxWidth: "85%", padding: spacing.md, borderRadius: radius.md, marginBottom: spacing.sm },
  bubbleUser: { backgroundColor: colors.brand, alignSelf: "flex-end" },
  bubbleAI: { backgroundColor: colors.surfaceSecondary, alignSelf: "flex-start" },
  bubbleText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 20 },
  bubbleTextUser: { color: "#fff" },
  composer: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  composerInput: { flex: 1, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 10, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, maxHeight: 100, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  sendBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  sendBtnDisabled: { opacity: 0.4 },
});
