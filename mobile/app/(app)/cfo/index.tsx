/**
 * Phase 32 · Step 2 — AI CFO (mobile mirror).
 *
 * Compact read-only mirror of the web dashboard. Skips charts /
 * forecast / anomalies / auto-categorize — those live on the desktop
 * per the Step 2 brief. Ships:
 *   • Period pills (MTD / QTD / YTD)
 *   • KPI cards (Revenue, Expenses, Gross, Margin, Cash, AR aging)
 *   • Top-3 revenue sources
 *   • Top-3 expense categories
 *   • Honest `mocked` badges on any field the backend flags
 *
 * Endpoints (Step-1 spine): GET /api/cfo/dashboard only.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, ScrollView, Pressable, StyleSheet, RefreshControl, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import QnAPanel from "@/src/components/cfo/QnAPanel";
import ScenarioPanel from "@/src/components/cfo/ScenarioPanel";
import { router } from "expo-router";

type Period = "mtd" | "qtd" | "ytd";

function fmtUSD(n: number | undefined): string {
  if (typeof n !== "number") return "—";
  try {
    return n.toLocaleString(undefined, {
      style: "currency", currency: "USD", maximumFractionDigits: 0,
    });
  } catch { return `$${Math.round(n)}`; }
}

function MockedBadge({ reason }: { reason?: string }) {
  return (
    <View style={s.mockedBadge} testID="mocked-badge">
      <Text style={s.mockedText}>mocked</Text>
    </View>
  );
}

function KPI({ testID, label, value, mocked, reason }: any) {
  return (
    <View style={s.kpi} testID={testID}>
      <View style={s.kpiHeader}>
        <Text style={s.kpiLabel}>{label}</Text>
        {mocked ? <MockedBadge reason={reason} /> : null}
      </View>
      <Text style={[s.kpiValue, mocked && { opacity: 0.55 }]}>{value}</Text>
      {mocked && reason ? (
        <Text style={s.kpiReason} numberOfLines={2}>{reason}</Text>
      ) : null}
    </View>
  );
}

export default function CFOMobile() {
  const { user } = useAuth();
  const role = user?.role || "";
  const allowed = role === "admin" || role === "super_admin";

  const [period, setPeriod] = useState<Period>("ytd");
  const [dash, setDash] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    if (!allowed) return;
    setLoading(true); setErr("");
    try {
      const d = await api.get(`/cfo/dashboard?period=${period}`);
      setDash(d);
    } catch (e: any) {
      setErr(e?.message || "Failed to load.");
    } finally { setLoading(false); }
  }, [allowed, period]);
  useEffect(() => { load(); }, [load]);

  if (!allowed) {
    return (
      <View style={s.centered}>
        <Ionicons name="lock-closed-outline" size={36} color={colors.muted} />
        <Text style={s.forbidden}>AI CFO is admin-only.</Text>
      </View>
    );
  }

  const revenueTop = (dash?.revenue_by_source || []).slice(0, 3);
  const expenseTop = (dash?.expense_by_category || []).slice(0, 3);

  return (
    <View style={s.root} testID="cfo-mobile">
      <Header title="AI CFO" />
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.brand} />}
      >
        {/* Period pills */}
        <View style={s.pills} testID="cfo-period-pills">
          {(["mtd","qtd","ytd"] as Period[]).map((p) => (
            <Pressable
              key={p}
              onPress={() => setPeriod(p)}
              style={[s.pill, period === p && s.pillOn]}
              testID={`cfo-period-${p}`}
            >
              <Text style={[s.pillText, period === p && s.pillTextOn]}>{p.toUpperCase()}</Text>
            </Pressable>
          ))}
        </View>

        {err ? (
          <View style={s.errBox} testID="cfo-error">
            <Ionicons name="warning-outline" size={14} color="#991B1B" />
            <Text style={s.errText}>{err}</Text>
          </View>
        ) : null}

        {loading && !dash ? (
          <View style={s.centered}>
            <ActivityIndicator size="large" color={colors.brand} />
          </View>
        ) : dash ? (
          <>
            <View style={s.grid}>
              <KPI testID="cfo-kpi-revenue" label="Revenue" value={fmtUSD(dash.revenue?.total)} />
              <KPI testID="cfo-kpi-expenses" label="Expenses" value={fmtUSD(dash.expenses?.total)} />
              <KPI testID="cfo-kpi-gross-profit" label="Gross Profit" value={fmtUSD(dash.gross_profit)} />
              <KPI testID="cfo-kpi-margin" label="Margin"
                    value={typeof dash.profit_margin_pct === "number" ? `${dash.profit_margin_pct.toFixed(1)}%` : "—"} />
              <KPI testID="cfo-kpi-cash-on-hand" label="Cash on Hand"
                    value={fmtUSD(dash.cash_on_hand?.value)}
                    mocked={dash.cash_on_hand?.mocked}
                    reason={dash.cash_on_hand?.reason} />
              <KPI testID="cfo-ar-0-30" label="AR 0-30" value={fmtUSD(dash.ar_aging?.["0_30"])} />
              <KPI testID="cfo-ar-31-60" label="AR 31-60" value={fmtUSD(dash.ar_aging?.["31_60"])} />
              <KPI testID="cfo-ar-61-90" label="AR 61-90" value={fmtUSD(dash.ar_aging?.["61_90"])} />
              <KPI testID="cfo-ar-90-plus" label="AR 90+" value={fmtUSD(dash.ar_aging?.["90_plus"])} />
            </View>

            <View style={s.apRow} testID="cfo-ap-aging">
              <Text style={s.apLabel}>AP aging unavailable</Text>
              <MockedBadge reason={dash.ap_aging?.reason} />
              <Text style={s.apReason} numberOfLines={2}>
                {dash.ap_aging?.reason || "AP bills collection not wired."}
              </Text>
            </View>

            <View style={s.section} testID="cfo-revenue-source">
              <Text style={s.sectionTitle}>Top revenue sources</Text>
              {revenueTop.length === 0 ? (
                <Text style={s.empty}>No revenue in this period.</Text>
              ) : revenueTop.map((r: any) => (
                <View key={r.source} style={s.row}>
                  <Text style={s.rowLabel}>{r.source}</Text>
                  <Text style={s.rowValue}>{fmtUSD(r.total)}</Text>
                </View>
              ))}
            </View>

            <View style={s.section} testID="cfo-expense-category">
              <Text style={s.sectionTitle}>Top expense categories</Text>
              {expenseTop.length === 0 ? (
                <Text style={s.empty}>Run auto-categorize on desktop to populate.</Text>
              ) : expenseTop.map((r: any) => (
                <View key={r.category} style={s.row}>
                  <Text style={s.rowLabel}>{r.category}</Text>
                  <Text style={s.rowValue}>{fmtUSD(r.total)}</Text>
                </View>
              ))}
            </View>

            <Text style={s.footNote}>
              Auto-Categorize is desktop-only. Deep-dive views:
            </Text>

            {/* Phase 36 · Feb-2026 — deep-dive navigation tiles. */}
            <View style={s.deepDives} testID="cfo-deep-dives">
              {[
                { label: "AP Aging",           to: "/cfo/ap-aging",       testID: "cfo-link-ap-aging" },
                { label: "Cash Forecast",      to: "/cfo/forecast",       testID: "cfo-link-forecast" },
                { label: "Anomalies",          to: "/cfo/anomalies",      testID: "cfo-link-anomalies" },
                { label: "Payroll (CFO)",      to: "/cfo/payroll",        testID: "cfo-link-payroll" },
                { label: "Price Increase",     to: "/cfo/price-increase", testID: "cfo-link-price-increase" },
                { label: "Vendor Bills",       to: "/finance/vendor-bills", testID: "cfo-link-vendor-bills" },
              ].map((d) => (
                <Pressable
                  key={d.to}
                  onPress={() => router.push(d.to as any)}
                  style={({ pressed }) => [s.deepDiveTile, pressed && { opacity: 0.7 }]}
                  testID={d.testID}
                >
                  <Text style={s.deepDiveLabel}>{d.label}</Text>
                  <Ionicons name="chevron-forward" size={16} color={colors.muted} />
                </Pressable>
              ))}
            </View>

            {/* Phase 34c — mobile Q&A + Scenario parity. */}
            <QnAPanel period={period} onUsageChange={load} />
            <ScenarioPanel
              topCustomers={dash?.top_customers || []}
              onUsageChange={load}
            />
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.lg },
  forbidden: { fontFamily: font.semibold, color: colors.muted, marginTop: spacing.md,
                textAlign: "center" },
  pills: {
    flexDirection: "row", gap: spacing.xs, marginBottom: spacing.md,
  },
  pill: {
    paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  pillOn: { borderColor: colors.brand, backgroundColor: colors.brand },
  pillText: { fontFamily: font.bold, fontSize: fontSize.xs, color: colors.onSurface },
  pillTextOn: { color: "#fff" },
  errBox: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#FEE2E2", borderColor: "#FCA5A5", borderWidth: 1,
    borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.md,
  },
  errText: { fontFamily: font.semibold, fontSize: fontSize.xs, color: "#991B1B" },
  grid: {
    flexDirection: "row", flexWrap: "wrap", gap: spacing.sm,
  },
  kpi: {
    width: "48%", padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  kpiHeader: { flexDirection: "row", alignItems: "center", gap: 4 },
  kpiLabel: {
    fontFamily: font.bold, fontSize: fontSize.xs, color: colors.muted,
    textTransform: "uppercase", letterSpacing: 0.6,
  },
  kpiValue: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    marginTop: 4,
  },
  kpiReason: {
    fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 2,
  },
  mockedBadge: {
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
    backgroundColor: "#FEF3C7",
  },
  mockedText: {
    fontFamily: font.bold, fontSize: 9, color: "#92400E",
    textTransform: "uppercase", letterSpacing: 0.5,
  },
  apRow: {
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: "#FEF3C7", borderColor: "#B45309", borderWidth: 1,
    marginTop: spacing.md,
  },
  apLabel: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#B45309" },
  apReason: { fontFamily: font.regular, fontSize: fontSize.xs, color: "#B45309", marginTop: 4 },
  section: {
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    marginTop: spacing.md,
  },
  sectionTitle: {
    fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  empty: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  row: {
    flexDirection: "row", justifyContent: "space-between",
    paddingVertical: 6, borderTopWidth: 1, borderTopColor: colors.border,
  },
  rowLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface,
                textTransform: "capitalize" },
  rowValue: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  footNote: {
    fontFamily: font.regular, fontSize: 11, color: colors.muted,
    marginTop: spacing.lg, textAlign: "center", fontStyle: "italic",
  },
  deepDives: {
    marginTop: spacing.md, gap: spacing.xs,
    padding: spacing.md, borderRadius: radius.md,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  deepDiveTile: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    paddingVertical: spacing.sm, paddingHorizontal: spacing.xs,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  deepDiveLabel: {
    fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface,
  },
});
