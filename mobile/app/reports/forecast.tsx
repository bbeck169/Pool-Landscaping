import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, RefreshControl, Pressable,
  ActivityIndicator, Modal, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import DateTimePicker from "@react-native-community/datetimepicker";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Header } from "@/src/components/widgets";

/**
 * Phase (Feb-2026) · mobile Forecast Revenue.
 *
 * Mirrors ``frontend/src/pages/reports/Forecast.jsx`` — same preset
 * chips (today / tomorrow / this week / this month / custom), same
 * endpoint (``GET /api/reports/forecast?range={preset}`` +
 * ``?range=custom&date_from&date_to``), same companion
 * ``/api/reports/forecast-cards`` KPI list.
 *
 * Web's default is a ``days``-based mode; mobile omits that in favour
 * of the five preset chips per the product spec, defaulting to
 * ``week``.
 */
type RangeKey = "today" | "tomorrow" | "week" | "month" | "custom";

const PRESETS: { key: RangeKey; label: string; testID: string }[] = [
  { key: "today",    label: "Today",       testID: "forecast-filter-today" },
  { key: "tomorrow", label: "Tomorrow",    testID: "forecast-filter-tomorrow" },
  { key: "week",     label: "This Week",   testID: "forecast-filter-this-week" },
  { key: "month",    label: "This Month",  testID: "forecast-filter-this-month" },
  { key: "custom",   label: "Custom",      testID: "forecast-filter-custom" },
];

const iso = (d: Date) => d.toISOString().slice(0, 10);
const short = (d: string) => {
  const [y, m, dd] = d.split("-");
  return `${m}/${dd}`;
};

export default function ForecastRevenue() {
  const [preset, setPreset] = useState<RangeKey>("week");
  const [customFrom, setCustomFrom] = useState<string>(iso(new Date()));
  const [customTo, setCustomTo] = useState<string>(
    iso(new Date(Date.now() + 6 * 86400000)),
  );
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerMode, setPickerMode] = useState<"from" | "to">("from");

  const [data, setData] = useState<any>(null);
  const [cards, setCards] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const canFetch = preset !== "custom" || (customFrom && customTo);

  const load = useCallback(async () => {
    if (!canFetch) return;
    setBusy(true);
    const url =
      preset === "custom"
        ? `/reports/forecast?range=custom&date_from=${customFrom}&date_to=${customTo}`
        : `/reports/forecast?range=${preset}`;
    try {
      const [f, c] = await Promise.all([
        api.get(url),
        api.get(`/reports/forecast-cards`),
      ]);
      setData(f);
      setCards(c?.cards || c || []);
    } catch {
      setData(null);
      setCards([]);
    } finally {
      setLoading(false);
      setBusy(false);
      setRefreshing(false);
    }
  }, [preset, customFrom, customTo, canFetch]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const customLabel = useMemo(() => {
    if (preset !== "custom") return "Custom";
    if (!customFrom || !customTo) return "Custom";
    return `${short(customFrom)} – ${short(customTo)}`;
  }, [preset, customFrom, customTo]);

  const openPickerFrom = () => { setPickerMode("from"); setPickerOpen(true); };
  const openPickerTo   = () => { setPickerMode("to"); setPickerOpen(true); };

  const onPickerChange = (_: any, selected?: Date) => {
    // Android closes on set; iOS stays open — keep behaviour parity by
    // closing after every pick, users tap the "to" button to change end.
    setPickerOpen(false);
    if (!selected) return;
    if (pickerMode === "from") setCustomFrom(iso(selected));
    else setCustomTo(iso(selected));
  };

  const series: { label: string; value: number }[] = data?.series || [];
  const total = data?.total ?? series.reduce((a, r) => a + Number(r.value || 0), 0);
  const max = Math.max(...series.map((r) => r.value), 1);

  return (
    <View style={s.root} testID="forecast-revenue-page">
      <Header title="Forecast Revenue" back subtitle="Projected billing for the selected window" />

      {/* Chip row */}
      <View style={s.chipBar}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow}>
          {PRESETS.map((p) => {
            const active = preset === p.key;
            const label = p.key === "custom" ? customLabel : p.label;
            return (
              <Pressable
                key={p.key}
                testID={p.testID}
                onPress={() => {
                  setPreset(p.key);
                  // Opening the custom picker on tap when the chip
                  // becomes active feels most natural — mirrors the
                  // web page's inline calendar reveal.
                  if (p.key === "custom") openPickerFrom();
                }}
                style={[s.chip, active && s.chipActive]}
              >
                <Text style={[s.chipText, active && s.chipTextActive]}>{label}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>

      {/* Custom range secondary controls */}
      {preset === "custom" ? (
        <View style={s.customRow} testID="forecast-custom-controls">
          <Pressable testID="forecast-custom-from" onPress={openPickerFrom} style={s.customPill}>
            <Ionicons name="calendar-outline" size={14} color={colors.brand} />
            <Text style={s.customPillText}>From {short(customFrom)}</Text>
          </Pressable>
          <Pressable testID="forecast-custom-to" onPress={openPickerTo} style={s.customPill}>
            <Ionicons name="calendar-outline" size={14} color={colors.brand} />
            <Text style={s.customPillText}>To {short(customTo)}</Text>
          </Pressable>
        </View>
      ) : null}

      {/* Body */}
      {loading ? (
        <ActivityIndicator style={{ flex: 1 }} color={colors.brand} testID="forecast-loading" />
      ) : (
        <ScrollView
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        >
          {busy ? (
            <View style={s.busyBar} testID="forecast-refetching">
              <ActivityIndicator size="small" color={colors.brand} />
              <Text style={s.busyText}>Updating forecast…</Text>
            </View>
          ) : null}

          {/* Total card */}
          <View style={s.totalCard}>
            <Text style={s.totalLabel}>Projected revenue</Text>
            <Text style={s.totalVal}>{money(total)}</Text>
            <Text style={s.totalSub}>
              {preset === "custom"
                ? `${customFrom} → ${customTo}`
                : PRESETS.find((p) => p.key === preset)?.label}
            </Text>
          </View>

          {/* Companion KPI cards */}
          {cards.length ? (
            <View style={s.cardsGrid} testID="forecast-cards">
              {cards.map((c: any) => (
                <View key={c.key || c.label} style={s.kpi}>
                  <Text style={s.kpiLabel}>{c.label}</Text>
                  <Text style={s.kpiVal}>
                    {typeof c.value === "number" ? money(c.value) : String(c.value ?? "—")}
                  </Text>
                  {c.sub ? <Text style={s.kpiSub}>{c.sub}</Text> : null}
                </View>
              ))}
            </View>
          ) : null}

          {/* Series bar list */}
          {series.length ? (
            <View style={s.chartCard} testID="forecast-series">
              <Text style={s.chartTitle}>Projection</Text>
              {series.map((r) => (
                <View key={r.label} style={s.row}>
                  <Text style={s.rowLabel} numberOfLines={1}>{r.label}</Text>
                  <View style={s.barTrack}>
                    <View style={[s.bar, { width: `${Math.max(4, (r.value / max) * 100)}%` }]} />
                  </View>
                  <Text style={s.rowValue}>{money(r.value)}</Text>
                </View>
              ))}
            </View>
          ) : (
            <View style={s.emptyCard} testID="forecast-empty">
              <Ionicons name="trending-up-outline" size={28} color={colors.muted} />
              <Text style={s.emptyTitle}>No projections yet</Text>
              <Text style={s.emptySub}>Pick a different window or check back after new jobs are scheduled.</Text>
            </View>
          )}
        </ScrollView>
      )}

      {/* Date-range picker modal */}
      {pickerOpen ? (
        Platform.OS === "ios" ? (
          <Modal
            visible
            transparent
            animationType="fade"
            onRequestClose={() => setPickerOpen(false)}
            testID="forecast-custom-range-picker"
          >
            <View style={s.pickerBackdrop}>
              <View style={s.pickerCard}>
                <Text style={s.pickerTitle}>
                  {pickerMode === "from" ? "Select start date" : "Select end date"}
                </Text>
                <DateTimePicker
                  value={new Date(pickerMode === "from" ? customFrom : customTo)}
                  mode="date"
                  display="spinner"
                  onChange={onPickerChange}
                />
                <Pressable
                  testID="forecast-picker-done"
                  onPress={() => setPickerOpen(false)}
                  style={s.pickerDoneBtn}
                >
                  <Text style={s.pickerDoneText}>Done</Text>
                </Pressable>
              </View>
            </View>
          </Modal>
        ) : (
          // Android's DateTimePicker is a dialog on its own — no Modal wrapper.
          <View testID="forecast-custom-range-picker">
            <DateTimePicker
              value={new Date(pickerMode === "from" ? customFrom : customTo)}
              mode="date"
              display="default"
              onChange={onPickerChange}
            />
          </View>
        )
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  chipBar: {
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipRow: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md, gap: 8 },
  chip: {
    paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  chipTextActive: { color: "#fff" },
  customRow: {
    flexDirection: "row", gap: 8,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
    backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  customPill: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: colors.brandTertiary,
  },
  customPillText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },

  busyBar: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: spacing.sm, marginBottom: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: colors.brandTertiary,
  },
  busyText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },

  totalCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  totalLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted, letterSpacing: 1 },
  totalVal: { fontFamily: font.bold, fontSize: fontSize["3xl"], color: colors.onSurface, marginVertical: 4 },
  totalSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },

  cardsGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.md },
  kpi: {
    flexBasis: "48%", flexGrow: 1,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
  },
  kpiLabel: { fontFamily: font.semibold, fontSize: 11, color: colors.muted, letterSpacing: 1 },
  kpiVal: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 4 },
  kpiSub: { fontFamily: font.regular, fontSize: 12, color: colors.muted, marginTop: 2 },

  chartCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
    gap: spacing.sm,
  },
  chartTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: 4 },

  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  rowLabel: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  barTrack: { flex: 1.4, height: 6, borderRadius: 999, backgroundColor: colors.surfaceTertiary, overflow: "hidden" },
  bar: { height: 6, borderRadius: 999, backgroundColor: colors.brand },
  rowValue: { minWidth: 78, textAlign: "right", fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },

  emptyCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.xl,
    alignItems: "center",
    gap: 8,
  },
  emptyTitle: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  emptySub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },

  pickerBackdrop: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.55)",
    alignItems: "center", justifyContent: "center", padding: spacing.lg,
  },
  pickerCard: {
    width: "100%", maxWidth: 380,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    gap: spacing.md,
    alignItems: "center",
  },
  pickerTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  pickerDoneBtn: {
    alignSelf: "stretch",
    paddingVertical: 12,
    borderRadius: radius.md,
    backgroundColor: colors.brand,
    alignItems: "center",
  },
  pickerDoneText: { fontFamily: font.bold, color: "#fff", fontSize: fontSize.base },
});
