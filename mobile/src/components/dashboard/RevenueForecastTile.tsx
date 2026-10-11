/**
 * RevenueForecastTile — Phase J2 / H10 parity.
 *
 * Inline dashboard tile with 5 quick-view tabs:
 * Today · Tomorrow · This Week · This Month · Next Month.
 * Hits GET /api/admin/dashboard/revenue-forecast?start=...&end=...
 * Mirrors web RevenueForecastTile.jsx.
 *
 * Phase 39A · the headline block (combined total "projected in range" +
 * Booked / Recurring chips + caption) is driven by the dashboard's shared
 * Revenue Insights ``range`` prop, as on web. The quick-view tabs stay
 * tile-local and do NOT propagate to the shared filter.
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

/* ── Headline (shared range) ────────────────────────────────── */
function plural(n: number, word: string) { return `${n} ${word}${n === 1 ? "" : "s"}`; }

function Chip({ icon, label, value, color, testID }: { icon: any; label: string; value: string; color: string; testID: string }) {
  return (
    <View style={[s.chip, { backgroundColor: color + "12", borderColor: color + "30" }]} testID={testID}>
      <View style={s.chipHead}>
        <Ionicons name={icon} size={11} color={color} />
        <Text style={[s.chipLabel, { color }]}>{label}</Text>
      </View>
      <Text style={s.chipValue}>{value}</Text>
    </View>
  );
}

function Headline({ range }: { range: { start: string; end: string } }) {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let alive = true;
    setData(null); setErr("");
    api.get(`/admin/dashboard/revenue-forecast?start=${range.start}&end=${range.end}`)
      .then((r: any) => { if (alive) setData(r || {}); })
      .catch((e: any) => { if (alive) setErr(e?.message || "Failed to load."); });
    return () => { alive = false; };
  }, [range.start, range.end]);
  if (err) return <Text style={s.heroErr} testID="revenue-forecast-error">{err}</Text>;
  if (data === null) {
    return <View style={s.heroLoading} testID="revenue-forecast-loading"><ActivityIndicator color={colors.brand} /></View>;
  }
  const booked = data.booked || {}, rec = data.recurring || {};
  return (
    <View style={{ gap: spacing.sm }} testID="revenue-forecast-headline">
      <View style={s.heroRow}>
        <Text style={s.heroValue} testID="revenue-forecast-combined">{money(data.combined_total ?? 0)}</Text>
        <Text style={s.heroSub}>projected in range</Text>
      </View>
      <View style={s.chipRow}>
        <Chip icon="calendar-outline" label="Booked" value={money(booked.amount ?? 0)} color="#0891B2" testID="revenue-forecast-booked" />
        <Chip icon="refresh-outline" label="Recurring" value={money(rec.amount ?? 0)} color="#7C3AED" testID="revenue-forecast-recurring" />
      </View>
      <Text style={s.hint} testID="revenue-forecast-caption">
        {`Based on ${plural(booked.job_count ?? 0, "booked job")} + `}
        {(rec.recurring_job_count ?? 0) > 0 ? `${plural(rec.recurring_job_count, "recurring job")} + ` : ""}
        {`${plural(rec.subscription_count ?? 0, "active subscription")} across ${plural(rec.cycle_count ?? 0, "billing cycle")}.`}
      </Text>
    </View>
  );
}

/* ── Component ──────────────────────────────────────────────── */
export default function RevenueForecastTile({ range }: { range?: { start: string; end: string } | null } = {}) {
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

      {range?.start && range?.end ? <Headline range={range} /> : null}

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
  heroRow: { flexDirection: "row", alignItems: "baseline", flexWrap: "wrap", gap: spacing.sm },
  heroValue: { fontFamily: font.bold, fontSize: 28, color: colors.onSurface },
  heroSub: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  heroErr: { padding: spacing.sm, borderRadius: radius.md, backgroundColor: "#FEE2E2", color: "#7F1D1D", fontFamily: font.medium, fontSize: fontSize.sm },
  heroLoading: { height: 96, alignItems: "center", justifyContent: "center", borderRadius: radius.md, backgroundColor: colors.surfaceSecondary },
  chipRow: { flexDirection: "row", gap: spacing.sm },
  chip: { flex: 1, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.sm, paddingVertical: 6 },
  chipHead: { flexDirection: "row", alignItems: "center", gap: 4 },
  chipLabel: { fontFamily: font.bold, fontSize: 10, textTransform: "uppercase", letterSpacing: 1 },
  chipValue: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
});
