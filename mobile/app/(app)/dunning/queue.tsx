/** Phase 22 · Mobile — Dunning queue (read-only). */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Alert,
  ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { formatCustomerName } from "@/src/utils/formatCustomerName";

export default function DunningQueueMobile() {
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin" || role === "super_admin";

  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/dunning/queue?days=7");
      setItems(r.items || []);
    } catch {
      /* ignore */
    } finally { setLoading(false); }
  };
  useFocusEffect(useCallback(() => { if (isAdmin) load(); }, [isAdmin]));

  if (!isAdmin) return (
    <View style={styles.root}>
      <Header title="Dunning queue" />
      <View style={styles.forbid}>
        <Ionicons name="lock-closed-outline" size={28} color={colors.muted} />
        <Text style={styles.forbidTitle}>Admins only</Text>
      </View>
    </View>
  );

  const send = async (it: any) => {
    Alert.alert("Send reminder now?",
                 `${it.stage_name} → ${formatCustomerName(it)}`, [
      { text: "Cancel", style: "cancel" },
      { text: "Send", onPress: async () => {
          await api.post(
            `/dunning/invoices/${it.invoice_id}/send-reminder`,
            { stage_id: it.stage_id });
          await load();
      } },
    ]);
  };

  return (
    <View style={styles.root}>
      <Header title="Dunning queue" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 60 }}>
        {loading ? <ActivityIndicator color={colors.brand} /> : (
          items.length === 0 ? (
            <View style={styles.empty}>
              <Ionicons name="mail-open-outline" size={28}
                         color={colors.muted} />
              <Text style={styles.emptyTitle}>Nothing scheduled</Text>
              <Text style={styles.emptyBody}>
                No reminders in the next 7 days.
              </Text>
            </View>
          ) : items.map((it) => (
            <View key={`${it.invoice_id}-${it.stage_id}`}
                  style={styles.card}
                  testID={`dun-queue-${it.invoice_id}-${it.stage_id}`}>
              <View style={{ flex: 1, minWidth: 0 }}>
                <Text style={styles.title}
                       numberOfLines={1}>{it.stage_name}</Text>
                <Text style={styles.meta} numberOfLines={1}>
                  {formatCustomerName(it)} · fire {it.fire_date}
                </Text>
                <View style={styles.chipRow}>
                  {it.channels.map((c: string) => (
                    <View key={c} style={styles.chip}>
                      <Text style={styles.chipText}>{c}</Text>
                    </View>
                  ))}
                </View>
              </View>
              <View style={{ alignItems: "flex-end", gap: 6 }}>
                <Text style={styles.amount}>
                  ${it.amount.toFixed(0)}
                </Text>
                <Pressable style={styles.sendBtn}
                            onPress={() => send(it)}
                            testID={`dun-send-${it.invoice_id}`}>
                  <Ionicons name="send" size={12} color="#fff" />
                  <Text style={styles.sendText}>Send now</Text>
                </Pressable>
              </View>
            </View>
          ))
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  forbid: { padding: spacing["2xl"], alignItems: "center", gap: spacing.sm },
  forbidTitle: { fontFamily: font.bold, fontSize: fontSize.xl,
                  color: colors.onSurface, marginTop: spacing.sm },
  empty: { padding: spacing["2xl"], alignItems: "center", gap: spacing.sm },
  emptyTitle: { fontFamily: font.bold, fontSize: fontSize.lg,
                 color: colors.onSurface, marginTop: spacing.sm },
  emptyBody: { fontFamily: font.regular, fontSize: fontSize.base,
                color: colors.muted, textAlign: "center" },
  card: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, marginBottom: spacing.sm,
  },
  title: { fontFamily: font.bold, fontSize: fontSize.base,
            color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm,
           color: colors.muted, marginTop: 2 },
  chipRow: { flexDirection: "row", gap: 4, marginTop: 4 },
  chip: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999,
           backgroundColor: colors.brandTertiary },
  chipText: { fontFamily: font.bold, fontSize: 9, color: colors.brand,
               textTransform: "uppercase" },
  amount: { fontFamily: font.bold, fontSize: fontSize.base,
             color: colors.onSurface },
  sendBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brand, borderRadius: radius.sm,
    paddingHorizontal: 8, paddingVertical: 4,
  },
  sendText: { fontFamily: font.bold, fontSize: 10, color: "#fff" },
});
