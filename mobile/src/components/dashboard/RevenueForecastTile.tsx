/**
 * RevenueForecastTile — Phase J2 / H10 parity.
 *
 * Inline dashboard tile with 5 quick-view tabs:
 * Today · Tomorrow · This Week · This Month · Next Month.
 * Hits GET /api/admin/dashboard/revenue-forecast?start=...&end=...
 * Mirrors web RevenueForecastTile.jsx.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";

/* ── Date-range helpers ─────────────────────────────────────── */
const isoDay = (d: Date) => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
};
const startOfDay = (d: Date) => {
  const x = new Date(d); x.setHours(0, 0, 0, 0); return x;
};
const todayRange = () => { const s = startOfDay(new Date()); return { start: isoDay(s), end: isoDay(s) }; };
const tomorrowRange = () => { const s = startOfDay(new Date()); s.setDate(s.getDate() + 1); return { start: isoDay(s), end: isoDay(s) }; };
const thisWeekRange = () => {
  const now = startOfDay(new Date()); const dow = now.getDay();
  const sun = new Date(now); sun.setDate(now.getDate() - dow);
  const sat = new Date(sun); sat.setDate(sun.getDate() + 6);
  return { start: isoDay(sun), end: isoDay(sat) };
};
const thisMonthRange = () => {
  const now = startOfDay(new Date());
  return { start: isoDay(new Date(now.getFullYear(), now.getMonth(), 1)),
           end: isoDay(new Date(now.getFullYear(), now.getMonth() + 1, 0)) };
};
const nextMonthRange = () => {
  const now = startOfDay(new Date());
  return { start: isoDay(new Date(now.getFullYear(), now.getMonth() + 1, 1)),
           end: isoDay(new Date(now.getFullYear(), now.getMonth() + 2, 0)) };
};

type TabDef = { key: string; label: string; build: () => { start: string; end: string } };
const TABS: TabDef[] = [
  { key: "today",      label: "Today",      build: todayRange },
  { key: "tomorrow",   label: "Tomorrow",   build: tomorrowRange },
  { key: "week",       label: "This Week",  build: thisWeekRange },
  { key: "this_month", label: "This Month", build: thisMonthRange },
  { key: "next_month", label: "Next Month", build: nextMonthRange },
];

/* ── Component ──────────────────────────────────────────────── */
export default function RevenueForecastTile() {
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [tabData, setTabData] = useState<any>(null);
  const [tabBusy, setTabBusy] = useState(false);
  const [tabErr, setTabErr] = useState("");

  const activeRange = useMemo(() => {
    if (!activeTab) return null;
    const t = TABS.find((x) => x.key === activeTab);
    return t ? t.build() : null;
  }, [activeTab]);

  useEffect(() => {
    if (!activeRange) { setTabData(null); setTabErr(""); return; }
    setTabBusy(true); setTabErr(""); setTabData(null);
    api.get(`/admin/dashboard/revenue-forecast?start=${activeRange.start}&end=${activeRange.end}`)
      .then((r: any) => setTabData(r))
      .catch((e: any) => setTabErr(e?.message || "Failed"))
      .finally(() => setTabBusy(false));
  }, [activeRange?.start, activeRange?.end]); // eslint-disable-line react-hooks/exhaustive-deps

  const onTabPress = (key: string) =>
    setActiveTab((cur) => (cur === key ? null : key));

  return (
    <View style={s.tile} testID="revenue-forecast-tile">
      <View style={s.headerRow}>
        <Ionicons name="trending-up-outline" size={16} color={colors.muted} />
        <Text style={s.headerLabel}>Revenue Forecast</Text>
      </View>

      {/* Quick-view tabs */}
      <View style={s.tabRow} testID="revenue-forecast-quick-view">
        {TABS.map((t) => {
          const active = activeTab === t.key;
          return (
            <Pressable
              key={t.key}
              onPress={() => onTabPress(t.key)}
              style={[s.tab, active && s.tabActive]}
              testID={`revenue-forecast-tab-${t.key}`}
            >
              <Text style={[s.tabText, active && s.tabTextActive]}>{t.label}</Text>
            </Pressable>
          );
        })}
      </View>

      {/* Result */}
      {activeTab ? (
        <View style={s.resultRow} testID="revenue-forecast-tab-stat">
          {tabBusy ? (
            <>
              <ActivityIndicator size="small" color={colors.brand} testID="revenue-forecast-tab-loading" />
              <Text style={s.resultMuted}>Loading…</Text>
            </>
          ) : tabErr ? (
            <Text style={s.resultErr} testID="revenue-forecast-tab-error">Failed</Text>
          ) : tabData ? (
            <>
              <Text style={s.resultLabel} testID="revenue-forecast-tab-value">
                {TABS.find((x) => x.key === activeTab)?.label}:{" "}
              </Text>
              <Text style={s.resultValue}>{money(tabData.combined_total)}</Text>
              {tabData.booked ? (
                <Text style={s.resultCaption}>
                  {" "}({tabData.booked.job_count} job{tabData.booked.job_count === 1 ? "" : "s"} + {tabData.recurring?.subscription_count ?? 0} subs)
                </Text>
              ) : null}
            </>
          ) : null}
        </View>
      ) : (
        <Text style={s.hint}>Tap a period to preview projected revenue</Text>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  tile: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  headerLabel: {
    fontFamily: font.bold,
    fontSize: 10,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  tabRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  tab: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  tabActive: {
    backgroundColor: "#0891B2",
    borderColor: "#0891B2",
  },
  tabText: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: colors.muted,
  },
  tabTextActive: {
    color: "#fff",
  },
  resultRow: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 4,
    paddingTop: 4,
  },
  resultLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  resultValue: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: "#0891B2",
  },
  resultCaption: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
  },
  resultMuted: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  resultErr: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#7F1D1D",
  },
  hint: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
});
