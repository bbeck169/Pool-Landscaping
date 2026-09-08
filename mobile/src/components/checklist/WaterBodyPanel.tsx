/**
 * Phase v · WaterBodyPanel — per-body card component.
 *
 * Renders chemistry inputs (filtered by type allow-list), a chemicals
 * section, notes, and a remove button. One card per body of water.
 */
import React, { useMemo } from "react";
import {
  View, Text, TextInput, Pressable, StyleSheet, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import {
  WaterBody, BODY_TYPE_LABELS, BODY_TYPE_TINTS,
  READING_ALLOWLIST, READING_LABELS, READING_REQUIRED,
  CHEMICAL_ALLOWLIST, CHEMICAL_LABELS,
} from "@/src/lib/waterBodies";

interface Props {
  body: WaterBody;
  index: number;
  locked: boolean;
  canRemove: boolean;
  highlightMissing?: string[];
  onChange: (updated: WaterBody) => void;
  onRemove: () => void;
}

export default function WaterBodyPanel({
  body, index, locked, canRemove, highlightMissing, onChange, onRemove,
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
  const allowedChemicals = useMemo(
    () => CHEMICAL_ALLOWLIST[body.type] || CHEMICAL_ALLOWLIST.pool,
    [body.type],
  );

  const readingsByKey = useMemo(() => {
    const map = new Map<string, any>();
    for (const r of body.readings || []) {
      if (r?.key) map.set(r.key, r);
    }
    return map;
  }, [body.readings]);

  const setReading = (key: string, value: string) => {
    const next = [...(body.readings || [])];
    const idx = next.findIndex((r) => r.key === key);
    const meta = READING_LABELS[key] || { name: key, unit: "ppm" };
    if (idx >= 0) {
      next[idx] = { ...next[idx], value: value || null };
    } else {
      next.push({ key, name: meta.name, value: value || null, unit: meta.unit });
    }
    onChange({ ...body, readings: next });
  };

  const setLabel = (label: string) => onChange({ ...body, label });
  const setNotes = (notes: string) => onChange({ ...body, notes });

  /* chemicals_used — add / update / remove */
  const addChemical = (slug: string) => {
    const meta = CHEMICAL_LABELS[slug] || { name: slug, unit: "oz" };
    const next = [...(body.chemicals_used || []), { product_slug: slug, amount: 0, unit: meta.unit, product_name: meta.name }];
    onChange({ ...body, chemicals_used: next });
  };
  const updateChemical = (idx: number, amount: string) => {
    const next = [...(body.chemicals_used || [])];
    next[idx] = { ...next[idx], amount: amount || 0 };
    onChange({ ...body, chemicals_used: next });
  };
  const removeChemical = (idx: number) => {
    const next = (body.chemicals_used || []).filter((_: any, i: number) => i !== idx);
    onChange({ ...body, chemicals_used: next });
  };

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

  /* already-added slugs for the "add chemical" dropdown */
  const addedSlugs = new Set((body.chemicals_used || []).map((c: any) => c.product_slug));
  const availableChemicals = allowedChemicals.filter((s) => !addedSlugs.has(s));

  return (
    <View style={[s.card, { borderColor: tint.border }]} testID={`water-body-panel-${index}`}>
      {/* Header row */}
      <View style={s.headerRow}>
        <View style={[s.typeBadge, { backgroundColor: tint.bg }]}>
          <Text style={[s.typeBadgeText, { color: tint.fg }]} testID={`water-body-type-badge-${index}`}>
            {BODY_TYPE_LABELS[body.type] || body.type}
          </Text>
        </View>
        <TextInput
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

      {/* Chemistry readings */}
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
            <TextInput
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

      {/* Chemicals used */}
      <Text style={s.sectionLabel}>Chemicals Used</Text>
      {(body.chemicals_used || []).map((chem: any, ci: number) => {
        const meta = CHEMICAL_LABELS[chem.product_slug] || { name: chem.product_name || chem.product_slug, unit: chem.unit };
        return (
          <View key={`${chem.product_slug}-${ci}`} style={s.chemRow} testID={`chem-row-${index}-${ci}`}>
            <Text style={s.chemName}>{meta.name}</Text>
            <TextInput
              style={s.chemInput}
              value={chem.amount != null ? String(chem.amount) : ""}
              onChangeText={(v) => updateChemical(ci, v)}
              keyboardType="decimal-pad"
              editable={!locked}
              placeholder="0"
              placeholderTextColor={colors.muted}
              testID={`chem-amount-${index}-${ci}`}
            />
            <Text style={s.chemUnit}>{meta.unit}</Text>
            {!locked ? (
              <Pressable onPress={() => removeChemical(ci)} hitSlop={8} testID={`chem-remove-${index}-${ci}`}>
                <Ionicons name="close-outline" size={16} color={colors.error} />
              </Pressable>
            ) : null}
          </View>
        );
      })}
      {!locked && availableChemicals.length > 0 ? (
        <Pressable
          style={s.addChemBtn}
          onPress={() => addChemical(availableChemicals[0])}
          testID={`add-chemical-${index}`}
        >
          <Ionicons name="add-outline" size={14} color={colors.brand} />
          <Text style={s.addChemText}>Add chemical</Text>
        </Pressable>
      ) : null}

      {/* Notes */}
      <Text style={s.sectionLabel}>Notes</Text>
      <TextInput
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
  chemRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  chemName: {
    flex: 1,
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  chemInput: {
    width: 60,
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    textAlign: "right",
    paddingVertical: 4,
    paddingHorizontal: 6,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    color: colors.onSurface,
  },
  chemUnit: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    width: 50,
  },
  addChemBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingVertical: 8,
  },
  addChemText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.brand,
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
