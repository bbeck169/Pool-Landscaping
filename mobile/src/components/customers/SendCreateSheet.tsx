/**
 * SendCreateSheet — action sheet for customer detail (A6).
 * Common shortcuts: New quote, New job, Send message, Send invoice, Add task, Add service note.
 */
import React from "react";
import { View, Text, StyleSheet, TouchableOpacity, Modal } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

const ACTIONS = [
  { key: "new-quote", icon: "document-text-outline", label: "New Quote", route: "/quote/new" },
  { key: "new-job", icon: "briefcase-outline", label: "New Job", route: "/job/new" },
  { key: "send-email", icon: "mail-outline", label: "Send Email", route: null },
  { key: "send-sms", icon: "chatbubble-outline", label: "Send SMS", route: null },
  { key: "send-invoice", icon: "receipt-outline", label: "Send Invoice", route: null },
  { key: "add-task", icon: "checkbox-outline", label: "Add Task", route: null },
  { key: "add-note", icon: "document-text-outline", label: "Add Service Note", route: null },
] as const;

type Props = {
  visible: boolean;
  onClose: () => void;
  customerId: string;
  onAddNote?: () => void;
  onAddTask?: () => void;
};

export default function SendCreateSheet({ visible, onClose, customerId, onAddNote, onAddTask }: Props) {
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const onAction = (key: string) => {
    onClose();
    switch (key) {
      case "new-quote":
        router.push({ pathname: "/quote/new", params: { customer_id: customerId } });
        break;
      case "new-job":
        router.push({ pathname: "/job/new", params: { customer_id: customerId } });
        break;
      case "send-message":
        router.push({ pathname: "/communications", params: { customer_id: customerId } } as any);
        break;
      case "send-email":
        router.push({ pathname: `/customer/${customerId}/compose`, params: { channel: "email" } } as any);
        break;
      case "send-sms":
        router.push({ pathname: `/customer/${customerId}/compose`, params: { channel: "sms" } } as any);
        break;
      case "send-invoice":
        router.push({ pathname: "/invoices", params: { customer_id: customerId } } as any);
        break;
      case "add-task":
        onAddTask?.();
        break;
      case "add-note":
        onAddNote?.();
        break;
    }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <TouchableOpacity
        style={styles.overlay}
        activeOpacity={1}
        onPress={onClose}
        testID="send-create-action-sheet"
      >
        <View style={[styles.sheet, { paddingBottom: insets.bottom + 16 }]}>
          <View style={styles.handle} />
          <Text style={styles.title}>Quick Actions</Text>
          {ACTIONS.map((a) => (
            <TouchableOpacity
              key={a.key}
              testID={`send-create-${a.key}`}
              style={styles.actionRow}
              onPress={() => onAction(a.key)}
              activeOpacity={0.7}
            >
              <View style={styles.actionIcon}>
                <Ionicons name={a.icon as any} size={20} color={colors.brand} />
              </View>
              <Text style={styles.actionLabel}>{a.label}</Text>
              <Ionicons name="chevron-forward" size={16} color={colors.muted} />
            </TouchableOpacity>
          ))}
        </View>
      </TouchableOpacity>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, paddingTop: spacing.md, paddingHorizontal: spacing.lg },
  handle: { width: 36, height: 4, borderRadius: 2, backgroundColor: colors.surfaceTertiary, alignSelf: "center", marginBottom: spacing.md },
  title: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: spacing.md },
  actionRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: 14, borderTopWidth: 1, borderTopColor: colors.divider },
  actionIcon: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  actionLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, flex: 1 },
});
