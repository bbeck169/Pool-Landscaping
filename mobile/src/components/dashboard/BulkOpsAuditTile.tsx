/**
 * Phase 39B · mobile port of web `admin/BulkOpsAuditTile.jsx`.
 * Reads the three `bulk_actions_*_24h` fields already on the
 * `/dashboard` response (zero new requests). Renders nothing when any
 * field is missing (older backend) — same defensive rule as web.
 * Parent gate: super_admin / admin / owner.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, spacing, radius, font, fontSize } from "@/src/theme";

function Stat({ icon, value, label, warn, testID }: { icon?: any; value: number; label: string; warn?: boolean; testID: string }) {
  return (
    <View style={s.stat} testID={testID}>
      {icon ? <Ionicons name={icon} size={13} color="#94A3B8" /> : null}
      <Text style={[s.value, warn && { color: "#B45309" }]} testID={`${testID}-value`}>{value}</Text>
      <Text style={s.statLabel}>{label}</Text>
    </View>
  );
}

export default function BulkOpsAuditTile({ data }: { data: any }) {
  if (data == null || data.bulk_actions_24h == null || data.bulk_actions_undone_24h == null || data.bulk_actions_expired_24h == null) {
    return null;
  }
  const total = Number(data.bulk_actions_24h) || 0;
  const undone = Number(data.bulk_actions_undone_24h) || 0;
  const expired = Number(data.bulk_actions_expired_24h) || 0;

  return (
    <View style={s.tile} testID="bulk-ops-audit-tile">
      <View style={s.head}>
        <Ionicons name="pulse-outline" size={16} color="#64748B" />
        <Text style={s.label} testID="bulk-ops-audit-tile-label">Bulk operations · last 24h</Text>
      </View>
      <View style={s.row}>
        <Stat value={total} label="bulk actions" testID="bulk-ops-audit-tile-total" />
        <Stat icon="arrow-undo-outline" value={undone} label="undone" testID="bulk-ops-audit-tile-undone" />
        <Stat icon="time-outline" value={expired} label="expired" warn={expired > 0} testID="bulk-ops-audit-tile-expired" />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  tile: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: "#E2E8F0", padding: spacing.lg, marginBottom: spacing.lg },
  head: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: spacing.sm },
  label: { fontFamily: font.semibold, fontSize: 11, color: "#64748B", letterSpacing: 0.6, textTransform: "uppercase" },
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.lg },
  stat: { flexDirection: "row", alignItems: "center", gap: 4 },
  value: { fontFamily: font.bold, fontSize: fontSize.base, color: "#1E293B" },
  statLabel: { fontFamily: font.regular, fontSize: fontSize.sm, color: "#64748B" },
});
