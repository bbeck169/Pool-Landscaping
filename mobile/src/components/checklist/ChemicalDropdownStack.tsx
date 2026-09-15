/**
 * Phase 48 · Chemicals Added — inline manual text entry (mobile).
 *
 * Mirror of the web ChemicalDropdownStack. Drops the Phase 37 preset
 * dropdown UX in favor of a plain numeric TextInput per shared
 * `CHEMICALS_CATALOG` entry. Persistence unchanged — commit fires the
 * parent onChange which flows into the autosave path.
 */
import React, { useRef, useState, useMemo } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import {
  CHEMICALS_CATALOG,
  normalizeChemQty,
  type ChemCatalogEntry,
} from "@/src/config/chemicalsCatalog";
import { CHEMICAL_ALLOWLIST } from "@/src/lib/waterBodies";
import AppTextInput from "@/src/components/ui/AppTextInput";

// Legacy CHEM_TYPES export retained for callers that still import the
// symbol (there are none in-tree today, but keeps the module surface
// stable). Each catalog entry is exposed with a mocked `options: []`
// so any older grid renderer would render an empty list instead of
// crashing.
export const CHEM_TYPES = CHEMICALS_CATALOG.map((c) => ({
  slug: c.slug, name: c.name, unit: c.unit,
  noOptionLabel: `No ${c.name} added`,
  options: [] as { label: string; quantity: number }[],
}));

// Phase 34e compat — no more presets, so pass through the raw quantity.
export function snapRecommendationToPreset(quantity: number) {
  return { quantity, snappedFrom: null };
}

type ChemAdded = {
  slug?: string; chemical?: string; name?: string;
  quantity?: number | null; amount?: number | string; unit?: string;
  raw_label?: string;
};

type Props = {
  chemicalsAdded?: ChemAdded[];
  locked?: boolean;
  onChange: (patch: { chemicals_added: ChemAdded[] }) => void;
  jobId?: string;
  /** Phase CHEM3 — filter catalog entries by body type allow-list. */
  bodyType?: string;
};

export default function ChemicalDropdownStack({
  chemicalsAdded = [], locked = false, onChange, bodyType,
}: Props) {
  const draftsRef = useRef<Record<string, string>>({});
  const [, force] = useState(0);

  // Phase CHEM3 — when bodyType is provided, only show allowed chemicals.
  const catalog = useMemo(() => {
    if (!bodyType) return CHEMICALS_CATALOG;
    const allowed = new Set(CHEMICAL_ALLOWLIST[bodyType] || CHEMICAL_ALLOWLIST.pool);
    return CHEMICALS_CATALOG.filter((c) => allowed.has(c.slug));
  }, [bodyType]);

  const findIdx = (entry: ChemCatalogEntry) =>
    chemicalsAdded.findIndex(
      (c) => c?.slug === entry.slug
        || String(c?.name || c?.chemical || "").toLowerCase() === entry.name.toLowerCase(),
    );

  const commit = (entry: ChemCatalogEntry, text: string) => {
    if (locked) return;
    const qty = normalizeChemQty(entry, text);
    const idx = findIdx(entry);
    const next = [...chemicalsAdded];
    if (qty == null || qty === 0) {
      if (idx >= 0) next.splice(idx, 1);
    } else {
      const row = {
        slug: entry.slug,
        chemical: entry.name, name: entry.name,
        quantity: qty, amount: String(qty),
        unit: entry.unit,
        raw_label: `${qty} ${entry.unit}`,
      };
      if (idx >= 0) next[idx] = { ...next[idx], ...row };
      else next.push(row);
    }
    onChange({ chemicals_added: next });
    delete draftsRef.current[entry.slug];
    force((n) => n + 1);
  };

  return (
    <View testID="chemicals-stack" style={styles.stack}>
      {catalog.map((entry) => {
        const idx = findIdx(entry);
        const existing = idx >= 0 ? chemicalsAdded[idx] : null;
        const seed = existing?.quantity != null ? String(existing.quantity) : "";
        const draft = draftsRef.current[entry.slug] ?? seed;
        const invalid = draft.trim() !== "" && normalizeChemQty(entry, draft) == null;
        const hasValue = existing?.quantity != null && Number(existing.quantity) > 0;
        return (
          <View
            key={entry.slug}
            testID={`chemicals-row-${entry.slug}`}
            style={[
              styles.row,
              hasValue && styles.rowFilled,
              invalid && styles.rowInvalid,
            ]}
          >
            <View style={styles.rowLeft}>
              <Text
                style={[styles.name, hasValue && styles.nameFilled]}
                testID={`chemicals-row-${entry.slug}-name`}
                numberOfLines={1}
              >
                {entry.name}
              </Text>
              <Text
                style={[styles.current, hasValue && styles.currentFilled]}
                testID={`chemicals-row-${entry.slug}-current`}
                numberOfLines={1}
              >
                {hasValue
                  ? `${existing.quantity} ${entry.unit}`
                  : `No ${entry.name} added`}
              </Text>
            </View>
            <AppTextInput
              testID={`chemicals-row-${entry.slug}-input`}
              keyboardType={entry.unit_kind === "integer" ? "number-pad" : "decimal-pad"}
              value={draft}
              placeholder="0"
              placeholderTextColor={colors.muted}
              editable={!locked}
              onChangeText={(t) => {
                const clean = entry.unit_kind === "integer"
                  ? t.replace(/[^0-9]/g, "")
                  : t.replace(/[^0-9.]/g, "");
                draftsRef.current[entry.slug] = clean;
                force((n) => n + 1);
              }}
              onBlur={() => commit(entry, draftsRef.current[entry.slug] ?? "")}
              onSubmitEditing={() => commit(entry, draftsRef.current[entry.slug] ?? "")}
              style={[styles.input, invalid && styles.inputInvalid,
                       locked && styles.inputDisabled]}
            />
            <Text style={styles.unit} testID={`chemicals-row-${entry.slug}-unit`}>
              {entry.unit}
            </Text>
            <Pressable
              onPress={() => commit(entry, "")}
              disabled={locked || !existing}
              hitSlop={6}
              style={styles.clearBtn}
              testID={`chemicals-row-${entry.slug}-clear`}
              accessibilityLabel={`Clear ${entry.name}`}
            >
              <Ionicons name="close"
                size={16}
                color={existing ? "#DC2626" : colors.muted} />
            </Pressable>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { gap: spacing.xs },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.sm, paddingVertical: spacing.xs,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  rowFilled: { backgroundColor: "#ECFDF5", borderColor: "#A7F3D0" },
  rowInvalid: { borderColor: "#DC2626", borderWidth: 2 },
  rowLeft: { flex: 1, minWidth: 0 },
  name: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  nameFilled: { color: "#047857" },
  current: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 1 },
  currentFilled: { color: "#047857" },
  input: {
    width: 76, textAlign: "right",
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: 8, paddingVertical: 6,
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  inputInvalid: { borderColor: "#DC2626", borderWidth: 2 },
  inputDisabled: { backgroundColor: colors.surfaceSecondary, color: colors.muted },
  unit: { fontFamily: font.semibold, fontSize: 11, color: colors.muted, minWidth: 48 },
  clearBtn: { padding: 2 },
});
