/**
 * QuoteIQ Q1-UI · Mobile — AI Credits.
 *
 * Read-only balance card + last 10 transactions. Admin+super see a hint
 * to use the web app for top-ups (mobile-first flow is view + audit).
 */
import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { getCreditsBalance, listCreditTransactions } from "@/src/api/quoteiq_q1";

export default function CreditsIndex() {
  const insets = useSafeAreaInsets();
  const [balance, setBalance] = useState<any>(null);
  const [txns, setTxns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [b, t] = await Promise.all([
        getCreditsBalance(),
        listCreditTransactions({ limit: 10 }),
      ]);
      setBalance(b);
      setTxns(t?.transactions || []);
    } catch {
      setBalance(null);
      setTxns([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <Header title="AI Credits" />
      {loading && !balance ? (
        <View style={{ padding: spacing.xl, alignItems: "center" }}>
          <ActivityIndicator />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={{
            padding: spacing.md,
            paddingBottom: insets.bottom + spacing.xl,
          }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
          testID="credits-mobile-scroll"
        >
          <View style={s.card}>
            <Text style={s.small}>Current balance</Text>
            <Text
              style={[s.bigNumber, balance?.balance <= 0 && { color: "#DC2626" }]}
              testID="credits-mobile-balance"
            >
              {(balance?.balance ?? 0).toLocaleString()}
            </Text>
            <Text style={s.small}>
              of {(balance?.monthly_grant ?? 0).toLocaleString()} monthly grant
            </Text>
            <View style={s.planRow}>
              <Ionicons name="ribbon-outline" size={16} color={colors.textDim} />
              <Text style={s.planText}>
                Plan: <Text style={{ fontWeight: "700" }}>{balance?.plan}</Text>
              </Text>
            </View>
            {balance?.warning && (
              <View style={s.warn}>
                <Ionicons name="alert-circle-outline" size={18} color="#B45309" />
                <Text style={s.warnText}>
                  You're near or below the low-balance threshold. Top up from the
                  web admin.
                </Text>
              </View>
            )}
          </View>

          <Text style={s.sectionLabel}>Recent transactions</Text>
          {txns.length === 0 && (
            <Text style={s.empty}>No transactions yet.</Text>
          )}
          {txns.map((t) => (
            <View key={t.id} style={s.txnRow} testID={`credits-txn-${t.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={s.txnReason}>{t.reason}</Text>
                <Text style={s.txnMeta}>
                  {t.feature} · {new Date(t.created_at).toLocaleString()}
                </Text>
              </View>
              <Text
                style={[
                  s.txnDelta,
                  { color: t.delta < 0 ? "#DC2626" : "#059669" },
                ]}
              >
                {t.delta > 0 ? "+" : ""}
                {t.delta.toLocaleString()}
              </Text>
            </View>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  small: { fontSize: fontSize.sm, color: colors.textDim, marginBottom: 4 },
  bigNumber: {
    fontSize: 40,
    fontWeight: "700",
    color: colors.text,
    marginVertical: 4,
    fontFamily: font.bold,
  },
  planRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: spacing.sm,
  },
  planText: { fontSize: fontSize.md, color: colors.text },
  warn: {
    flexDirection: "row",
    gap: 6,
    padding: spacing.sm,
    backgroundColor: "#FEF3C7",
    borderRadius: radius.sm,
    marginTop: spacing.sm,
  },
  warnText: { flex: 1, fontSize: fontSize.sm, color: "#78350F" },
  sectionLabel: {
    fontSize: fontSize.sm,
    color: colors.textDim,
    marginBottom: spacing.sm,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  empty: {
    fontSize: fontSize.sm,
    color: colors.textDim,
    textAlign: "center",
    paddingVertical: spacing.xl,
  },
  txnRow: {
    flexDirection: "row",
    alignItems: "center",
    padding: spacing.md,
    borderRadius: radius.sm,
    backgroundColor: colors.card,
    marginBottom: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  txnReason: { fontSize: fontSize.md, color: colors.text, fontWeight: "500" },
  txnMeta: { fontSize: fontSize.xs, color: colors.textDim, marginTop: 2 },
  txnDelta: { fontSize: fontSize.md, fontWeight: "700" },
});
