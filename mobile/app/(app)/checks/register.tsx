/** Phase 24 · Mobile — Check register (admin-only, read-only). */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

const STATUS_META: Record<string, { color: string; label: string }> = {
  draft:    { color: "#6B7280", label: "Draft" },
  printed:  { color: "#0EA5E9", label: "Printed" },
  cleared:  { color: "#059669", label: "Cleared" },
  voided:   { color: "#DC2626", label: "Voided" },
};

export default function CheckRegisterMobile() {
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin" || role === "super_admin";

  const [checks, setChecks] = useState<any[]>([]);
  const [banks, setBanks] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, b] = await Promise.all([
        api.get("/checks/checks"),
        api.get("/checks/bank-accounts"),
      ]);
      setChecks(c.items || []);
      setBanks(b.items || []);
    } catch {
      /* ignore */
    } finally { setLoading(false); }
  }, []);
  useFocusEffect(useCallback(() => {
    if (isAdmin) load();
  }, [isAdmin, load]));

  if (!isAdmin) return (
    <View style={styles.root}>
      <Header title="Check register" />
      <View style={styles.forbid}>
        <Ionicons name="lock-closed-outline" size={28} color={colors.muted} />
        <Text style={styles.forbidTitle}>Admins only</Text>
      </View>
    </View>
  );

  const bankById = Object.fromEntries(banks.map((b) => [b.id, b]));

  return (
    <View style={styles.root}>
      <Header title="Check register" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: spacing["3xl"] }}>
        <View style={styles.summary}>
          <View style={styles.summaryPill}>
            <Text style={styles.summaryLabel}>Checks</Text>
            <Text style={styles.summaryValue}>{checks.length}</Text>
          </View>
          <View style={styles.summaryPill}>
            <Text style={styles.summaryLabel}>Banks</Text>
            <Text style={styles.summaryValue}>{banks.length}</Text>
          </View>
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: spacing.xl }}
                              color={colors.brand} />
        ) : checks.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="document-outline" size={36} color={colors.muted} />
            <Text style={styles.emptyText}>No checks yet.</Text>
            <Text style={styles.emptySub}>
              Write your first check from the desktop admin.
            </Text>
          </View>
        ) : (
          checks.map((c: any) => {
            const meta = STATUS_META[c.status]
              || { color: "#6B7280", label: c.status };
            const bank = bankById[c.bank_account_id];
            const isVoided = c.status === "voided";
            return (
              <View key={c.id}
                     style={[styles.card,
                              isVoided ? { opacity: 0.55 } : null]}
                     testID={`check-mobile-row-${c.id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={[styles.cardTitle,
                                  isVoided ? styles.strikethrough : null]}>
                    #{c.check_number} · {c.payee_name_snapshot}
                  </Text>
                  <Text style={styles.cardMeta}>
                    {c.date} · {bank?.nickname || "—"}
                    {c.memo ? ` · ${c.memo}` : ""}
                  </Text>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <View style={[styles.pill,
                                  { backgroundColor: `${meta.color}15` }]}>
                    <Text style={[styles.pillText,
                                     { color: meta.color }]}>
                      {meta.label}
                    </Text>
                  </View>
                  <Text style={[styles.amount,
                                  isVoided ? styles.strikethrough : null]}>
                    ${Number(c.amount).toFixed(2)}
                  </Text>
                </View>
              </View>
            );
          })
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  forbid: { flex: 1, alignItems: "center", justifyContent: "center",
             padding: spacing.xl },
  forbidTitle: { marginTop: spacing.sm, fontFamily: font.bold,
                   fontSize: fontSize.xl, color: colors.muted },
  summary: { flexDirection: "row", gap: spacing.sm,
              marginBottom: spacing.md },
  summaryPill: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    alignItems: "center",
  },
  summaryLabel: {
    fontFamily: font.regular, fontSize: fontSize.xs,
    color: colors.muted, textTransform: "uppercase",
  },
  summaryValue: {
    fontFamily: font.bold, fontSize: fontSize.xl,
    color: colors.onSurface, marginTop: 2,
  },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  cardTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  cardMeta: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    marginTop: 2,
  },
  pill: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
    marginBottom: 4,
  },
  pillText: {
    fontFamily: font.bold,
    fontSize: 10,
  },
  amount: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  strikethrough: {
    textDecorationLine: "line-through",
  },
  empty: {
    marginTop: spacing.xl,
    alignItems: "center",
    padding: spacing.xl,
  },
  emptyText: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.muted,
    marginTop: spacing.sm,
  },
  emptySub: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 4,
    textAlign: "center",
  },
});
