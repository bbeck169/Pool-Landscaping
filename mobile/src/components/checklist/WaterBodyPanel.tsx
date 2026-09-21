/**
 * Phase v · WaterBodyPanel — per-body card component.
 *
 * Renders chemistry inputs (filtered by type allow-list), a chemicals
 * section, notes, and a remove button. One card per body of water.
 *
 * Phase CHEM2 · Cyanuric alias dedupe:
 *   Legacy `cyanuric` key treated as alias for canonical `cyanuric_acid`.
 *   Read path: resolves `cyanuric` → `cyanuric_acid`.
 *   Write path: always writes `cyanuric_acid`; drops legacy `cyanuric` entry.
 */
import React, { useMemo, useCallback } from "react";
import {
  View, Text, Pressable, StyleSheet, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import {
  WaterBody, BODY_TYPE_LABELS, BODY_TYPE_TINTS,
  READING_ALLOWLIST, READING_LABELS, READING_REQUIRED,
} from "@/src/lib/waterBodies";
import AppTextInput from "@/src/components/ui/AppTextInput";
import ChemicalDropdownStack from "./ChemicalDropdownStack";

// Phase CHEM2 — alias: legacy `cyanuric` → canonical `cyanuric_acid`.
const LEGACY_ALIAS: Record<string, string> = { cyanuric: "cyanuric_acid" };

interface Props {
  body: WaterBody;
  index: number;
  locked: boolean;
  canRemove: boolean;
  /** Phase CHEM4 — body 0 is primary; its chemistry/chemicals live at report level. */
  isPrimary?: boolean;
  highlightMissing?: string[];
  onChange: (updated: WaterBody) => void;
  onRemove: () => void;
}

export default function WaterBodyPanel({
  body, index, locked, canRemove, isPrimary = false, highlightMissing, onChange, onRemove,
}: Props) {
  const tint = BODY_TYPE_TINTS[body.type] || BODY_TYPE_TINTS.pool;
  const allowedReadings = useMemo(
    () => READING_ALLOWLIST[body.type] || READING_ALLOWLIST.pool,
    [body.type],
  );
  const requiredSet = useMemo(
    () => new Set(READING_REQUIRED[body.type] || []),
    [body.type],
  );
  const missingSet = useMemo(
    () => new Set(highlightMissing || []),
    [highlightMissing],
  );

  // Phase CHEM2 — alias: legacy `cyanuric` → canonical `cyanuric_acid`.

  const readingsByKey = useMemo(() => {
    const map = new Map<string, any>();
    for (const r of body.readings || []) {
      if (!r?.key) continue;
      const canonical = LEGACY_ALIAS[r.key] || r.key;
      if (canonical !== r.key && map.has(canonical)) continue;
      map.set(canonical, r);
    }
    return map;
  }, [body.readings]);

  // Phase P17.M — coerce to number | null; preserve 0 as a valid reading.
  const setReading = useCallback((key: string, raw: string) => {
    const trimmed = raw.trim();
    const coerced: number | null =
      trimmed === "" ? null : Number.isFinite(Number(trimmed)) ? Number(trimmed) : null;

    let next = [...(body.readings || [])];
    const meta = READING_LABELS[key] || { name: key, unit: "ppm" };
    if (key === "cyanuric_acid") {
      next = next.filter((r) => r.key !== "cyanuric");
    }
    const idx = next.findIndex((r) => r.key === key);
    if (idx >= 0) {
      next[idx] = { ...next[idx], value: coerced };
    } else {
      next.push({ key, name: meta.name, value: coerced, unit: meta.unit });
    }
    onChange({ ...body, readings: next });
  }, [body, onChange]);

  const setLabel = (label: string) => onChange({ ...body, label });
  const setNotes = (notes: string) => onChange({ ...body, notes });

  /* ── Phase CHEM3 · ChemicalDropdownStack adapter ─────────────────────
   *
   * ChemicalDropdownStack works with `chemicals_added[*].slug`,
   * but the body persists `chemicals_used[*].product_slug`.
   *
   * Read:  product_slug → slug  (before passing rows in)
   * Write: slug → product_slug  (on the stack's onChange callback)
   */
  const chemAdapted = useMemo(
    () => (body.chemicals_used || []).map((c: any) => ({
      ...c,
      slug: c.product_slug || c.slug,
    })),
    [body.chemicals_used],
  );

  const handleChemChange = useCallback(
    (patch: { chemicals_added: any[] }) => {
      const next = patch.chemicals_added.map((c: any) => {
        const { slug, ...rest } = c;
        return { ...rest, product_slug: slug || c.product_slug };
      });
      onChange({ ...body, chemicals_used: next });
    },
    [body, onChange],
  );

  const handleRemove = () => {
    const hasData = (body.readings || []).some((r) => r.value !== null && r.value !== "")
      || (body.chemicals_used || []).length > 0
      || (body.notes || "").trim().length > 0;
    if (hasData) {
      Alert.alert("Remove this body?", "All entered data will be lost.", [
        { text: "Cancel", style: "cancel" },
        { text: "Remove", style: "destructive", onPress: onRemove },
      ]);
    } else {
      onRemove();
    }
  };

  return (
    <View style={[s.card, { borderColor: tint.border }]} testID={`water-body-panel-${index}`}>
      {/* Header row */}
      <View style={s.headerRow}>
        <View style={[s.typeBadge, { backgroundColor: tint.bg }]}>
          <Text style={[s.typeBadgeText, { color: tint.fg }]} testID={`water-body-type-badge-${index}`}>
            {BODY_TYPE_LABELS[body.type] || body.type}
          </Text>
        </View>
        <AppTextInput
          style={s.labelInput}
          value={body.label || ""}
          onChangeText={setLabel}
          placeholder={`Label (e.g. "Backyard Pool")`}
          placeholderTextColor={colors.muted}
          editable={!locked}
          testID={`water-body-label-input-${index}`}
        />
        {canRemove && !locked ? (
          <Pressable onPress={handleRemove} hitSlop={8} testID={`water-body-remove-${index}`}>
            <Ionicons name="close-circle" size={22} color={colors.error} />
          </Pressable>
        ) : null}
      </View>

      {/* Chemistry readings — rendered for every body */}
      <Text style={s.sectionLabel}>Chemistry Readings</Text>
      {allowedReadings.map((key) => {
        const meta = READING_LABELS[key] || { name: key, unit: "ppm", short: key };
        const cur = readingsByKey.get(key);
        const isMissing = missingSet.has(key);
        const isRequired = requiredSet.has(key);
        return (
          <View key={key} style={[s.readingRow, isMissing && s.readingRowMissing]} testID={`reading-row-${index}-${key}`}>
            <View style={s.readingLabel}>
              <Text style={[s.readingName, isMissing && { color: colors.error }]}>
                {meta.name}
                {isRequired ? <Text style={{ color: colors.error }}> *</Text> : null}
              </Text>
              {meta.unit ? <Text style={s.readingUnit}>{meta.unit}</Text> : null}
            </View>
            <AppTextInput
              style={[s.readingInput, isMissing && s.readingInputMissing]}
              value={cur?.value != null ? String(cur.value) : ""}
              onChangeText={(v) => setReading(key, v)}
              keyboardType="decimal-pad"
              editable={!locked}
              placeholder="—"
              placeholderTextColor={colors.muted}
              testID={`reading-input-${index}-${key}`}
            />
          </View>
        );
      })}

      {/* Phase CHEM5 — Chemicals used on every body; header varies by isPrimary */}
      <Text style={s.sectionLabel} testID={`water-body-chem-header-${index}`}>
        {isPrimary ? "Pool" : "Additional Body of Water Chemicals"}
      </Text>
      {!isPrimary && (
        <Text style={s.subHeader} testID={`water-body-chem-subheader-${index}`}>
          {BODY_TYPE_LABELS[body.type] || body.type}
        </Text>
      )}
      <ChemicalDropdownStack
        chemicalsAdded={chemAdapted as any}
        locked={locked}
        onChange={handleChemChange}
        bodyType={body.type}
      />

      {/* Notes */}
      <Text style={s.sectionLabel}>Notes</Text>
      <AppTextInput
        style={s.notesInput}
        value={body.notes || ""}
        onChangeText={setNotes}
        multiline
        editable={!locked}
        placeholder="Notes for this body of water…"
        placeholderTextColor={colors.muted}
        testID={`water-body-notes-${index}`}
      />
    </View>
  );
}

const s = StyleSheet.create({
  card: {
    borderWidth: 1.5,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    backgroundColor: colors.surface,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  typeBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radius.sm,
  },
  typeBadgeText: {
    fontFamily: font.bold,
    fontSize: fontSize.xs,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  labelInput: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    paddingVertical: 4,
  },
  sectionLabel: {
    fontFamily: font.bold,
    fontSize: fontSize.xs,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginTop: spacing.md,
    marginBottom: spacing.xs,
  },
  subHeader: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    marginBottom: spacing.xs,
  },
  readingRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  readingRowMissing: {
    backgroundColor: "#FEF2F2",
    borderRadius: radius.sm,
    paddingHorizontal: 6,
  },
  readingLabel: {
    flex: 1,
    flexDirection: "row",
    alignItems: "baseline",
    gap: 4,
  },
  readingName: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  readingUnit: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
  },
  readingInput: {
    width: 80,
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    textAlign: "right",
    paddingVertical: 4,
    paddingHorizontal: 8,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
  },
  readingInputMissing: {
    borderColor: colors.error,
    borderWidth: 1.5,
  },
  notesInput: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    padding: spacing.sm,
    minHeight: 60,
    textAlignVertical: "top",
  },
});
