/**
 * TD-84 b2 · one line item card in the Uncategorized report. Two taxonomy
 * buttons (amber when missing, web MISSING_HIGHLIGHT); checkbox in select mode.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, font, fontSize, money, radius, spacing } from "@/src/theme";
import { BulkCheckbox } from "@/src/components/bulk-select/BulkSelectToolkit";
import { rowKey, type Taxonomy, type UncatRow } from "@/src/lib/uncategorized";

const AMBER = "#F59E0B";
const fmtDate = (iso?: string) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso).slice(0, 10)
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
};

type Props = {
  row: UncatRow; selectMode: boolean; selected: boolean; busyField: Taxonomy | null;
  onToggle: () => void; onLongPress: () => void; onAssign: (field: Taxonomy) => void;
};

function TaxonomyButton({ field, row, disabled, busy, onPress }: { field: Taxonomy; row: UncatRow; disabled: boolean; busy: boolean; onPress: () => void }) {
  const missing = field === "income" ? row.missing_income : row.missing_service;
  const name = field === "income" ? row.income_category_name : row.service_category_name;
  const label = field === "income" ? "Income" : "Service";
  return (
    <Pressable
      onPress={onPress} disabled={disabled || busy}
      style={[s.tax, missing ? s.taxMissing : s.taxSet, disabled && { opacity: 0.5 }]}
      testID={`uncat-assign-${field}-${rowKey(row)}`} accessibilityRole="button"
      accessibilityLabel={missing ? `Assign ${label} category` : `${label} category ${name}`}
    >
      {busy ? <ActivityIndicator size="small" color={colors.brand} />
        : <Ionicons name={missing ? "alert-circle-outline" : "checkmark-circle"} size={15} color={missing ? "#B45309" : "#047857"} />}
      <Text style={s.taxText} numberOfLines={1}>{missing ? `Assign ${label}` : `${label}: ${name || "—"}`}</Text>
    </Pressable>
  );
}

export default function UncategorizedRow({ row, selectMode, selected, busyField, onToggle, onLongPress, onAssign }: Props) {
  const key = rowKey(row);
  return (
    <Pressable
      onPress={selectMode ? onToggle : undefined} onLongPress={onLongPress} delayLongPress={350}
      style={[s.card, selected && s.cardSelected]} testID={`uncat-row-${key}`}
    >
      <View style={s.top}>
        {selectMode ? <BulkCheckbox checked={selected} onPress={onToggle} testID={`uncat-select-${key}`} /> : null}
        <View style={{ flex: 1 }}>
          <Text style={s.meta} numberOfLines={1}>{row.invoice_number || "Invoice"} · {fmtDate(row.created_at)}</Text>
          <Text style={s.customer} numberOfLines={1}>{row.customer_name || "—"}</Text>
          <Text style={s.desc} numberOfLines={2}>{row.description || "Untitled line item"}</Text>
        </View>
        <Text style={s.amount}>{money(Number(row.amount || 0))}</Text>
      </View>
      <View style={s.taxRow}>
        {(["income", "service"] as const).map((f) => (
          <TaxonomyButton key={f} field={f} row={row} disabled={selectMode} busy={busyField === f} onPress={() => onAssign(f)} />
        ))}
      </View>
    </Pressable>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm, gap: spacing.sm },
  cardSelected: { borderColor: colors.brand, borderWidth: 1.5 },
  top: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  meta: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  customer: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
  desc: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 2 },
  amount: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  taxRow: { flexDirection: "row", gap: spacing.sm },
  tax: { flex: 1, flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, paddingHorizontal: spacing.sm, borderRadius: radius.sm, borderWidth: 1.5 },
  taxMissing: { borderColor: AMBER, backgroundColor: "#FFFBEB" },
  taxSet: { borderColor: "#A7F3D0", backgroundColor: "#ECFDF5" },
  taxText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
});
