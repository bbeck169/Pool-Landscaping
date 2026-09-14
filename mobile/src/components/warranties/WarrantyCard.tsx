/**
 * WarrantyCard — read-only card for a single warranty contract.
 *
 * Shared by the portal warranties screen and the admin/tech customer
 * detail section. Renders contract_name, provider, coverage window,
 * and the optional linked_summary chip.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export type LinkedSummary = {
  type: "install" | "equipment";
  label: string;
  details?: Record<string, string | undefined>;
} | null;

export type WarrantyContract = {
  id: string;
  contract_name?: string;
  provider?: string;
  coverage_start?: string;
  coverage_end?: string;
  linked_type?: string;
  linked_id?: string;
  linked_summary?: LinkedSummary;
  notes?: string;
};

function fmtDate(iso?: string): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

function isExpired(end?: string): boolean {
  if (!end) return false;
  return new Date(end) < new Date();
}

function linkIcon(type?: string): string {
  if (type === "install") return "construct-outline";
  if (type === "equipment") return "hardware-chip-outline";
  return "link-outline";
}

export default function WarrantyCard({
  warranty,
  index,
  testIdPrefix = "warranty",
}: {
  warranty: WarrantyContract;
  index: number;
  testIdPrefix?: string;
}) {
  const expired = isExpired(warranty.coverage_end);

  return (
    <View style={s.card} testID={`${testIdPrefix}-card-${index}`}>
      {/* Header: contract name */}
      <View style={s.cardHeader}>
        <Ionicons name="shield-checkmark-outline" size={18} color={expired ? colors.muted : colors.brand} />
        <Text
          style={[s.cardName, expired && s.cardNameExpired]}
          numberOfLines={2}
          testID={`${testIdPrefix}-card-name-${index}`}
        >
          {warranty.contract_name || "Unnamed Contract"}
        </Text>
        {expired && (
          <View style={s.expiredBadge}>
            <Text style={s.expiredBadgeText}>EXPIRED</Text>
          </View>
        )}
      </View>

      {/* Provider */}
      {warranty.provider ? (
        <Text style={s.provider}>{warranty.provider}</Text>
      ) : null}

      {/* Coverage window */}
      <View style={s.windowRow} testID={`${testIdPrefix}-card-window-${index}`}>
        <Ionicons name="calendar-outline" size={14} color={colors.muted} />
        <Text style={s.windowText}>
          {fmtDate(warranty.coverage_start)} → {fmtDate(warranty.coverage_end)}
        </Text>
      </View>

      {/* Linked entity summary */}
      {warranty.linked_summary ? (
        <View style={s.linkChip} testID={`${testIdPrefix}-card-link-${index}`}>
          <Ionicons name={linkIcon(warranty.linked_summary.type) as any} size={14} color={colors.brand} />
          <Text style={s.linkLabel} numberOfLines={1}>
            {warranty.linked_summary.label}
          </Text>
        </View>
      ) : null}

      {/* Notes */}
      {warranty.notes ? (
        <Text
          style={s.notes}
          numberOfLines={2}
          testID={`${testIdPrefix}-card-notes-${index}`}
        >
          {warranty.notes}
        </Text>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  cardHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 4,
  },
  cardName: {
    flex: 1,
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  cardNameExpired: {
    color: colors.muted,
  },
  expiredBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: radius.sm,
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FCA5A5",
  },
  expiredBadgeText: {
    fontFamily: font.bold,
    fontSize: 9,
    color: "#B91C1C",
    letterSpacing: 0.5,
  },
  provider: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurfaceSecondary,
    marginBottom: 4,
    marginLeft: 26,
  },
  windowRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginLeft: 26,
    marginBottom: 4,
  },
  windowText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  linkChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginLeft: 26,
    marginTop: 2,
    paddingHorizontal: 8,
    paddingVertical: 4,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.sm,
    alignSelf: "flex-start",
  },
  linkLabel: {
    fontFamily: font.medium,
    fontSize: fontSize.xs,
    color: colors.brand,
  },
  notes: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    fontStyle: "italic",
    marginTop: 4,
    marginLeft: 26,
  },
});
