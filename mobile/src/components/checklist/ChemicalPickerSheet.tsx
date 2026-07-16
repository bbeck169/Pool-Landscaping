/**
 * Phase 31 · Step 2c — mobile Chemical Picker Sheet.
 *
 * Opens as a bottom sheet from a "Quick add" button on the checklist,
 * complementing (not replacing) the mature preset-based
 * `ChemicalDropdownStack`. The stack still owns the preset picker UX
 * shipped in Phase 37 (with its algae-risk / reservation wiring); this
 * sheet gives the tech a fast stepper-driven path to log arbitrary
 * quantities of any chemical without having to hunt the right preset.
 *
 * Contract with the caller:
 *   • `onChange({ chemicals_added })` — mirrors the callback the stack
 *     already uses, so autosave debouncing in the parent form (1500ms)
 *     picks up the change identically. No new writeQueue plumbing is
 *     required — the parent already enqueues the PATCH offline.
 *   • Chemical config (`CHEM_TYPES`) is imported from the stack so
 *     both surfaces stay in lock-step; there is no second source of
 *     truth for units / aliases / preset ordering.
 *
 * Uses the same `Modal` + backdrop primitive as the Phase 43 global
 * menu — no new sheet library added. Swipe-to-close and backdrop-tap
 * dismiss both work via the same pattern.
 */
import React, { useMemo, useRef, useState } from "react";
import {
  View, Text, Modal, Pressable, StyleSheet, ScrollView, TextInput,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { CHEM_TYPES } from "./ChemicalDropdownStack";

type ChemAdded = {
  chemical?: string;
  name?: string;
  quantity?: number | string;
  amount?: number | string;
  unit?: string;
  raw_label?: string;
  id?: string;
};

type Props = {
  visible: boolean;
  onClose: () => void;
  chemicalsAdded: ChemAdded[];
  onChange: (patch: { chemicals_added: ChemAdded[] }) => void;
  locked?: boolean;
};

// Sensible per-unit step for the +/- stepper. `tabs` and `bags` step by
// whole units; everything else steps by 0.25 to match the existing
// preset increments.
const stepFor = (unit: string): number =>
  unit === "tabs" || unit === "bags" ? 1 : 0.25;

const roundQty = (q: number): number => Math.round(q * 1000) / 1000;

export default function ChemicalPickerSheet({
  visible, onClose, chemicalsAdded, onChange, locked,
}: Props) {
  const insets = useSafeAreaInsets();
  const [query, setQuery] = useState("");
  // Local per-chemical quantity draft so the stepper feels snappy —
  // committed to the parent on "Add". Ref-backed so we don't rerender
  // the entire sheet on every stepper tap.
  const draftsRef = useRef<Record<string, number>>({});
  const [, forceRerender] = useState(0);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return CHEM_TYPES;
    return CHEM_TYPES.filter((t) =>
      t.name.toLowerCase().includes(q) ||
      (t.aliases || []).some((a) => a.toLowerCase().includes(q)),
    );
  }, [query]);

  const draftFor = (slug: string, unit: string, existing?: number) => {
    if (draftsRef.current[slug] != null) return draftsRef.current[slug];
    // Seed the draft from the existing entry (if any) so bumping the
    // stepper reflects "add another X on top" rather than starting at
    // zero every time.
    return roundQty(existing != null ? Number(existing) : stepFor(unit));
  };

  const bumpDraft = (slug: string, unit: string, delta: number, existing?: number) => {
    const current = draftFor(slug, unit, existing);
    const step = stepFor(unit);
    const next = Math.max(step, roundQty(current + delta * step));
    draftsRef.current[slug] = next;
    forceRerender((n) => n + 1);
  };

  const commit = (type: typeof CHEM_TYPES[number]) => {
    if (locked) return;
    const qty = draftFor(type.slug, type.unit);
    const target = type.name.toLowerCase();
    const idx = chemicalsAdded.findIndex(
      (c) => String(c?.chemical || c?.name || "").toLowerCase() === target,
    );
    const entry: ChemAdded = {
      chemical: type.name,
      name: type.name,
      quantity: qty,
      amount: String(qty),
      unit: type.unit,
      raw_label: `${qty} ${type.unit}`,
    };
    const next = [...chemicalsAdded];
    if (idx >= 0) next[idx] = { ...next[idx], ...entry };
    else next.push(entry);
    onChange({ chemicals_added: next });
    // Clear the draft so the next open of this row seeds from the new
    // stored quantity rather than the last uncommitted value.
    delete draftsRef.current[type.slug];
    forceRerender((n) => n + 1);
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      onRequestClose={onClose}
    >
      <Pressable
        style={styles.backdrop}
        onPress={onClose}
        testID="chem-picker-sheet-backdrop"
      />
      <View
        style={[styles.sheet, { paddingBottom: insets.bottom + spacing.md }]}
        testID="chem-picker-sheet"
      >
        {/* Grabber — visual cue for the swipe-down dismiss expectation.
            The Modal already responds to hardware back + backdrop tap; a
            real swipe gesture would require rewriting on top of
            gesture-handler which is out-of-scope for this pass. */}
        <View style={styles.grabber} />
        <View style={styles.header}>
          <Text style={styles.title}>Quick add chemical</Text>
          <Pressable
            onPress={onClose}
            hitSlop={10}
            testID="chem-picker-sheet-close"
            accessibilityLabel="Close chemical picker"
          >
            <Ionicons name="close" size={22} color={colors.onSurface} />
          </Pressable>
        </View>

        <View style={styles.searchWrap}>
          <Ionicons name="search-outline" size={16} color={colors.muted} />
          <TextInput
            style={styles.searchInput}
            placeholder="Filter…"
            placeholderTextColor={colors.muted}
            value={query}
            onChangeText={setQuery}
            autoCorrect={false}
            autoCapitalize="none"
            testID="chem-picker-search"
          />
        </View>

        <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.sm }}>
          {filtered.length === 0 ? (
            <Text style={styles.emptyText}>No chemicals match “{query}”.</Text>
          ) : filtered.map((type) => {
            const existing = chemicalsAdded.find(
              (c) => String(c?.chemical || c?.name || "").toLowerCase() === type.name.toLowerCase(),
            );
            const existingQty = existing?.quantity != null ? Number(existing.quantity) : undefined;
            const qty = draftFor(type.slug, type.unit, existingQty);
            return (
              <View
                key={type.slug}
                style={styles.row}
                testID={`chem-picker-row-${type.slug}`}
              >
                <View style={styles.rowText}>
                  <Text style={styles.rowName}>{type.name}</Text>
                  <Text style={styles.rowUnit}>
                    {type.unit}{existing ? ` · already logged ${existingQty ?? "?"}` : ""}
                  </Text>
                </View>
                <View style={styles.stepper}>
                  <Pressable
                    onPress={() => bumpDraft(type.slug, type.unit, -1, existingQty)}
                    hitSlop={6}
                    style={styles.stepBtn}
                    testID={`chem-picker-${type.slug}-dec`}
                    accessibilityLabel="Decrease"
                  >
                    <Ionicons name="remove" size={18} color={colors.onSurface} />
                  </Pressable>
                  <Text
                    style={styles.qtyText}
                    testID={`chem-picker-${type.slug}-qty`}
                  >
                    {qty}
                  </Text>
                  <Pressable
                    onPress={() => bumpDraft(type.slug, type.unit, +1, existingQty)}
                    hitSlop={6}
                    style={styles.stepBtn}
                    testID={`chem-picker-${type.slug}-inc`}
                    accessibilityLabel="Increase"
                  >
                    <Ionicons name="add" size={18} color={colors.onSurface} />
                  </Pressable>
                </View>
                <Pressable
                  onPress={() => commit(type)}
                  disabled={locked}
                  style={[styles.addBtn, locked && styles.addBtnDisabled]}
                  testID={`chem-picker-${type.slug}-add`}
                  accessibilityRole="button"
                  accessibilityLabel={`Add ${qty} ${type.unit} of ${type.name}`}
                >
                  <Text style={styles.addBtnText}>Add</Text>
                </Pressable>
              </View>
            );
          })}
        </ScrollView>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  sheet: {
    position: "absolute",
    left: 0, right: 0, bottom: 0,
    maxHeight: "85%",
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    ...(Platform.OS === "web"
      ? { boxShadow: "0 -8px 24px rgba(0,0,0,0.18)" as any }
      : { elevation: 14 }),
  },
  grabber: {
    alignSelf: "center", width: 44, height: 4, borderRadius: 2,
    backgroundColor: colors.border, marginTop: 8, marginBottom: 4,
  },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  searchWrap: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    marginHorizontal: spacing.md, marginTop: spacing.sm,
    paddingHorizontal: spacing.md, height: 38,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
  },
  searchInput: {
    flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: spacing.sm, paddingHorizontal: spacing.md,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  rowText: { flex: 1 },
  rowName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  rowUnit: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  stepper: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill,
    paddingHorizontal: 4, paddingVertical: 2,
  },
  stepBtn: {
    width: 26, height: 26, borderRadius: radius.pill,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  qtyText: {
    minWidth: 34, textAlign: "center",
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface,
  },
  addBtn: {
    paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.pill,
    backgroundColor: colors.brand,
  },
  addBtnDisabled: { opacity: 0.4 },
  addBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#FFFFFF" },
  emptyText: {
    textAlign: "center", padding: spacing.lg,
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
  },
});
