/**
 * TD-admin-dashboard-outstanding-invoices-tile-mobile-parity (web 03121b822).
 * All-time Outstanding Invoices tile at the top of Revenue Insights.
 *
 * `summary` is the Dashboard-level `/payments/summary` payload (shared with
 * the RevenueChart "due" pill): `null` while loading, `undefined` after a
 * failure, object on success — same three-state contract as web.
 * `onPress` omitted → display-only (manager: `/invoices/overview` is
 * admin-only, so there's nowhere to deep-link).
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";

// Amber tone — matches PaymentsWidget's Outstanding stat.
const AMBER_BG = "#FEF9C3";
const AMBER_FG = "#A16207";
const AMBER_RULE = "#F59E0B";

export default function OutstandingInvoicesTile({ summary, onPress }: { summary: any; onPress?: () => void }) {
  const isLoading = summary === null;
  const isError = summary === undefined;
  const count = Number(summary?.outstanding_count || 0);
  const value = isLoading || isError ? "—" : money(Number(summary?.outstanding_total || 0));
  const sub = isLoading ? "loading…" : isError ? "unavailable" : `${count} invoice${count === 1 ? "" : "s"} · all time`;
  const tappable = !!onPress && !isLoading && !isError;

  return (
    <Pressable
      onPress={tappable ? onPress : undefined}
      disabled={!tappable}
      style={({ pressed }) => [s.tile, (isLoading || isError) && { opacity: 0.75 }, pressed && tappable && { opacity: 0.85 }]}
      accessibilityRole={onPress ? "button" : undefined}
      accessibilityLabel={`Outstanding invoices ${value}, ${sub}`}
      testID="tile-outstanding-invoices"
    >
      <View style={s.topRow}>
        <View style={s.chip}>
          <Ionicons name="alert-circle-outline" size={20} color="#FFFFFF" />
        </View>
        {onPress ? <Ionicons name="chevron-forward" size={18} color={AMBER_FG} testID="tile-outstanding-invoices-chevron" /> : null}
      </View>
      <Text style={s.value} testID="tile-outstanding-invoices-value">{value}</Text>
      <Text style={s.label}>Outstanding Invoices</Text>
      <Text style={s.sub} testID="tile-outstanding-invoices-sublabel">{sub}</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  tile: {
    backgroundColor: AMBER_BG, borderRadius: radius.lg, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.border, borderLeftWidth: 4, borderLeftColor: AMBER_RULE,
  },
  topRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  chip: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: "#0B1F3A", alignItems: "center", justifyContent: "center" },
  value: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm, color: AMBER_FG, marginTop: 2 },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
