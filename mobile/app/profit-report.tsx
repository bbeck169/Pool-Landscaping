/**
 * PB1 · Profit Report — Admin-only screen.
 *
 * Mirrors web ProfitReportPage.jsx:
 *   - Range picker (This Month / Last Month / QTD / YTD / Custom)
 *   - Dimension toggle (Service Category ↔ Income Category)
 *   - 5 summary tiles: Revenue, COGS, Labor, Gross Profit, Margin %
 *   - Sortable breakdown list
 *   - Export CSV → download + share
 *
 * STRICTLY internal — never linked from customer-facing surfaces.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  ActivityIndicator, Alert, Platform, TextInput,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as FileSystemLegacy from "expo-file-system/legacy";
import * as SharingModule from "expo-sharing";

import { api, api_base, getAuthToken } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useLocalSearchParams } from "expo-router";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import EbitPanel from "@/src/components/admin/EbitPanel";

const RANGE_OPTIONS = [
  { key: "this_month", label: "This Month" },
  { key: "last_month", label: "Last Month" },
  { key: "qtd", label: "QTD" },
  { key: "ytd", label: "YTD" },
  { key: "custom", label: "Custom" },
] as const;

const fmtPct = (n: number) => `${Number(n || 0).toFixed(1)}%`;

const ADMIN_ROLES = ["admin", "super_admin", "manager"];

export default function ProfitReport() {
  const { user } = useAuth();
  const isAdmin = ADMIN_ROLES.includes(user?.role || "");

  // Phase 53f · Feb-2026 — mobile EBIT-tile drill-down entry.
  const _params = useLocalSearchParams<{ from?: string; to?: string }>();
  const _dateRe = /^\d{4}-\d{2}-\d{2}$/;
  const _urlFrom = typeof _params?.from === "string" && _dateRe.test(_params.from) ? _params.from : "";
  const _urlTo = typeof _params?.to === "string" && _dateRe.test(_params.to) ? _params.to : "";
  const _hasDeepLink = Boolean(_urlFrom && _urlTo);

  const [rangeKey, setRangeKey] = useState(_hasDeepLink ? "custom" : "this_month");
  const [customFrom, setCustomFrom] = useState(_urlFrom);
  const [customTo, setCustomTo] = useState(_urlTo);
  const [dimension, setDimension] = useState("service_category");
  const [sortCol, setSortCol] = useState("revenue");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");

  const buildQuery = () => {
    const p = new URLSearchParams();
    p.set("dimension", dimension);
    p.set("range", rangeKey);
    if (rangeKey === "custom") {
      if (!customFrom || !customTo) return null;
      p.set("from", customFrom);
      p.set("to", customTo);
    }
    return p.toString();
  };

  const load = async () => {
    const qs = buildQuery();
    if (!qs) return;
    setBusy(true);
    setErr("");
    try {
      const res = await api.get(`/reports/profit?${qs}`);
      setData(res);
    } catch (e: any) {
      setErr(e?.message || "Failed to load profit report.");
      setData(null);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!isAdmin) return;
    if (rangeKey === "custom" && (!customFrom || !customTo)) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin, dimension, rangeKey, customFrom, customTo]);

  const sorted = useMemo(() => {
    const rows = (data?.breakdown || []).slice();
    rows.sort((a: any, b: any) => {
      const av = a[sortCol];
      const bv = b[sortCol];
      const an = typeof av === "number" ? av : String(av || "").toLowerCase();
      const bn = typeof bv === "number" ? bv : String(bv || "").toLowerCase();
      if (an < bn) return sortDir === "asc" ? -1 : 1;
      if (an > bn) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return rows;
  }, [data, sortCol, sortDir]);

  const bump = (col: string) => {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
  };

  const exportCsv = async () => {
    const qs = buildQuery();
    if (!qs) return;
    try {
      const token = await getAuthToken();
      const url = `${api_base()}/reports/profit.csv?${qs}`;
      if (Platform.OS === "web") {
        const res = await fetch(url, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        const blob = await res.blob();
        const objUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = objUrl;
        a.download = `profit-${dimension}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(objUrl), 1500);
      } else {
        const localUri = `${FileSystemLegacy.cacheDirectory}profit-${dimension}.csv`;
        const dl = await FileSystemLegacy.downloadAsync(url, localUri, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (await SharingModule.isAvailableAsync()) {
          await SharingModule.shareAsync(dl.uri);
        } else {
          Alert.alert("Downloaded", "CSV saved to cache.");
        }
      }
    } catch (e: any) {
      Alert.alert("Export failed", e?.message || "");
    }
  };

  // ── Non-admin guard ──
  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <Header title="Profit Report" back />
        <View style={styles.forbidden} testID="profit-report-forbidden">
          <Ionicons name="lock-closed" size={24} color="#7F1D1D" />
          <Text style={styles.forbiddenText}>
            You do not have permission to view this report. Contact your administrator if you need access.
          </Text>
        </View>
      </View>
    );
  }

  const totals = data?.totals || {};

  return (
    <View style={styles.root}>
      <Header title="Profit Report" back />
      <ScrollView contentContainerStyle={styles.scroll} testID="profit-report-page">
        {/* Internal label */}
        <View style={styles.internalBadge}>
          <Ionicons name="shield-checkmark" size={12} color="#92400E" />
          <Text style={styles.internalText}>Internal — not shown to customers</Text>
        </View>

        {/* ── Range pills ── */}
        <View style={styles.filterCard} testID="profit-report-filters">
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <View style={styles.pillRow}>
              {RANGE_OPTIONS.map((r) => (
                <Pressable
                  key={r.key}
                  onPress={() => setRangeKey(r.key)}
                  style={[styles.pill, rangeKey === r.key && styles.pillActive]}
                  testID={`profit-report-range-${r.key}`}
                >
                  <Text
                    style={[
                      styles.pillText,
                      rangeKey === r.key && styles.pillTextActive,
                    ]}
                  >
                    {r.label}
                  </Text>
                </Pressable>
              ))}
            </View>
          </ScrollView>

          {/* Custom date inputs */}
          {rangeKey === "custom" && (
            <View style={styles.customRow} testID="profit-report-custom-picker">
              <View style={{ flex: 1 }}>
                <Text style={styles.dateLabel}>FROM</Text>
                <TextInput
                  style={styles.dateInput}
                  placeholder="YYYY-MM-DD"
                  placeholderTextColor={colors.muted}
                  value={customFrom}
                  onChangeText={setCustomFrom}
                  testID="profit-report-custom-from"
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.dateLabel}>TO</Text>
                <TextInput
                  style={styles.dateInput}
                  placeholder="YYYY-MM-DD"
                  placeholderTextColor={colors.muted}
                  value={customTo}
                  onChangeText={setCustomTo}
                  testID="profit-report-custom-to"
                />
              </View>
            </View>
          )}

          {/* Dimension toggle + export */}
          <View style={styles.dimRow}>
            <Text style={styles.dimLabel}>Group by:</Text>
            <View style={styles.segmented} testID="profit-report-dimension-toggle">
              <Pressable
                style={[
                  styles.segBtn,
                  dimension === "service_category" && styles.segBtnActive,
                ]}
                onPress={() => setDimension("service_category")}
                testID="profit-report-dim-service"
              >
                <Text
                  style={[
                    styles.segText,
                    dimension === "service_category" && styles.segTextActive,
                  ]}
                >
                  Service
                </Text>
              </Pressable>
              <Pressable
                style={[
                  styles.segBtn,
                  dimension === "income_category" && styles.segBtnActive,
                ]}
                onPress={() => setDimension("income_category")}
                testID="profit-report-dim-income"
              >
                <Text
                  style={[
                    styles.segText,
                    dimension === "income_category" && styles.segTextActive,
                  ]}
                >
                  Income
                </Text>
              </Pressable>
            </View>
            <Pressable
              style={[styles.csvBtn, (!data || busy) && { opacity: 0.5 }]}
              onPress={exportCsv}
              disabled={!data || busy}
              testID="profit-report-export-csv"
            >
              <Ionicons name="download-outline" size={14} color="#fff" />
              <Text style={styles.csvText}>CSV</Text>
            </Pressable>
          </View>
        </View>

        {/* ── Body ── */}
        {err ? (
          <View style={styles.errBox} testID="profit-report-error">
            <Text style={styles.errText}>{err}</Text>
          </View>
        ) : busy && !data ? (
          <View style={styles.loadingWrap} testID="profit-report-loading">
            <ActivityIndicator size="large" color={colors.brand} />
          </View>
        ) : data ? (
          <>
            {/* Summary tiles - 2-col grid */}
            <View style={styles.tilesGrid}>
              <SummaryTile
                icon="cash-outline"
                label="Revenue"
                value={money(totals.revenue || 0)}
                hint={`${totals.line_count || 0} lines`}
                color="#0891B2"
                testID="profit-report-tile-revenue"
              />
              <SummaryTile
                icon="cube-outline"
                label="COGS"
                value={money(totals.cogs || 0)}
                color="#B45309"
                testID="profit-report-tile-cogs"
              />
              <SummaryTile
                icon="construct-outline"
                label="Labor"
                value={money(totals.labor || 0)}
                color="#7C3AED"
                testID="profit-report-tile-labor"
              />
              <SummaryTile
                icon="trending-up-outline"
                label="Gross Profit"
                value={money(totals.gross_profit || 0)}
                color="#166534"
                testID="profit-report-tile-profit"
              />
              <SummaryTile
                icon="pie-chart-outline"
                label="Margin"
                value={fmtPct(totals.margin_pct || 0)}
                color="#065F46"
                testID="profit-report-tile-margin"
              />
            </View>

            {/* Breakdown list */}
            <View style={styles.breakdownCard} testID="profit-report-breakdown">
              {/* Column headers */}
              <View style={styles.bkHeaderRow}>
                <Pressable style={{ flex: 2 }} onPress={() => bump("category_name")}>
                  <Text style={styles.bkHeaderText}>
                    Category{sortCol === "category_name" ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                  </Text>
                </Pressable>
                {[
                  { k: "revenue", l: "Rev" },
                  { k: "cogs", l: "COGS" },
                  { k: "labor", l: "Labor" },
                  { k: "profit", l: "Profit" },
                  { k: "margin_pct", l: "Mrg%" },
                ].map((c) => (
                  <Pressable
                    key={c.k}
                    style={{ flex: 1, alignItems: "flex-end" }}
                    onPress={() => bump(c.k)}
                  >
                    <Text style={styles.bkHeaderText}>
                      {c.l}{sortCol === c.k ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                    </Text>
                  </Pressable>
                ))}
              </View>
              {sorted.length === 0 ? (
                <Text style={styles.emptyText} testID="profit-report-empty">
                  No invoices in the selected range.
                </Text>
              ) : (
                sorted.map((row: any) => (
                  <View
                    key={row.category_id || row.category_name}
                    style={styles.bkRow}
                    testID={`profit-report-row-${row.category_id}`}
                  >
                    <Text style={[styles.bkCell, { flex: 2, fontFamily: font.semibold }]} numberOfLines={1}>
                      {row.category_name}
                    </Text>
                    <Text style={[styles.bkCell, styles.bkRight]}>{money(row.revenue)}</Text>
                    <Text style={[styles.bkCell, styles.bkRight, { color: "#B45309" }]}>
                      {money(row.cogs)}
                    </Text>
                    <Text style={[styles.bkCell, styles.bkRight, { color: "#7C3AED" }]}>
                      {money(row.labor)}
                    </Text>
                    <Text
                      style={[
                        styles.bkCell,
                        styles.bkRight,
                        { fontFamily: font.semibold, color: row.profit >= 0 ? "#166534" : "#991B1B" },
                      ]}
                    >
                      {money(row.profit)}
                    </Text>
                    <Text style={[styles.bkCell, styles.bkRight, { color: colors.muted }]}>
                      {fmtPct(row.margin_pct)}
                    </Text>
                  </View>
                ))
              )}
            </View>
          </>
        ) : null}
        {/* ── Phase 53c · Editable EBIT panel (parity with 53b web) ── */}
        <EbitPanel />
      </ScrollView>
    </View>
  );
}

// ── SummaryTile ──
function SummaryTile({
  icon,
  label,
  value,
  hint,
  color,
  testID,
}: {
  icon: string;
  label: string;
  value: string;
  hint?: string;
  color: string;
  testID: string;
}) {
  return (
    <View
      style={[styles.tile, { borderColor: `${color}40`, backgroundColor: `${color}10` }]}
      testID={testID}
    >
      <View style={styles.tileLabelRow}>
        <Ionicons name={icon as any} size={12} color={color} />
        <Text style={[styles.tileLabel, { color }]}>{label}</Text>
      </View>
      <Text style={styles.tileValue}>{value}</Text>
      {hint ? <Text style={styles.tileHint}>{hint}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  scroll: { padding: spacing.lg, paddingBottom: spacing["3xl"] },
  forbidden: {
    margin: spacing.lg,
    padding: spacing.lg,
    borderRadius: radius.lg,
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FCA5A5",
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  forbiddenText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#7F1D1D", flex: 1 },
  internalBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#FEF3C7",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.pill,
    alignSelf: "flex-start",
    marginBottom: spacing.md,
  },
  internalText: { fontFamily: font.bold, fontSize: 11, color: "#92400E" },
  filterCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.lg,
    gap: spacing.md,
  },
  pillRow: { flexDirection: "row", gap: 6 },
  pill: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  pillActive: { backgroundColor: "#0891B2", borderColor: "#0891B2" },
  pillText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted },
  pillTextActive: { color: "#fff" },
  customRow: { flexDirection: "row", gap: spacing.md },
  dateLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 1, marginBottom: 4 },
  dateInput: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 40,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  dimRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.md,
  },
  dimLabel: { fontFamily: font.bold, fontSize: 11, color: colors.muted, textTransform: "uppercase" },
  segmented: {
    flexDirection: "row",
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  segBtn: { paddingHorizontal: 12, paddingVertical: 6, backgroundColor: colors.surface },
  segBtnActive: { backgroundColor: "#0891B2" },
  segText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted },
  segTextActive: { color: "#fff" },
  csvBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: radius.md,
    backgroundColor: "#0891B2",
    marginLeft: "auto",
  },
  csvText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  loadingWrap: { padding: 40, alignItems: "center" },
  errBox: {
    padding: spacing.md,
    borderRadius: radius.lg,
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FCA5A5",
  },
  errText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#7F1D1D" },
  // Tiles
  tilesGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  tile: {
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    minWidth: "47%",
    flexGrow: 1,
    flexBasis: "47%",
  },
  tileLabelRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  tileLabel: { fontFamily: font.bold, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 },
  tileValue: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onSurface, marginTop: 4 },
  tileHint: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  // Breakdown
  breakdownCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  bkHeaderRow: {
    flexDirection: "row",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  bkHeaderText: { fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase" },
  bkRow: {
    flexDirection: "row",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  bkCell: { flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  bkRight: { textAlign: "right" },
  emptyText: {
    textAlign: "center",
    padding: spacing.xl,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
});
