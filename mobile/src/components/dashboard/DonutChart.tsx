/**
 * Phase 39A · shared donut for the Revenue Insights tiles (web parity:
 * recharts PieChart innerRadius 55 / outerRadius 85, paddingAngle 1,
 * center "Total" label). Drawn with react-native-svg circle segments —
 * no new dependency. Hover tooltips have no touch equivalent, so tapping
 * a legend row highlights its segment and swaps the center label to that
 * item's amount · % · line-item count; tap again to clear.
 *
 * Also exports ``useRangedFetch`` (stale-response-safe range refetch) and
 * ``pct`` shared by RevenueByCategoryTile + IncomeByServiceCategoryTile.
 */
import React, { useEffect, useState } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import Svg, { Circle, G } from "react-native-svg";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";

export type DonutItem = { key: string; label: string; amount: number; color: string; count?: number };

export function pct(part: number, total: number): string {
  if (!total) return "0%";
  return `${((part / total) * 100).toFixed(1)}%`;
}

/** Fetch ``path?start&end`` whenever the range changes; ignores stale responses. */
export function useRangedFetch(path: string, range?: { start: string; end: string } | null) {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!range?.start || !range?.end) return;
    let alive = true;
    setData(null); setErr("");
    api.get(`${path}?start=${range.start}&end=${range.end}`)
      .then((r: any) => { if (alive) setData(r || { items: [], total: 0 }); })
      .catch((e: any) => { if (alive) setErr(e?.message || "Failed to load."); });
    return () => { alive = false; };
  }, [path, range?.start, range?.end]);
  return { data, err };
}

const SIZE = 170, OUTER = 85 * (SIZE / 170), INNER = 55 * (SIZE / 170);
const R = (OUTER + INNER) / 2, STROKE = OUTER - INNER, C = 2 * Math.PI * R;

function Ring({ items, total, selected }: { items: DonutItem[]; total: number; selected: string | null }) {
  const gap = items.length > 1 ? (C * 1) / 360 : 0; // paddingAngle 1°
  let offset = 0;
  return (
    <Svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
      <G rotation={-90} origin={`${SIZE / 2}, ${SIZE / 2}`}>
        {items.map((it) => {
          const len = total > 0 ? (Math.max(0, it.amount) / total) * C : 0;
          const seg = Math.max(0, len - gap);
          const el = (
            <Circle key={it.key} cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" stroke={it.color} strokeWidth={STROKE}
              strokeDasharray={`${seg} ${C - seg}`} strokeDashoffset={-offset}
              opacity={selected && selected !== it.key ? 0.3 : 1} />
          );
          offset += len;
          return el;
        })}
      </G>
    </Svg>
  );
}

type Props = { items: DonutItem[]; total: number; prefix: string };

export default function DonutChart({ items, total, prefix }: Props) {
  const [selected, setSelected] = useState<string | null>(null);
  const sel = items.find((i) => i.key === selected) || null;
  return (
    <View style={s.wrap}>
      <View style={s.chart} testID={`${prefix}-chart`}>
        <Ring items={items} total={total} selected={selected} />
        <View style={s.center} pointerEvents="none" testID={`${prefix}-center`}>
          <Text style={[s.centerLabel, sel && { color: sel.color }]} numberOfLines={1}>{sel ? sel.label : "Total"}</Text>
          <Text style={s.centerValue} numberOfLines={1} adjustsFontSizeToFit>{money(sel ? sel.amount : total)}</Text>
          {sel ? <Text style={s.centerSub}>{`${pct(sel.amount, total)} · ${sel.count ?? 0} line item(s)`}</Text> : null}
        </View>
      </View>
      <View style={s.legend} testID={`${prefix}-legend`}>
        {items.map((it) => {
          const on = selected === it.key;
          return (
            <Pressable key={it.key} onPress={() => setSelected(on ? null : it.key)} style={[s.row, on && s.rowOn]}
              testID={`${prefix}-legend-${it.label.replace(/\s+/g, "-")}`} accessibilityRole="button" accessibilityState={{ selected: on }}>
              <View style={[s.swatch, { backgroundColor: it.color }]} />
              <Text style={s.rowLabel} numberOfLines={1}>{it.label}</Text>
              <Text style={s.rowValue}>{`${money(it.amount)} · ${pct(it.amount, total)}`}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { alignItems: "center", gap: spacing.md },
  chart: { width: SIZE, height: SIZE, alignItems: "center", justifyContent: "center" },
  center: { position: "absolute", alignItems: "center", width: INNER * 2 - 8 },
  centerLabel: { fontFamily: font.medium, fontSize: 11, color: colors.muted },
  centerValue: { fontFamily: font.bold, fontSize: 18, color: colors.onSurface },
  centerSub: { fontFamily: font.regular, fontSize: 10, color: colors.muted, textAlign: "center" },
  legend: { alignSelf: "stretch", gap: 2 },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 40, paddingHorizontal: 6, borderRadius: radius.sm },
  rowOn: { backgroundColor: colors.surfaceSecondary },
  swatch: { width: 12, height: 12, borderRadius: 3 },
  rowLabel: { flex: 1, fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  rowValue: { fontFamily: font.medium, fontSize: fontSize.xs, color: colors.onSurface },
});
