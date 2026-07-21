/**
 * CustomerTasks — read-only task list for customer detail (A5).
 */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/api";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type Props = { customerId: string };

export default function CustomerTasks({ customerId }: Props) {
  const [tasks, setTasks] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useFocusEffect(
    useCallback(() => {
      setLoading(true);
      api.get(`/customer-tasks?customer_id=${customerId}`)
        .then((d) => setTasks(Array.isArray(d) ? d : []))
        .catch(() => setTasks([]))
        .finally(() => setLoading(false));
    }, [customerId])
  );

  const statusColor = (s: string) => {
    if (s === "completed") return { bg: "#DCFCE7", fg: "#166534" };
    if (s === "overdue") return { bg: "#FEE2E2", fg: "#991B1B" };
    return { bg: "#FEF3C7", fg: "#92400E" };
  };

  return (
    <View testID="customer-tasks-tab">
      <TouchableOpacity
        style={styles.sectionHeader}
        onPress={() => setExpanded(!expanded)}
        activeOpacity={0.7}
      >
        <Ionicons name="checkbox-outline" size={18} color={colors.brand} />
        <Text style={styles.sectionTitle}>Tasks ({tasks.length})</Text>
        <Ionicons name={expanded ? "chevron-up" : "chevron-down"} size={18} color={colors.muted} />
      </TouchableOpacity>

      {expanded && (
        loading ? (
          <ActivityIndicator style={{ paddingVertical: 12 }} color={colors.brand} />
        ) : tasks.length === 0 ? (
          <Text style={styles.empty}>No tasks for this customer.</Text>
        ) : (
          tasks.map((t) => {
            const sc = statusColor(t.status || "pending");
            return (
              <View key={t.id} style={styles.taskRow} testID={`task-item-${t.id}`}>
                <View style={[styles.statusDot, { backgroundColor: sc.bg }]}>
                  <Ionicons
                    name={t.status === "completed" ? "checkmark" : "time-outline"}
                    size={12}
                    color={sc.fg}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.taskTitle} numberOfLines={1}>{t.title}</Text>
                  {t.due_date && <Text style={styles.taskMeta}>Due: {t.due_date.slice(0, 10)}</Text>}
                  {t.assignee_name && <Text style={styles.taskMeta}>Assigned: {t.assignee_name}</Text>}
                </View>
                <View style={[styles.statusPill, { backgroundColor: sc.bg }]}>
                  <Text style={[styles.statusText, { color: sc.fg }]}>{t.status || "open"}</Text>
                </View>
              </View>
            );
          })
        )
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  sectionHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.sm },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, flex: 1 },
  empty: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, paddingVertical: spacing.sm },
  taskRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  statusDot: { width: 28, height: 28, borderRadius: 14, alignItems: "center", justifyContent: "center" },
  taskTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  taskMeta: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 1 },
  statusPill: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  statusText: { fontFamily: font.bold, fontSize: 9, textTransform: "uppercase", letterSpacing: 0.5 },
});
