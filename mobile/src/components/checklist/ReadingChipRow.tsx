/**
 * Phase 36b · Mobile ReadingChipRow — mirror of the web Phase 36
 * slider-chip UI (see `/app/frontend/src/components/checklist/PoolChecklistForm.jsx`).
 *
 * One row per chemical reading. The tech taps a chip to set the value;
 * the pencil icon opens a small numeric TextInput for exact entry.
 * "N/A" clears the reading (sends null). Under the chips we show
 * "Previously tested at: <value> · <relative time>" using the payload
 * from `GET /api/service-reports/last-readings`.
 *
 * Chip scales and palettes are IDENTICAL to the web constants so the
 * two platforms present the same options.
 */
import React, { useState } from "react";
import { View, Text, Pressable, TextInput, ScrollView, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font } from "@/src/theme";

// ── Chip scales (Phase 37 — parity with web PoolChecklistForm.jsx) ─────
const _seqInc = (start: number, stop: number, step: number): number[] => {
  const out: number[] = [];
  const n = Math.round((stop - start) / step) + 1;
  for (let i = 0; i < n; i += 1) out.push(Number((start + i * step).toFixed(2)));
  return out;
};
const _chlorineVals: (number | string)[] = _seqInc(0, 20, 0.5);
const _phVals: (number | string)[] = ["<6", ..._seqInc(6.0, 8.5, 0.1)];
const _alkVals: (number | string)[] = _seqInc(20, 200, 10);
const _tempVals: (number | string)[] = ["N/A", 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100];
const _psiVals:  (number | string)[] = ["N/A", 0, 2.5, 5, 7.5, 10, 12.5, 15, 17.5, 20, 22.5, 25, 30];
const _cyaVals: (number | string)[] = [
  "N/A",
  ...Array.from({ length: 49 }, (_, i) => 20 + i * 10),
  ">500",
];

const PH_UNDER_SIX_VALUE = 5.9;
const CYA_OVER_500_VALUE = 501;

const CHIP_SCALES: Record<string, { values: (number | string)[]; palette: string }> = {
  total_chlorine:    { values: _chlorineVals,   palette: "chlorine" },
  free_chlorine:     { values: _chlorineVals,   palette: "chlorine" },
  chlorine:          { values: _chlorineVals,   palette: "chlorine" },
  combined_chlorine: { values: _chlorineVals,   palette: "chlorine" },
  ph:                { values: _phVals,         palette: "ph" },
  alkalinity:        { values: _alkVals,        palette: "alkalinity" },
  total_alkalinity:  { values: _alkVals,        palette: "alkalinity" },
  cyanuric_acid:     { values: _cyaVals,        palette: "optional" },
  cya:               { values: _cyaVals,        palette: "optional" },
  calcium_hardness:  { values: ["N/A", 0, 100, 150, 200, 250, 300, 400, 500],     palette: "optional" },
  phosphate:         { values: ["N/A", 0, 125, 250, 500, 1000, 2500],             palette: "optional" },
  phosphates:        { values: ["N/A", 0, 125, 250, 500, 1000, 2500],             palette: "optional" },
  salt:              { values: ["N/A", 0, 1000, 2000, 2700, 3200, 3600, 4500],    palette: "optional" },
  tds:               { values: ["N/A", 0, 500, 1000, 1500, 2000, 3000],           palette: "optional" },
  water_temp:        { values: _tempVals,       palette: "optional" },
  temperature:       { values: _tempVals,       palette: "optional" },
  filter_psi:        { values: _psiVals,        palette: "optional" },
  psi:               { values: _psiVals,        palette: "optional" },
};

// "N/A" → null, "<6" → 5.9, ">500" → 501, else numeric.
const chipToValue = (v: number | string): number | null => {
  if (v === "N/A") return null;
  if (v === "<6") return PH_UNDER_SIX_VALUE;
  if (v === ">500") return CYA_OVER_500_VALUE;
  return v as number;
};
const isChipSelected = (chipRaw: number | string, current: number | string | null): boolean => {
  if (chipRaw === "N/A") return current == null || current === "";
  if (chipRaw === "<6") return typeof current === "number" && current < 6.0;
  if (chipRaw === ">500") return typeof current === "number" && current > 500;
  return current != null && current !== "" && Number(current) === Number(chipRaw);
};

type Palette = { bg: string; sel: string; selFg: string; fg: string;
                 inRangeBg?: string; inRangeSel?: string; inRangeFg?: string };

const PALETTES: Record<string, Palette> = {
  chlorine:   { bg: "#CFFAFE", sel: "#0891B2", selFg: "#FFFFFF", fg: "#155E75" },
  ph:         { bg: "#FEE2E2", sel: "#DC2626", selFg: "#FFFFFF", fg: "#7F1D1D",
                inRangeBg: "#DCFCE7", inRangeSel: "#16A34A", inRangeFg: "#14532D" },
  alkalinity: { bg: "#DCFCE7", sel: "#16A34A", selFg: "#FFFFFF", fg: "#14532D" },
  optional:   { bg: "#FFEDD5", sel: "#EA580C", selFg: "#FFFFFF", fg: "#7C2D12" },
};

const normalizeKey = (name: string) =>
  String(name || "").toLowerCase().replace(/[\s()]+/g, "_");

// Phase 46.1 — Default values for a "just started this reading" state so
// techs land on sensible presets when they toggle "Not tested" off.
const DEFAULT_VALUES: Record<string, number> = {
  free_chlorine: 3,
  total_chlorine: 3,
  chlorine: 3,
  ph: 7.6,
  total_alkalinity: 100,
  alkalinity: 100,
  cyanuric_acid: 70,
  cya: 70,
};

const isPhSweetSpot = (v: number | null) =>
  typeof v === "number" && v >= 7.2 && v <= 7.6;

const formatRelative = (iso?: string | null) => {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const ms = Date.now() - d.getTime();
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const dd = Math.floor(h / 24);
    if (dd < 30) return `${dd}d ago`;
    return d.toLocaleDateString();
  } catch { return "—"; }
};

export type ReadingChipRowProps = {
  readingKey: string;   // canonical key from server (e.g. "ph")
  label: string;        // display label from server (e.g. "pH")
  unit?: string;
  value: number | string | null;
  step?: number | string;
  min?: number;
  max?: number;
  locked?: boolean;
  previous?: { value: number | null; at?: string | null } | null;
  onChange: (val: number | null) => void;
};

export default function ReadingChipRow({
  readingKey, label, unit, value, step, min, max,
  locked, previous, onChange,
}: ReadingChipRowProps) {
  const key = normalizeKey(readingKey || label);
  const scale = CHIP_SCALES[key];
  const palette = scale ? PALETTES[scale.palette] : PALETTES.optional;

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>(value == null ? "" : String(value));

  const numericValue = typeof value === "string" && value !== ""
    ? Number(value)
    : (value as number | null);

  const commit = () => {
    if (draft === "") onChange(null);
    else {
      const n = parseFloat(draft);
      onChange(Number.isFinite(n) ? n : null);
    }
    setEditing(false);
  };

  const openEdit = () => {
    if (locked) return;
    setDraft(value == null ? "" : String(value));
    setEditing(true);
  };

  return (
    <View
      testID={`pool-reading-${key}-slider`}
      style={styles.card}
    >
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Pressable
            onPress={openEdit}
            disabled={!!locked}
            hitSlop={8}
            style={styles.editBtn}
            testID={`pool-reading-${key}-edit`}
            accessibilityLabel={`Edit ${label}`}
          >
            <Ionicons name="pencil" size={12} color={colors.muted} />
          </Pressable>
          <Text style={styles.label}>
            {label}{unit ? ` (${unit})` : ""}
          </Text>
        </View>
        <View style={styles.headerRight}>
          <Pressable
            onPress={() => {
              if (locked) return;
              if (value == null || value === "") {
                onChange(DEFAULT_VALUES[key] ?? 0);
              } else {
                onChange(null);
              }
            }}
            disabled={!!locked}
            style={[
              styles.notTestedBtn,
              (value == null || value === "") && styles.notTestedBtnActive,
            ]}
            testID={`pool-reading-${key}-not-tested`}
            accessibilityLabel={`Toggle not tested for ${label}`}
          >
            <Text style={[
              styles.notTestedText,
              (value == null || value === "") && styles.notTestedTextActive,
            ]}>
              {value == null || value === "" ? "Not tested" : "—"}
            </Text>
          </Pressable>
          <Text style={[styles.currentVal, { color: palette.sel }]}>
            {value == null || value === "" ? "—" : String(value)}
          </Text>
        </View>
      </View>

      {editing ? (
        <View style={styles.editRow}>
          <TextInput
            keyboardType="decimal-pad"
            autoFocus
            editable={!locked}
            value={draft}
            onChangeText={setDraft}
            onSubmitEditing={commit}
            onBlur={commit}
            style={styles.editInput}
            testID={`pool-reading-${key}-input`}
            placeholder="—"
            placeholderTextColor={colors.muted}
          />
          <Pressable onPress={commit} style={styles.setBtn}>
            <Text style={styles.setBtnText}>Set</Text>
          </Pressable>
          <Pressable onPress={() => setEditing(false)} style={styles.cancelBtn} hitSlop={6}>
            <Ionicons name="close" size={14} color={colors.muted} />
          </Pressable>
        </View>
      ) : null}

      {scale ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.chipRow}
          style={value == null || value === "" ? { opacity: 0.4 } : undefined}
        >
          {scale.values.map((v) => {
            const chipVal = chipToValue(v);
            const isSelected = isChipSelected(v, value);
            const useGreen =
              scale.palette === "ph" && isPhSweetSpot(typeof chipVal === "number" ? chipVal : null);
            const bg = isSelected
              ? (useGreen ? palette.inRangeSel! : palette.sel)
              : (useGreen ? palette.inRangeBg! : palette.bg);
            const fg = isSelected
              ? palette.selFg
              : (useGreen ? palette.inRangeFg! : palette.fg);
            const borderColor = isSelected
              ? (useGreen ? palette.inRangeSel! : palette.sel)
              : bg;
            return (
              <Pressable
                key={String(v)}
                disabled={!!locked}
                onPress={() => onChange(chipVal)}
                testID={`pool-reading-${key}-chip-${String(v)}`}
                style={[
                  styles.chip,
                  {
                    backgroundColor: bg,
                    borderColor,
                    borderWidth: isSelected ? 2 : 1,
                  },
                ]}
              >
                <Text style={[styles.chipText, { color: fg }]}>{String(v)}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
      ) : (
        <TextInput
          keyboardType="decimal-pad"
          editable={!locked}
          value={value == null ? "" : String(value)}
          onChangeText={(v) => onChange(v === "" ? null : parseFloat(v))}
          style={styles.fallbackInput}
          placeholder="—"
          placeholderTextColor={colors.muted}
          testID={`pool-reading-${key}-input`}
        />
      )}

      <Text
        style={styles.prev}
        testID={`pool-reading-${key}-previous`}
      >
        Previously tested at:{" "}
        {previous && previous.value != null
          ? `${previous.value}${unit ? ` ${unit}` : ""} · ${formatRelative(previous.at || null)}`
          : "—"}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    padding: spacing.sm,
    marginBottom: spacing.sm,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 6,
  },
  headerLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    flex: 1,
  },
  editBtn: {
    padding: 2,
  },
  label: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.onSurface,
    letterSpacing: 0.6,
    textTransform: "uppercase",
  },
  currentVal: {
    fontFamily: font.bold,
    fontSize: 13,
  },
  headerRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  notTestedBtn: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  notTestedBtnActive: {
    borderColor: colors.brand,
    backgroundColor: colors.brandTertiary,
  },
  notTestedText: {
    fontFamily: font.semibold,
    fontSize: 10,
    color: colors.muted,
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },
  notTestedTextActive: {
    color: colors.brand,
  },
  editRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 6,
  },
  editInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 8,
    paddingVertical: 6,
    fontFamily: font.regular,
    fontSize: 13,
    color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  setBtn: {
    backgroundColor: colors.brand,
    borderRadius: radius.sm,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  setBtnText: {
    color: "#FFFFFF",
    fontFamily: font.bold,
    fontSize: 11,
  },
  cancelBtn: {
    padding: 4,
  },
  chipRow: {
    flexDirection: "row",
    gap: 6,
    paddingBottom: 2,
  },
  chip: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.sm,
    minWidth: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  chipText: {
    fontFamily: font.bold,
    fontSize: 11,
  },
  fallbackInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 8,
    paddingVertical: 8,
    fontFamily: font.regular,
    fontSize: 13,
    color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  prev: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
    marginTop: 4,
  },
});
