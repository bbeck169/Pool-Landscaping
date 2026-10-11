/**
 * Phase 39B · mobile port of web `admin/CrewProductivityTile.jsx`.
 * GET /admin/crew-productivity?range=this_week|last_week|this_month.
 * No auto-poll (report, refetch on range change / refresh). Web
 * `<select>` → range tabs; crews with zero jobs AND zero revenue are
 * hidden; totals row from server `totals`. "Schedule" opens the mobile
 * calendar. Parent gate: super_admin / admin / owner.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export const CREW_RANGES = [
  { value: "this_week", label: "This Week" },
  { value: "last_week", label: "Last Week" },
  { value: "this_month", label: "This Month" },
];
const LABEL: Record<string, string> = Object.fromEntries(CREW_RANGES.map((r) => [r.value, r.label]));
const usd = (n: any) => `$${(Number(n) || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function CrewRow({ c, onSchedule }: { c: any; onSchedule: () => void }) {
  return (
    <View style={s.tr} testID={`crew-productivity-row-${c.crew_id}`}>
      <View style={[s.crewCell, s.tdCrew]}>
        <View style={[s.dot, { backgroundColor: c.color || "#0284C7" }]} />
        <Text style={s.crewName} numberOfLines={1}>{c.crew_name}</Text>
      </View>
      <View style={[s.td, s.members]}>
        <Ionicons name="people-outline" size={11} color={colors.muted} />
        <Text style={s.mutedNum}>{c.member_count ?? 0}</Text>
      </View>
      <Text style={[s.td, s.num]} testID={`crew-productivity-row-${c.crew_id}-jobs`}>{c.jobs_completed ?? 0}</Text>
      <Text style={[s.tdRev, s.num, s.bold]} testID={`crew-productivity-row-${c.crew_id}-revenue`}>{usd(c.revenue_subtotal)}</Text>
      <Pressable onPress={onSchedule} hitSlop={8} style={s.tdLink} testID={`crew-productivity-row-${c.crew_id}-schedule`} accessibilityLabel={`Schedule for ${c.crew_name}`}>
        <Ionicons name="calendar-outline" size={15} color={colors.brand} />
      </Pressable>
    </View>
  );
}

export default function CrewProductivityTile() {
  const router = useRouter();
  const [range, setRange] = useState("this_week");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async (r: string) => {
    setLoading(true); setErr("");
    try { setData((await api.get(`/admin/crew-productivity?range=${encodeURIComponent(r)}`)) || null); }
    catch (e: any) { setErr(e?.message || "Failed to load"); setData(null); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(range); }, [range, load]);

  const crews = useMemo(
    () => (Array.isArray(data?.crews) ? data.crews : []).filter((c: any) => (c.jobs_completed || 0) > 0 || (c.revenue_subtotal || 0) > 0),
    [data],
  );

  return (
    <View style={s.tile} testID="crew-productivity-tile">
      <View style={s.head}>
        <View style={s.titleRow}>
          <Ionicons name="trending-up" size={16} color={colors.brand} />
          <Text style={s.title} testID="crew-productivity-tile-title">Crew Productivity ({LABEL[range]})</Text>
        </View>
        <Pressable onPress={() => load(range)} hitSlop={10} style={s.iconBtn} testID="crew-productivity-tile-refresh" accessibilityLabel="Refresh">
          <Ionicons name="refresh" size={14} color={colors.muted} style={{ opacity: loading ? 0.4 : 1 }} />
        </Pressable>
      </View>
      <View style={s.tabs} testID="crew-productivity-tile-range">
        {CREW_RANGES.map((o) => (
          <Pressable key={o.value} onPress={() => setRange(o.value)} style={[s.tab, range === o.value && s.tabOn]} testID={`crew-productivity-range-option-${o.value}`}>
            <Text style={[s.tabText, range === o.value && s.tabTextOn]}>{o.label}</Text>
          </Pressable>
        ))}
      </View>
      {err ? <View style={s.errBox} testID="crew-productivity-tile-error"><Text style={s.errText}>{err}</Text></View> : null}
      {loading && !data ? (
        <View testID="crew-productivity-tile-skeleton">{[0, 1, 2].map((i) => <View key={i} style={s.skel} />)}</View>
      ) : null}
      {!loading && !err && crews.length === 0 ? (
        <View style={s.empty} testID="crew-productivity-tile-empty">
          <Text style={s.emptyText}>No completed jobs for any crew {LABEL[range].toLowerCase()}.</Text>
        </View>
      ) : null}
      {crews.length > 0 ? (
        <View testID="crew-productivity-tile-table">
          <View style={s.tr}>
            <Text style={[s.th, s.tdCrew]}>Crew</Text>
            <Text style={[s.th, s.td, s.num]}>Members</Text>
            <Text style={[s.th, s.td, s.num]}>Jobs</Text>
            <Text style={[s.th, s.tdRev, s.num]}>Revenue</Text>
            <View style={s.tdLink} />
          </View>
          <View testID="crew-productivity-tile-tbody">
            {crews.map((c: any) => (
              <CrewRow key={c.crew_id} c={c} onSchedule={() => router.push({ pathname: "/(app)/schedule/calendar", params: { crew: c.crew_id } } as any)} />
            ))}
          </View>
          <View style={s.tr} testID="crew-productivity-tile-totals">
            <Text style={[s.th, s.tdCrew]}>Totals</Text>
            <View style={s.td} />
            <Text style={[s.td, s.num, s.bold]} testID="crew-productivity-tile-totals-jobs">{data?.totals?.jobs_completed || 0}</Text>
            <Text style={[s.tdRev, s.num, s.bold]} testID="crew-productivity-tile-totals-revenue">{usd(data?.totals?.revenue_subtotal)}</Text>
            <View style={s.tdLink} />
          </View>
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  tile: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.lg },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 6, flexShrink: 1 },
  title: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface, flexShrink: 1 },
  iconBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
  tabs: { flexDirection: "row", gap: 4, padding: 3, borderRadius: radius.md, backgroundColor: colors.surfaceSecondary, marginVertical: spacing.sm },
  tab: { flex: 1, minHeight: 36, alignItems: "center", justifyContent: "center", borderRadius: radius.sm },
  tabOn: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  tabText: { fontFamily: font.semibold, fontSize: 12, color: colors.onSurfaceSecondary },
  tabTextOn: { color: colors.brand, fontFamily: font.bold },
  errBox: { padding: spacing.md, borderRadius: radius.md, backgroundColor: "#FEE2E2", borderWidth: 1, borderColor: "#FCA5A5", marginBottom: spacing.sm },
  errText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.error },
  skel: { height: 36, borderRadius: radius.md, backgroundColor: colors.surfaceSecondary, marginBottom: spacing.sm },
  empty: { padding: spacing.xl, borderRadius: radius.md, borderWidth: 1, borderStyle: "dashed", borderColor: colors.border, backgroundColor: colors.surfaceSecondary },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
  tr: { flexDirection: "row", alignItems: "center", minHeight: 40, borderTopWidth: 1, borderTopColor: colors.border },
  th: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 0.6, textTransform: "uppercase" },
  tdCrew: { flex: 1, minWidth: 0 },
  crewCell: { flexDirection: "row", alignItems: "center", gap: 6 },
  td: { width: 56 },
  tdRev: { width: 92 },
  tdLink: { width: 32, alignItems: "flex-end", justifyContent: "center", minHeight: 36 },
  members: { flexDirection: "row", alignItems: "center", justifyContent: "flex-end", gap: 3 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  crewName: { flexShrink: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  num: { textAlign: "right", fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  mutedNum: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  bold: { fontFamily: font.bold },
});
