/**
 * Phase 39A · Revenue Insights date-range dropdown (web parity:
 * ``RevenueDateRangeFilter.jsx``). Pill toggle → bottom sheet with the
 * 9 presets; "Custom Range" reveals Start / End (native date picker on
 * iOS/Android, YYYY-MM-DD text on web) + Apply. Persists the last
 * selection (AsyncStorage, web's key) and emits once after hydration.
 * testIDs mirror web: revenue-range-filter / -toggle / -preset-{key} /
 * -custom-start / -custom-end / -custom-apply / -custom-summary.
 */
import React, { useEffect, useRef, useState } from "react";
import { View, Text, Pressable, StyleSheet, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import DateTimePicker from "@react-native-community/datetimepicker";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Sheet } from "@/src/components/ui";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { useAuth } from "@/src/auth";
import {
  RANGE_PRESETS, rangeFromPreset, loadPersistedRange, persistRange, defaultCustom,
  isValidIsoDate, isoDate, TENANT_TZ_FALLBACK, type RangePresetKey, type DateRange,
} from "@/src/lib/revenueRange";

export type RevenueRange = DateRange & { preset: RangePresetKey };

type Props = { onChange: (r: RevenueRange) => void; defaultPreset?: RangePresetKey; tenantTimezone?: string };

function DateField({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  if (Platform.OS === "web") {
    return (
      <View style={s.field}>
        <Text style={s.fieldLabel}>{label}</Text>
        <AppTextInput value={value} onChangeText={onChange} placeholder="YYYY-MM-DD" style={s.input} testID={id} />
      </View>
    );
  }
  const date = isValidIsoDate(value) ? new Date(`${value}T12:00:00`) : new Date();
  return (
    <View style={s.field}>
      <Text style={s.fieldLabel}>{label}</Text>
      <Pressable style={s.input} onPress={() => setOpen((v) => !v)} testID={id}>
        <Text style={s.inputText}>{value}</Text>
      </Pressable>
      {open ? (
        <DateTimePicker
          value={date}
          mode="date"
          display={Platform.OS === "ios" ? "inline" : "default"}
          onChange={(e: any, d?: Date) => {
            if (Platform.OS !== "ios") setOpen(false);
            if (e?.type !== "dismissed" && d) onChange(isoDate(d));
          }}
          testID={`${id}-picker`}
        />
      ) : null}
    </View>
  );
}

export default function RevenueDateRangeFilter({ onChange, defaultPreset = "this_month", tenantTimezone }: Props) {
  const { user } = useAuth() as any;
  const tz = tenantTimezone ?? user?.tenant?.timezone ?? TENANT_TZ_FALLBACK;
  const [preset, setPreset] = useState<RangePresetKey>(defaultPreset);
  const [custom, setCustom] = useState<DateRange>(defaultCustom());
  const [draft, setDraft] = useState<DateRange>(custom);
  const [open, setOpen] = useState(false);
  const cb = useRef(onChange);
  cb.current = onChange;

  const emit = (p: RangePresetKey, c: DateRange) => {
    persistRange({ preset: p, custom: c });
    cb.current({ preset: p, ...rangeFromPreset(p, c, { tenantTimezone: tz }) });
  };

  useEffect(() => {
    let alive = true;
    loadPersistedRange().then((saved) => {
      if (!alive) return;
      const p = saved?.preset || defaultPreset;
      const c = saved?.custom || defaultCustom();
      setPreset(p); setCustom(c); setDraft(c);
      cb.current({ preset: p, ...rangeFromPreset(p, c, { tenantTimezone: tz }) });
    });
    return () => { alive = false; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- mount-only hydration (web parity)

  const pick = (k: RangePresetKey) => {
    setPreset(k);
    if (k !== "custom") { setOpen(false); emit(k, custom); }
  };
  const draftOk = isValidIsoDate(draft.start) && isValidIsoDate(draft.end) && draft.start <= draft.end;
  const apply = () => { if (!draftOk) return; setCustom(draft); setOpen(false); emit("custom", draft); };
  const label = RANGE_PRESETS.find((p) => p.key === preset)?.label || "Range";

  return (
    <View testID="revenue-range-filter">
      <Pressable style={({ pressed }) => [s.toggle, pressed && { opacity: 0.7 }]} onPress={() => setOpen(true)} testID="revenue-range-toggle"
        accessibilityRole="button" accessibilityLabel={`Revenue range: ${label}`}>
        <Ionicons name="calendar-outline" size={14} color={colors.onSurface} />
        <Text style={s.toggleText}>{label}</Text>
        {preset === "custom" ? (
          <Text style={s.summary} testID="revenue-range-custom-summary">{`${custom.start} → ${custom.end}`}</Text>
        ) : null}
        <Ionicons name="chevron-down" size={14} color={colors.onSurface} />
      </Pressable>
      <Sheet visible={open} onClose={() => setOpen(false)} title="Revenue range" testID="revenue-range-popover">
        {RANGE_PRESETS.map((p) => {
          const on = preset === p.key;
          return (
            <Pressable key={p.key} onPress={() => pick(p.key)} style={[s.preset, on && s.presetOn]}
              testID={`revenue-range-preset-${p.key}`} accessibilityState={{ selected: on }}>
              <Text style={[s.presetText, on && s.presetTextOn]}>{p.label}</Text>
              {on ? <Ionicons name="checkmark" size={18} color={colors.brand} /> : null}
            </Pressable>
          );
        })}
        {preset === "custom" ? (
          <View style={s.custom} testID="revenue-range-custom">
            <DateField id="revenue-range-custom-start" label="Start" value={draft.start} onChange={(v) => setDraft((d) => ({ ...d, start: v }))} />
            <DateField id="revenue-range-custom-end" label="End" value={draft.end} onChange={(v) => setDraft((d) => ({ ...d, end: v }))} />
            <Pressable style={[s.apply, !draftOk && { opacity: 0.5 }]} onPress={apply} disabled={!draftOk}
              testID="revenue-range-custom-apply" accessibilityState={{ disabled: !draftOk }}>
              <Text style={s.applyText}>Apply</Text>
            </Pressable>
          </View>
        ) : null}
      </Sheet>
    </View>
  );
}

const s = StyleSheet.create({
  toggle: {
    flexDirection: "row", alignItems: "center", gap: 6, minHeight: 40,
    paddingHorizontal: spacing.md, borderRadius: radius.pill,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  toggleText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  summary: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  preset: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    minHeight: 48, paddingHorizontal: spacing.md, borderRadius: radius.md,
  },
  presetOn: { backgroundColor: colors.brandTertiary },
  presetText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  presetTextOn: { fontFamily: font.bold, color: colors.brand },
  custom: { borderTopWidth: 1, borderTopColor: colors.border, marginTop: spacing.sm, paddingTop: spacing.md, gap: spacing.sm },
  field: { gap: 4 },
  fieldLabel: { fontFamily: font.medium, fontSize: fontSize.xs, color: colors.muted },
  input: {
    minHeight: 44, justifyContent: "center", paddingHorizontal: spacing.md,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  inputText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  apply: { minHeight: 44, borderRadius: radius.pill, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center", marginTop: spacing.xs },
  applyText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});
