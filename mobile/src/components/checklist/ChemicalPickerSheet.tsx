/**
 * Phase 45 · Task 5 — Chemicals Added with manual text entry.
 *
 * Replaces the stepper-only Quick-add sheet with a manual numeric input
 * per chemical driven by the shared `CHEMICALS_CATALOG`. Steppers are
 * retained as convenience buttons alongside the text input.
 *
 * Persistence semantics unchanged from Phase 31 · Step 2c:
 *   commit() → onChange({chemicals_added}) → parent autosave (1500ms
 *   debounce) → PATCH /jobs/{id}/service-report with X-Idempotency-Key.
 * The stale-closure fix in `checklist.tsx` (reportRef) guarantees the
 * autosave PATCHes the freshest state.
 */
import React, { useRef, useState } from "react";
import {
  View, Text, Modal, Pressable, StyleSheet, ScrollView, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import {
  CHEMICALS_CATALOG,
  CHEMICAL_BY_SLUG,
  normalizeChemQty,
  type ChemCatalogEntry,
} from "@/src/config/chemicalsCatalog";
import AppTextInput from "@/src/components/ui/AppTextInput";

type ChemAdded = {
  slug?: string; chemical?: string; name?: string;
  quantity?: number | null;
  amount?: number | string;
  unit?: string;
  raw_label?: string;
};

type Props = {
  visible: boolean;
  onClose: () => void;
  chemicalsAdded: ChemAdded[];
  onChange: (patch: { chemicals_added: ChemAdded[] }) => void;
  locked?: boolean;
};

export default function ChemicalPickerSheet({
  visible, onClose, chemicalsAdded, onChange, locked,
}: Props) {
  const insets = useSafeAreaInsets();
  const draftsRef = useRef<Record<string, string>>({});
  const [, forceRerender] = useState(0);

  const findExisting = (slug: string) =>
    chemicalsAdded.find((c) => c?.slug === slug || String(c?.name || c?.chemical || "").toLowerCase() === CHEMICAL_BY_SLUG[slug]?.name.toLowerCase());

  const commit = (entry: ChemCatalogEntry, rawText: string) => {
    if (locked) return;
    const qty = normalizeChemQty(entry, rawText);
    const existingIdx = chemicalsAdded.findIndex(
      (c) => c?.slug === entry.slug || String(c?.name || c?.chemical || "").toLowerCase() === entry.name.toLowerCase(),
    );
    const next = [...chemicalsAdded];
    if (qty == null || qty === 0) {
      // Empty / zero → remove the entry so cleared inputs actually
      // clear the chemicals_added list rather than persisting 0.
      if (existingIdx >= 0) next.splice(existingIdx, 1);
    } else {
      const row: ChemAdded = {
        slug: entry.slug,
        chemical: entry.name, name: entry.name,
        quantity: qty, amount: String(qty),
        unit: entry.unit,
        raw_label: `${qty} ${entry.unit}`,
      };
      if (existingIdx >= 0) next[existingIdx] = { ...next[existingIdx], ...row };
      else next.push(row);
    }
    try { onChange({ chemicals_added: next }); } catch { /* defensive */ }
    delete draftsRef.current[entry.slug];
    forceRerender((n) => n + 1);
  };

  const closeSheet = () => {
    try { draftsRef.current = {}; onClose(); }
    catch (e) { if (console && console.warn) console.warn("[ChemicalPickerSheet]", e); }
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      onRequestClose={closeSheet}
    >
      <Pressable
        style={styles.backdrop}
        onPress={closeSheet}
        testID="chem-picker-sheet-backdrop"
      />
      <View
        style={[styles.sheet, { paddingBottom: insets.bottom + spacing.md }]}
        testID="chem-picker-sheet"
        onStartShouldSetResponder={() => true}
      >
        <View style={styles.grabber} />
        <View style={styles.header}>
          <Text style={styles.title}>Chemicals Added</Text>
          <Pressable
            onPress={closeSheet}
            hitSlop={10}
            testID="chem-picker-sheet-close"
            accessibilityLabel="Close chemical picker"
          >
            <Ionicons name="close" size={22} color={colors.onSurface} />
          </Pressable>
        </View>

        <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.sm }}>
          {CHEMICALS_CATALOG.map((entry) => {
            const existing = findExisting(entry.slug);
            const seed = existing?.quantity != null ? String(existing.quantity) : "";
            const draft = draftsRef.current[entry.slug] ?? seed;
            const invalid = draft.trim() !== "" && normalizeChemQty(entry, draft) == null;
            return (
              <View
                key={entry.slug}
                style={[styles.row, invalid && styles.rowInvalid]}
                testID={`chem-row-${entry.slug}`}
              >
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.name}>{entry.name}</Text>
                  <Text style={styles.unit}>{entry.unit}</Text>
                </View>
                <AppTextInput
                  value={draft}
                  onChangeText={(t) => {
                    // Digits + optional decimal for decimal units; digits
                    // only for integer units.
                    const clean = entry.unit_kind === "integer"
                      ? t.replace(/[^0-9]/g, "")
                      : t.replace(/[^0-9.]/g, "");
                    draftsRef.current[entry.slug] = clean;
                    forceRerender((n) => n + 1);
                  }}
                  onBlur={() => commit(entry, draftsRef.current[entry.slug] ?? "")}
                  onSubmitEditing={() => commit(entry, draftsRef.current[entry.slug] ?? "")}
                  keyboardType={entry.unit_kind === "integer" ? "number-pad" : "decimal-pad"}
                  placeholder="0"
                  placeholderTextColor={colors.muted}
                  style={styles.input}
                  editable={!locked}
                  testID={`chem-input-${entry.slug}`}
                />
                <Pressable
                  onPress={() => commit(entry, "")}
                  disabled={locked || !existing}
                  hitSlop={8}
                  style={[styles.clearBtn, (!existing || locked) && styles.clearBtnDisabled]}
                  testID={`chem-clear-${entry.slug}`}
                  accessibilityLabel={`Clear ${entry.name}`}
                >
                  <Ionicons name="close-circle" size={18}
                             color={existing ? colors.error : colors.muted} />
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
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.45)" },
  sheet: {
    position: "absolute", left: 0, right: 0, bottom: 0, maxHeight: "85%",
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
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
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: spacing.sm, paddingHorizontal: spacing.md,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  rowInvalid: { borderColor: colors.error },
  name: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  unit: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  input: {
    minWidth: 84,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.sm, paddingVertical: 8,
    textAlign: "right",
    fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  clearBtn: { padding: 6 },
  clearBtnDisabled: { opacity: 0.3 },
});
