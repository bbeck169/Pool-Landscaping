/**
 * Phase 25b · Customer profile dark-chassis parts (mobile parity with
 * web Phase 27 · 66328fc7d).
 *
 *   * KPITileGrid — 6 tiles in locked order fed by
 *     ``GET /customers/{id}/kpi-summary``. Past Due / Overdue → #7F1D1D
 *     when > 0, Credit → #064E3B when > 0, others neutral dark. Static
 *     soft white glow on every tile (Phase 25 KPI_GLOW).
 *   * QuickActionTileGrid — mobile analogue of web's tab-picker tiles:
 *     each tile scrolls the profile to its section in the stack.
 *   * LightPanel — light inset card that keeps un-restyled child
 *     sections readable on the navy page; doubles as a scroll anchor.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet, type LayoutChangeEvent } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, font, fontSize, spacing } from "@/src/theme";
import {
  DARK_BG, DARK_BORDER, DARK_TILE_RADIUS, DARK_TEXT, DARK_TEXT_MUTED,
  DANGER_BG, SUCCESS_BG, KPI_GLOW,
} from "@/src/lib/customerDarkTokens";

export type KpiSummary = {
  balance_due_cents?: number; past_due_cents?: number; credit_cents?: number;
  overdue_count?: number; pending_estimates_count?: number; unread_messages_count?: number;
} | null;

const fmtMoney = (cents?: number) =>
  (Math.max(0, Number(cents || 0)) / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });

export function kpiTiles(kpi: KpiSummary) {
  const n = (v?: number) => Number(v || 0);
  return [
    { k: "balance-due", label: "Balance Due", icon: "receipt-outline", value: fmtMoney(kpi?.balance_due_cents), bg: undefined },
    { k: "past-due", label: "Past Due", icon: "alert-circle-outline", value: fmtMoney(kpi?.past_due_cents), bg: n(kpi?.past_due_cents) > 0 ? DANGER_BG : undefined },
    { k: "credit", label: "Credit", icon: "wallet-outline", value: fmtMoney(kpi?.credit_cents), bg: n(kpi?.credit_cents) > 0 ? SUCCESS_BG : undefined },
    { k: "overdue", label: "Overdue", icon: "time-outline", value: String(n(kpi?.overdue_count)), bg: n(kpi?.overdue_count) > 0 ? DANGER_BG : undefined },
    { k: "pending-est", label: "Pending Estimates", icon: "document-text-outline", value: String(n(kpi?.pending_estimates_count)), bg: undefined },
    { k: "unread-msgs", label: "Unread Messages", icon: "chatbubble-outline", value: String(n(kpi?.unread_messages_count)), bg: undefined },
  ] as const;
}

export function KPITileGrid({ kpi }: { kpi: KpiSummary }) {
  return (
    <View style={s.grid} testID="cd-kpi-tile-grid">
      {kpiTiles(kpi).map((t) => (
        <View
          key={t.k}
          style={[s.tile, t.bg ? { backgroundColor: t.bg, borderColor: t.bg } : null]}
          testID={`cd-kpi-tile-${t.k}`}
        >
          <View style={s.tileHead}>
            <Ionicons name={t.icon as any} size={14} color={DARK_TEXT_MUTED} />
            <Text style={s.tileLabel} numberOfLines={1}>{t.label}</Text>
          </View>
          <Text style={s.tileValue} testID={`cd-kpi-tile-${t.k}-value`}>{t.value}</Text>
        </View>
      ))}
    </View>
  );
}

export type QuickAction = { k: string; label: string; icon: string };

export function QuickActionTileGrid({ actions, onPick }: { actions: QuickAction[]; onPick: (k: string) => void }) {
  return (
    <View style={s.grid} testID="cd-quick-action-grid">
      {actions.map((a) => (
        <Pressable
          key={a.k}
          onPress={() => onPick(a.k)}
          style={({ pressed }) => [s.qa, pressed && { opacity: 0.85 }]}
          testID={`cd-quick-action-${a.k}`}
          accessibilityRole="button"
          accessibilityLabel={`Jump to ${a.label}`}
        >
          <Ionicons name={a.icon as any} size={18} color={DARK_TEXT} />
          <Text style={s.qaLabel} numberOfLines={1}>{a.label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

export function LightPanel({ children, anchor, onAnchor, onNode }: {
  children: React.ReactNode; anchor?: string; onAnchor?: (k: string, y: number) => void;
  onNode?: (k: string, node: any) => void;
}) {
  const onLayout = anchor && onAnchor
    ? (e: LayoutChangeEvent) => onAnchor(anchor, e.nativeEvent.layout.y)
    : undefined;
  return (
    <View
      style={s.panel}
      onLayout={onLayout}
      ref={anchor && onNode ? (n) => onNode(anchor, n) : undefined}
      collapsable={false}
      testID={anchor ? `cd-section-${anchor}` : undefined}
    >
      {children}
    </View>
  );
}

const s = StyleSheet.create({
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.md },
  tile: {
    flexGrow: 1, flexBasis: "30%", minHeight: 76, padding: spacing.md, justifyContent: "space-between",
    backgroundColor: DARK_BG, borderRadius: DARK_TILE_RADIUS, borderWidth: 1, borderColor: DARK_BORDER,
    ...KPI_GLOW,
  },
  tileHead: { flexDirection: "row", alignItems: "center", gap: 4 },
  tileLabel: { flex: 1, fontFamily: font.semibold, fontSize: 10, color: DARK_TEXT_MUTED, textTransform: "uppercase", letterSpacing: 0.5 },
  tileValue: { fontFamily: font.bold, fontSize: fontSize.lg, color: DARK_TEXT, marginTop: 4 },
  qa: {
    flexGrow: 1, flexBasis: "30%", minHeight: 64, padding: spacing.sm, alignItems: "center", justifyContent: "center", gap: 4,
    backgroundColor: DARK_BG, borderRadius: DARK_TILE_RADIUS, borderWidth: 1, borderColor: DARK_BORDER,
  },
  qaLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: DARK_TEXT },
  panel: {
    backgroundColor: colors.surface, borderRadius: DARK_TILE_RADIUS, borderWidth: 1, borderColor: DARK_BORDER,
    padding: spacing.sm, marginTop: spacing.md, overflow: "hidden",
  },
});
