/**
 * Phase 48 · Chemical Readings row (mobile) — manual text entry only.
 *
 * Replaces the Phase 37 chip-scale UI. Each reading is now a single
 * numeric text field + unit label, with the existing "Not tested"
 * toggle preserved from Phase 46.1. Validation is per-reading (pH ≤ 14,
 * chlorine ≤ 10, ppm-scaled up to 500/300 for alkalinity/CYA). Red
 * border + parent-blocking `invalid` prop on bad input.
 *
 * Persistence unchanged: onChange fires with a normalized number or
 * null; the parent's `useDebouncedCallback` autosave PATCHes
 * `/jobs/{id}/service-report` with the current `chemical_readings`
 * array. Ref-based debounce (Phase 44 Fix C) is respected — we never
 * read stale state here, only call onChange.
 */
import React, { useMemo, useState } from "react";
import { View, Text, TextInput, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

const normalizeKey = (name: string) =>
  String(name || "").toLowerCase().replace(/[\s()]+/g, "_");

// Phase 46.1 defaults, shown as placeholder text when the field is empty.
const DEFAULT_VALUES: Record<string, number> = {
  free_chlorine: 3,   total_chlorine: 3,  chlorine: 3,
  ph: 7.6,
  total_alkalinity: 100, alkalinity: 100,
  cyanuric_acid: 70,  cya: 70,
};

// Phase 49.1 — readings that ship in "tested" state by default. A blank
// value for these keys shows the input enabled with the default as
// placeholder text (not a "Not tested" state). The user must explicitly
// toggle "Not tested" to skip a reading; then the pill is visible and
// the input dims.
const DEFAULT_TESTED_KEYS = new Set<string>([
  "free_chlorine", "total_chlorine", "chlorine",
  "ph",
  "total_alkalinity", "alkalinity",
  "cyanuric_acid", "cya",
]);

// Phase 48 — per-key numeric bounds + decimal precision. Keys are
// normalized (snake_case) so the aliases (`chlorine`, `alkalinity`) all
// share the same rule.
type Rule = { min: number; max: number; decimals: number };
const RULES: Record<string, Rule> = {
  free_chlorine:    { min: 0, max: 10,  decimals: 2 },
  total_chlorine:   { min: 0, max: 10,  decimals: 2 },
  chlorine:         { min: 0, max: 10,  decimals: 2 },
  ph:               { min: 0, max: 14,  decimals: 2 },
  total_alkalinity: { min: 0, max: 500, decimals: 1 },
  alkalinity:       { min: 0, max: 500, decimals: 1 },
  cyanuric_acid:    { min: 0, max: 300, decimals: 1 },
  cya:              { min: 0, max: 300, decimals: 1 },
  salt:             { min: 0, max: 6000, decimals: 0 },
};

function validate(rule: Rule | undefined, raw: string): { value: number | null; invalid: boolean } {
  if (raw === "" || raw == null) return { value: null, invalid: false };
  // Reject anything with more than 1 dot, or non-numeric junk.
  if (!/^\d*\.?\d*$/.test(raw)) return { value: null, invalid: true };
  const n = Number(raw);
  if (!isFinite(n) || n < 0) return { value: null, invalid: true };
  if (rule) {
    if (n < rule.min || n > rule.max) return { value: null, invalid: true };
    // Reject too many decimal places.
    const dot = raw.indexOf(".");
    if (dot >= 0 && raw.length - dot - 1 > rule.decimals) {
      return { value: null, invalid: true };
    }
  }
  return { value: rule && rule.decimals === 0 ? Math.round(n) : n, invalid: false };
}

function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const secs = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (secs < 60) return `${Math.floor(secs)}s ago`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
    return `${Math.floor(secs / 86400)}d ago`;
  } catch { return "—"; }
}

type Props = {
  readingKey?: string;
  label: string;
  unit?: string;
  value: number | string | null;
  locked?: boolean;
  previous?: { value: number | null; at?: string | null } | null;
  recent?: number[];
  onChange: (val: number | null) => void;
};

export default function ReadingChipRow({
  readingKey, label, unit, value, locked, previous, recent, onChange,
}: Props) {
  const key = normalizeKey(readingKey || label);
  const rule = RULES[key];
  const hasValue = value != null && value !== "";
  // Phase 49.1 — for the 5 default-tested readings, a blank value is NOT
  // "not tested"; it just means the tech hasn't typed yet. Only explicit
  // toggle sets notTested = true. For other readings (Salt, Calcium
  // Hardness, etc.) fall back to the old "blank == not tested" behavior.
  const [manualNotTested, setManualNotTested] = React.useState<boolean>(
    !hasValue && !DEFAULT_TESTED_KEYS.has(key),
  );
  const notTested = manualNotTested;

  // Local draft so users can type partial values ("7.") without triggering
  // invalidation until they commit.
  const [draft, setDraft] = useState<string>(hasValue ? String(value) : "");

  // If the parent value changes (autosave hydrate, wipe, etc.) reset draft
  // AND clear the manual-not-tested flag when a real value arrives.
  React.useEffect(() => {
    setDraft(hasValue ? String(value) : "");
    if (hasValue) setManualNotTested(false);
  }, [value, hasValue]);

  const { value: numericDraft, invalid } = useMemo(
    () => validate(rule, draft),
    [rule, draft],
  );

  // Phase 49.6 — median of recent 4 values (from bootstrap); flag draft
  // as outlier when > 2× or < 0.5× the median (typo protection).
  const recentArr = Array.isArray(recent) ? recent.filter((x) => Number.isFinite(x)) : [];
  const median = useMemo(() => {
    if (recentArr.length === 0) return null;
    const sorted = [...recentArr].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }, [recentArr]);
  const draftNum = Number(draft);
  const isOutlier = median != null && median > 0 && Number.isFinite(draftNum) && draftNum > 0
    && (draftNum > 2 * median || draftNum < 0.5 * median);

  const commit = () => {
    if (locked) return;
    if (draft === "") { onChange(null); return; }
    if (invalid) return;
    onChange(numericDraft);
  };

  return (
    <View
      testID={`pool-reading-${key}-slider`}
      style={[styles.card, notTested && styles.cardDim]}
    >
      <View style={styles.header}>
        <Text style={styles.label}>
          {label}{unit ? ` (${unit})` : ""}
        </Text>
        <Pressable
          onPress={() => {
            if (locked) return;
            if (notTested) {
              // Toggle OFF: exit not-tested state, keep field empty so
              // the placeholder shows the default; user types to fill.
              setManualNotTested(false);
              onChange(null);
            } else {
              // Toggle ON: mark not-tested, clear value.
              setManualNotTested(true);
              setDraft("");
              onChange(null);
            }
          }}
          disabled={!!locked}
          style={[styles.notTestedBtn, notTested && styles.notTestedBtnActive]}
          testID={`pool-reading-${key}-not-tested`}
          accessibilityLabel={`Toggle not tested for ${label}`}
        >
          <Text style={[styles.notTestedText, notTested && styles.notTestedTextActive]}>
            {notTested ? "Not tested" : "—"}
          </Text>
        </Pressable>
      </View>

      <View style={styles.inputRow}>
        <TextInput
          testID={`pool-reading-${key}-input`}
          keyboardType="decimal-pad"
          editable={!locked && !notTested}
          value={draft}
          onChangeText={setDraft}
          onEndEditing={commit}
          onBlur={commit}
          onSubmitEditing={commit}
          placeholder={String(DEFAULT_VALUES[key] ?? "")}
          placeholderTextColor={colors.muted}
          style={[
            styles.input,
            invalid && styles.inputInvalid,
            (locked || notTested) && styles.inputDisabled,
          ]}
        />
        {unit ? (
          <Text style={styles.unit} testID={`pool-reading-${key}-unit`}>
            {unit}
          </Text>
        ) : null}
      </View>
      {invalid ? (
        <Text style={styles.errText} testID={`pool-reading-${key}-error`}>
          Value out of range{rule ? ` (${rule.min}–${rule.max}, ${rule.decimals}dp)` : ""}.
        </Text>
      ) : isOutlier ? (
        <Text style={styles.recheckText} testID={`pool-reading-${key}-recheck`}>
          ⚠ Recheck? Recent median {median} · you typed {draftNum}
        </Text>
      ) : null}

      <Text style={styles.prev} testID={`pool-reading-${key}-previous`}>
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
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    backgroundColor: colors.surface,
    padding: spacing.sm, marginBottom: spacing.sm,
  },
  cardDim: { opacity: 0.7 },
  header: {
    flexDirection: "row", alignItems: "center",
    justifyContent: "space-between", marginBottom: spacing.xs,
  },
  label: { fontFamily: font.semibold, fontSize: 11, textTransform: "uppercase",
           letterSpacing: 0.4, color: colors.onSurface, flex: 1 },
  notTestedBtn: {
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: radius.sm, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface,
  },
  notTestedBtnActive: { borderColor: colors.brand, backgroundColor: colors.brandTertiary },
  notTestedText: { fontFamily: font.semibold, fontSize: 10, color: colors.muted,
                    letterSpacing: 0.4, textTransform: "uppercase" },
  notTestedTextActive: { color: colors.brand },
  inputRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  input: {
    flex: 1, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.sm, paddingHorizontal: 10, paddingVertical: 8,
    fontFamily: font.semibold, fontSize: fontSize.base,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  inputInvalid: { borderColor: "#DC2626", borderWidth: 2 },
  inputDisabled: { backgroundColor: colors.surfaceSecondary, color: colors.muted },
  unit: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted, minWidth: 30 },
  errText: {
    fontFamily: font.semibold, fontSize: 11,
    color: "#B91C1C", marginTop: 4,
  },
  recheckText: {
    fontFamily: font.semibold, fontSize: 11,
    color: "#854D0E", marginTop: 4,
    backgroundColor: "#FEF9C3", borderColor: "#FDE68A", borderWidth: 1,
    borderRadius: 4, paddingHorizontal: 6, paddingVertical: 3,
    alignSelf: "flex-start",
  },
  prev: { fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 6 },
});
