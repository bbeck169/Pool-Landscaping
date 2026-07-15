/**
 * Phase 37 · ChemicalDropdownStack (mobile).
 *
 * Mirror of the web ChemicalDropdownStack — 9 collapsible chemical
 * rows. See `/app/frontend/src/components/checklist/ChemicalDropdownStack.jsx`
 * for the canonical behaviour spec; both platforms share the same
 * `CHEM_TYPES` config, backend contract, and testid conventions.
 */
import React, { useState } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font } from "@/src/theme";

type ChemOption = { label: string; quantity: number };
type ChemType = {
  slug: string;
  name: string;
  aliases?: string[];
  noOptionLabel: string;
  sectionLabel?: string;
  unit: string;
  options: ChemOption[];
};

const gallons: ChemOption[] = [
  { label: "1/8 Gallon",  quantity: 0.125 },
  { label: "1/4 Gallon",  quantity: 0.25 },
  { label: "1/3 Gallon",  quantity: 0.333 },
  { label: "1/2 Gallon",  quantity: 0.5 },
  { label: "2/3 Gallon",  quantity: 0.667 },
  { label: "3/4 Gallon",  quantity: 0.75 },
  { label: "1 Gallon",    quantity: 1 },
  { label: "1.5 Gallons", quantity: 1.5 },
  { label: "2 Gallons",   quantity: 2 },
];
const ounces: ChemOption[] = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20].map((n) => ({
  label: `${n} Ounces`, quantity: n,
}));
const tabs: ChemOption[] = Array.from({ length: 10 }, (_, i) => {
  const n = i + 1; return { label: `${n} Tab${n > 1 ? "s" : ""}`, quantity: n };
});
const calhypoPounds: ChemOption[] = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6].map((n) => ({
  label: n === 0.5 ? "1/2 Pound" : `${n} Pound${n > 1 ? "s" : ""}`,
  quantity: n,
}));
const saltBags: ChemOption[] = Array.from({ length: 10 }, (_, i) => {
  const n = i + 1; return { label: `${n} bag${n > 1 ? "s" : ""} of Salt`, quantity: n };
});

export const CHEM_TYPES: ChemType[] = [
  { slug: "chlorine-tablets", name: "Chlorine Tablets", aliases: ["3 inch tabs", "chlorine tabs"],
    noOptionLabel: "No Tabs Used", sectionLabel: "~ 3 Inch tabs ~", unit: "tabs", options: tabs },
  { slug: "liquid-chlorine", name: "Liquid Chlorine", aliases: ["chlorine liquid", "sodium hypochlorite"],
    noOptionLabel: "No Liquid Chlorine Used", unit: "gal", options: gallons },
  { slug: "liquid-acid", name: "Liquid Acid (Muriatic)", aliases: ["muriatic acid", "hydrochloric acid"],
    noOptionLabel: "No Liquid Acid Used", unit: "gal", options: gallons },
  { slug: "calhypo-shock", name: "CalHypo Shock", aliases: ["calcium hypochlorite", "shock", "cal-hypo"],
    noOptionLabel: "No Calhypo Added", unit: "lbs", options: calhypoPounds },
  { slug: "clarifier", name: "Clarifier", aliases: ["pool clarifier"],
    noOptionLabel: "No clarifier added", sectionLabel: "~ Ounces Measurement ~", unit: "oz", options: ounces },
  { slug: "phosphate-remover", name: "Phosphate Remover", aliases: ["phos remover", "phosfree"],
    noOptionLabel: "No Phosphate Remover Added", unit: "oz", options: ounces },
  { slug: "salt", name: "Salt", aliases: ["pool salt", "sodium chloride"],
    noOptionLabel: "No Salt Added", sectionLabel: "~ Salt ~", unit: "bags", options: saltBags },
  { slug: "pool-enzymes", name: "Pool Enzymes", aliases: ["enzymes", "enzyme"],
    noOptionLabel: "No Pool Enzymes Added", unit: "oz", options: ounces },
  { slug: "algaecide", name: "Algaecide", aliases: ["algicide", "polyquat"],
    noOptionLabel: "No Algaecide Added", unit: "oz", options: ounces },
];

const slugifyOption = (label: string) =>
  String(label).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

type ChemAdded = {
  chemical?: string;
  name?: string;
  quantity?: number | string;
  amount?: number | string;
  unit?: string;
  raw_label?: string;
  source?: string;
  reading_key?: string;
  snapped_from?: number;
  id?: string;
};

const findEntry = (chemicalsAdded: ChemAdded[], type: ChemType) => {
  const target = type.name.toLowerCase();
  return chemicalsAdded.find(
    (c) => String(c?.chemical || c?.name || "").toLowerCase() === target
  );
};

export function snapRecommendationToPreset(chemicalName: string, quantity: number) {
  const target = String(chemicalName || "").toLowerCase();
  const type = CHEM_TYPES.find((t) => {
    if (t.name.toLowerCase() === target) return true;
    return (t.aliases || []).some((a) => a.toLowerCase() === target);
  });
  if (!type) return null;
  let closest = type.options[0];
  let diff = Math.abs(Number(closest.quantity) - Number(quantity));
  for (const o of type.options) {
    const d = Math.abs(Number(o.quantity) - Number(quantity));
    if (d < diff) { diff = d; closest = o; }
  }
  return { type, option: closest, snappedFrom: Number(quantity) };
}

export type ChemicalDropdownStackProps = {
  chemicalsAdded: ChemAdded[];
  locked?: boolean;
  onChange: (patch: { chemicals_added: ChemAdded[] }) => void;
};

export default function ChemicalDropdownStack({
  chemicalsAdded = [],
  locked = false,
  onChange,
}: ChemicalDropdownStackProps) {
  const [openSlug, setOpenSlug] = useState<string | null>(null);

  const upsert = (type: ChemType, option: ChemOption | null) => {
    const existingIdx = chemicalsAdded.findIndex(
      (c) => String(c?.chemical || c?.name || "").toLowerCase() === type.name.toLowerCase()
    );
    const next = [...chemicalsAdded];
    if (option === null) {
      if (existingIdx >= 0) next.splice(existingIdx, 1);
    } else {
      const entry: ChemAdded = {
        chemical: type.name,
        name: type.name,
        quantity: option.quantity,
        amount: String(option.quantity),
        unit: type.unit,
        raw_label: option.label,
      };
      if (existingIdx >= 0) next[existingIdx] = { ...next[existingIdx], ...entry };
      else next.push(entry);
    }
    onChange({ chemicals_added: next });
  };

  return (
    <View testID="chemicals-stack" style={styles.stack}>
      {CHEM_TYPES.map((type) => {
        const entry = findEntry(chemicalsAdded, type);
        const isOpen = openSlug === type.slug;
        const currentLabel = entry?.raw_label
          || (entry?.quantity != null ? `${entry.quantity} ${type.unit}` : null);
        const snappedFromLabel = entry?.snapped_from != null && entry?.snapped_from !== entry?.quantity
          ? `Snapped from ${entry.snapped_from} ${type.unit}` : null;

        return (
          <View
            key={type.slug}
            testID={`chemicals-row-${type.slug}`}
            style={styles.row}
          >
            <Pressable
              onPress={() => setOpenSlug(isOpen ? null : type.slug)}
              disabled={locked}
              testID={`chemicals-row-${type.slug}-header`}
              style={[styles.header, entry && styles.headerActive]}
            >
              <View style={{ flex: 1 }}>
                <Text style={[styles.headerName, entry && styles.headerNameActive]}>
                  {type.name}
                </Text>
                <Text
                  style={[styles.headerCurrent, entry && styles.headerCurrentActive]}
                  testID={`chemicals-row-${type.slug}-current`}
                >
                  {currentLabel || type.noOptionLabel}
                </Text>
                {snappedFromLabel ? (
                  <Text style={styles.snappedNote}>{snappedFromLabel}</Text>
                ) : null}
              </View>
              <Ionicons
                name={isOpen ? "chevron-down" : "chevron-forward"}
                size={16}
                color={colors.muted}
              />
            </Pressable>

            {isOpen ? (
              <View style={styles.body}>
                {type.sectionLabel ? (
                  <Text style={styles.sectionLabel}>{type.sectionLabel}</Text>
                ) : null}
                <Pressable
                  onPress={() => upsert(type, null)}
                  testID={`chemicals-row-${type.slug}-option-none`}
                  style={[styles.option, !entry && styles.optionSelected]}
                >
                  <Text style={[styles.optionText, !entry && styles.optionTextSelected]}>
                    {type.noOptionLabel}
                  </Text>
                </Pressable>
                <View style={styles.optionsGrid}>
                  {type.options.map((o) => {
                    const optSlug = slugifyOption(o.label);
                    const isSel = !!entry
                      && Math.abs(Number(entry.quantity) - Number(o.quantity)) < 0.001;
                    return (
                      <Pressable
                        key={optSlug}
                        onPress={() => upsert(type, o)}
                        testID={`chemicals-row-${type.slug}-option-${optSlug}`}
                        style={[styles.chip, isSel && styles.chipSelected]}
                      >
                        <Text style={[styles.chipText, isSel && styles.chipTextSelected]}>
                          {o.label}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ) : null}
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { gap: spacing.sm },
  row: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    overflow: "hidden",
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.surface,
  },
  headerActive: { backgroundColor: "#D1FAE5" },
  headerName: {
    fontFamily: font.bold,
    fontSize: 13,
    color: colors.onSurface,
  },
  headerNameActive: { color: "#059669" },
  headerCurrent: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 2,
  },
  headerCurrentActive: { color: "#059669", fontFamily: font.semibold },
  snappedNote: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
    fontStyle: "italic",
    marginTop: 2,
  },
  body: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  sectionLabel: {
    textAlign: "center",
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
    fontStyle: "italic",
    paddingVertical: 4,
    marginBottom: 4,
  },
  option: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    backgroundColor: "#F1F5F9",
    marginBottom: 6,
  },
  optionSelected: {
    backgroundColor: "#DBEAFE",
    borderWidth: 2,
    borderColor: colors.brand,
  },
  optionText: {
    fontFamily: font.semibold,
    fontSize: 12,
    color: colors.onSurface,
  },
  optionTextSelected: { color: "#1E3A8A" },
  optionsGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  chip: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 8,
    borderRadius: radius.sm,
    backgroundColor: "#F1F5F9",
    borderWidth: 1,
    borderColor: "transparent",
    minWidth: "31%",
    alignItems: "center",
  },
  chipSelected: {
    backgroundColor: "#DBEAFE",
    borderWidth: 2,
    borderColor: colors.brand,
  },
  chipText: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: colors.onSurface,
  },
  chipTextSelected: { color: "#1E3A8A" },
});
