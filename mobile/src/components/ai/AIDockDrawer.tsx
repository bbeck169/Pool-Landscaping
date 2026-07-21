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
  listAIEmployees, getAICreditsBalance,
  createConversation, sendConversationMessage,
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
            refreshBalance={async () => {
              const bal = await getAICreditsBalance().catch(() => null);
              if (bal) setBalance(bal.balance);
            }}
          />
        ) : (
          <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
            {/* Pending actions */}
            {actions.length > 0 && (
              <View style={styles.actionsSection}>
                <Text style={styles.sectionLabel}>Pending Approvals ({actions.length})</Text>
                {actions.map((a) => (
                  <View key={a.id} style={styles.actionCard} testID={`ai-action-${a.id}`}>
                    <Text style={styles.actionLabel}>{a.title || a.action}</Text>
                    <Text style={styles.actionDesc} numberOfLines={2}>{a.summary || ""}</Text>
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

function ChatView({ employee, onBack, insets, refreshBalance }: { employee: AIEmployee; onBack: () => void; insets: any; refreshBalance: () => void }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [convId, setConvId] = useState<string | null>(null);
  const [pendingActions, setPendingActions] = useState<AIAction[]>([]);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<FlatList>(null);

  // Load or create a conversation on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const conv = await createConversation(employee.id, `${employee.name} chat`);
        if (cancelled) return;
        setConvId(conv.id);
        // Load pending actions scoped to this employee
        const acts = await listPendingActions(employee.key).catch(() => []);
        if (!cancelled) setPendingActions((acts || []).filter((a: any) => a.status === "pending"));
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Failed to start conversation");
      }
    })();
    return () => { cancelled = true; };
  }, [employee.id, employee.key, employee.name]);

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sending || !convId) return;
    setInput("");
    setError(null);
    setSending(true);
    try {
      const res = await sendConversationMessage(employee.id, convId, trimmed);
      // Response shape: { user_message, assistant_message, action? }
      if (res.user_message) {
        setMessages((m) => [...m, { id: res.user_message.id, role: "user", text: res.user_message.text }]);
      }
      if (res.assistant_message) {
        setMessages((m) => [...m, { id: res.assistant_message.id, role: "assistant", text: res.assistant_message.text }]);
      }
      if (res.action) {
        setPendingActions((p) => [res.action, ...p]);
      }
      refreshBalance();
    } catch (e: any) {
      setError(e?.message || "Send failed");
      setMessages((m) => [...m, { id: `e-${Date.now()}`, role: "assistant", text: `⚠️ ${e?.message || "Error"}` }]);
    } finally {
      setSending(false);
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 100);
    }
  }, [employee.id, convId, sending, refreshBalance]);

  const onApproveChat = async (aid: string) => {
    try {
      await approveAction(aid);
      setPendingActions((p) => p.filter((a) => a.id !== aid));
      refreshBalance();
    } catch (e: any) {
      setError(e?.message || "Approval failed");
    }
  };

  const onRejectChat = async (aid: string) => {
    try {
      await rejectAction(aid);
      setPendingActions((p) => p.filter((a) => a.id !== aid));
    } catch (e: any) {
      setError(e?.message || "Rejection failed");
    }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <View style={styles.chatHeader}>
        <TouchableOpacity onPress={onBack} hitSlop={12} testID="ai-dock-back">
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

      {/* Pending actions scoped to this employee */}
      {pendingActions.length > 0 && (
        <View style={styles.chatActionsBar}>
          <Text style={styles.chatActionsLabel}>Pending approval ({pendingActions.length})</Text>
          {pendingActions.slice(0, 3).map((a) => (
            <View key={a.id} style={styles.chatActionRow} testID={`ai-dock-pending-${a.id}`}>
              <Text style={styles.chatActionTitle} numberOfLines={1}>{a.title || a.action}</Text>
              <View style={{ flexDirection: "row", gap: 6 }}>
                <TouchableOpacity
                  style={styles.approveBtn}
                  onPress={() => onApproveChat(a.id)}
                  testID={`ai-dock-approve-${a.id}`}
                >
                  <Ionicons name="checkmark" size={12} color="#fff" />
                  <Text style={styles.approveBtnText}>Approve</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.rejectBtn} onPress={() => onRejectChat(a.id)}>
                  <Text style={styles.rejectBtnText}>Discard</Text>
                </TouchableOpacity>
              </View>
            </View>
          ))}
        </View>
      )}

      {error && (
        <View style={styles.errorBar}>
          <Ionicons name="alert-circle" size={14} color={colors.error} />
          <Text style={styles.errorText}>{error}</Text>
        </View>
      )}

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
          testID="ai-dock-input"
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
          testID="ai-dock-send"
          style={[styles.sendBtn, (!input.trim() || sending || !convId) && styles.sendBtnDisabled]}
          onPress={() => send(input)}
          disabled={!input.trim() || sending || !convId}
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
  /* Chat-scoped actions & error */
  chatActionsBar: { paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  chatActionsLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 },
  chatActionRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: colors.surfaceSecondary, padding: spacing.sm, borderRadius: radius.sm, marginBottom: 4 },
  chatActionTitle: { flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface, marginRight: 8 },
  errorBar: { flexDirection: "row", alignItems: "center", gap: 6, marginHorizontal: spacing.lg, marginTop: spacing.sm, padding: spacing.sm, borderRadius: radius.sm, backgroundColor: colors.surfaceSecondary },
  errorText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.error, flex: 1 },
});
