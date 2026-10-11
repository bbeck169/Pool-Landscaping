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
 *   * Phase 40 · web Phase 38 grouping — neutral KPI tiles teal
 *     (#115E59, slate-300 labels); Quick Action tiles slate-900 with icon
 *     accents cycling teal / indigo / slate by index (i % 3) and an indigo
 *     #4F46E5 outline on the last-picked (active) tile. SectionAnchor is a
 *     chassis-less scroll target for sections without a LightPanel.
 *   * LightPanel — light inset card that keeps un-restyled child
 *     sections readable on the navy page; doubles as a scroll anchor.
 */
import React from "react";
import { View, Text, Pressable, StyleSheet, type LayoutChangeEvent } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, font, fontSize, spacing } from "@/src/theme";
import {
  DARK_BORDER, DARK_TILE_RADIUS, DARK_TEXT, DARK_TEXT_MUTED,
  DANGER_BG, SUCCESS_BG, KPI_GLOW,
  CD_FINANCIAL_NEUTRAL_BG, CD_FINANCIAL_NEUTRAL_LABEL, CD_NAV_TILE_BG, CD_NAV_TILE_ACTIVE_BG,
  CD_ICON_ACCENTS, CD_ACTIVE_TILE_BORDER,
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
            <Ionicons name={t.icon as any} size={14} color={t.bg ? DARK_TEXT_MUTED : CD_FINANCIAL_NEUTRAL_LABEL} />
            <Text style={[s.tileLabel, !t.bg && { color: CD_FINANCIAL_NEUTRAL_LABEL }]} numberOfLines={1}>{t.label}</Text>
          </View>
          <Text style={s.tileValue} testID={`cd-kpi-tile-${t.k}-value`}>{t.value}</Text>
        </View>
      ))}
    </View>
  );
}

export type QuickAction = { k: string; label: string; icon: string };

export const qaIconColor = (i: number, active: boolean) => (active ? DARK_TEXT : CD_ICON_ACCENTS[i % CD_ICON_ACCENTS.length]);

export function QuickActionTileGrid({ actions, onPick, activeKey }: {
  actions: QuickAction[]; onPick: (k: string) => void; activeKey?: string | null;
}) {
  return (
    <View style={s.grid} testID="cd-quick-action-grid">
      {actions.map((a, i) => {
        const on = activeKey === a.k;
        return (
          <Pressable
            key={a.k}
            onPress={() => onPick(a.k)}
            style={({ pressed }) => [s.qa, on && s.qaActive, pressed && { opacity: 0.85 }]}
            testID={`cd-quick-action-${a.k}`}
            accessibilityRole="button"
            accessibilityLabel={`Jump to ${a.label}`}
            accessibilityState={{ selected: on }}
          >
            <Ionicons name={a.icon as any} size={18} color={qaIconColor(i, on)} testID={`cd-quick-action-${a.k}-icon`} />
            <Text style={s.qaLabel} numberOfLines={1}>{a.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Phase 40 · chassis-less scroll target (same anchor contract as LightPanel). */
export function SectionAnchor({ k, onAnchor, onNode, children }: {
  k: string; onAnchor: (k: string, y: number) => void; onNode: (k: string, node: any) => void; children: React.ReactNode;
}) {
  return (
    <View onLayout={(e) => onAnchor(k, e.nativeEvent.layout.y)} ref={(n) => onNode(k, n)} collapsable={false} testID={`cd-anchor-${k}`}>
      {children}
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
    backgroundColor: CD_FINANCIAL_NEUTRAL_BG, borderRadius: DARK_TILE_RADIUS, borderWidth: 1, borderColor: DARK_BORDER,
    ...KPI_GLOW,
  },
  tileHead: { flexDirection: "row", alignItems: "center", gap: 4 },
  tileLabel: { flex: 1, fontFamily: font.semibold, fontSize: 10, color: DARK_TEXT_MUTED, textTransform: "uppercase", letterSpacing: 0.5 },
  tileValue: { fontFamily: font.bold, fontSize: fontSize.lg, color: DARK_TEXT, marginTop: 4 },
  qa: {
    flexGrow: 1, flexBasis: "30%", minHeight: 64, padding: spacing.sm, alignItems: "center", justifyContent: "center", gap: 4,
    backgroundColor: CD_NAV_TILE_BG, borderRadius: DARK_TILE_RADIUS, borderWidth: 1, borderColor: DARK_BORDER,
  },
  qaActive: { backgroundColor: CD_NAV_TILE_ACTIVE_BG, borderColor: CD_ACTIVE_TILE_BORDER },
  qaLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: DARK_TEXT },
  panel: {
    backgroundColor: colors.surface, borderRadius: DARK_TILE_RADIUS, borderWidth: 1, borderColor: DARK_BORDER,
    padding: spacing.sm, marginTop: spacing.md, overflow: "hidden",
  },
});
