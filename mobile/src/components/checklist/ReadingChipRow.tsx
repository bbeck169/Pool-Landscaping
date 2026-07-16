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
  onChange: (val: number | null) => void;
};

export default function ReadingChipRow({
  readingKey, label, unit, value, locked, previous, onChange,
}: Props) {
  const key = normalizeKey(readingKey || label);
  const rule = RULES[key];
  const notTested = value == null || value === "";

  // Local draft so users can type partial values ("7.") without triggering
  // invalidation until they commit.
  const [draft, setDraft] = useState<string>(notTested ? "" : String(value));

  // If the parent value changes (autosave hydrate, wipe, etc.) reset draft.
  React.useEffect(() => {
    setDraft(notTested ? "" : String(value));
  }, [value, notTested]);

  const { value: numericDraft, invalid } = useMemo(
    () => validate(rule, draft),
    [rule, draft],
  );

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
            if (notTested) onChange(DEFAULT_VALUES[key] ?? 0);
            else onChange(null);
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
  prev: { fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 6 },
});
