/**
 * Templates Library — Phase 3 (Mobile) · table field.
 *
 * Mobile-ergonomic: each row is a vertical card with one labeled input
 * per column (NOT a horizontally scrolled grid). Add-row button at the
 * bottom; delete via the row's trash button or a long-press (confirmed).
 */
import React from "react";
import { View, Text, StyleSheet, TouchableOpacity, Pressable, Switch } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, font, fontSize, radius } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { showConfirm } from "@/src/components/ConfirmModal";
import { parseNumberInput } from "./fieldUtils";

type Column = { key: string; label?: string; type?: string };

function CellInput({ col, value, onChange, disabled, testID }: {
  col: Column; value: any; onChange: (v: any) => void; disabled: boolean; testID: string;
}) {
  const ct = col.type || "text";
  if (ct === "checkbox") {
    return (
      <View style={styles.checkRow}>
        <Switch
          value={!!value}
          disabled={disabled}
          onValueChange={onChange}
          trackColor={{ false: colors.border, true: colors.brand }}
          testID={testID}
        />
        <Text style={styles.cellLabelInline}>{col.label || col.key}</Text>
      </View>
    );
  }
  return (
    <View style={styles.cell}>
      <Text style={styles.cellLabel}>{col.label || col.key}</Text>
      <AppTextInput
        value={value != null ? String(value) : ""}
        editable={!disabled}
        onChangeText={(t) => onChange(ct === "number" ? parseNumberInput(t) : t)}
        keyboardType={ct === "number" ? "decimal-pad" : "default"}
        placeholder={ct === "date" ? "YYYY-MM-DD" : undefined}
        style={[styles.cellInput, disabled && styles.cellInputDisabled]}
        testID={testID}
      />
    </View>
  );
}

export default function TemplateTableField({ field, value, onChange, disabled = false }: {
  field: any; value: any; onChange: (v: any) => void; disabled?: boolean;
}) {
  const cols: Column[] = Array.isArray(field.columns) ? field.columns : [];
  const rows: Record<string, any>[] = Array.isArray(value) ? value : [];
  const base = `template-table-${field.key}`;

  const setCell = (ri: number, key: string, v: any) =>
    onChange(rows.map((r, i) => (i === ri ? { ...r, [key]: v } : r)));
  const addRow = () => onChange([...rows, {}]);
  const delRow = (ri: number) => onChange(rows.filter((_, i) => i !== ri));
  const confirmDel = (ri: number) =>
    showConfirm({
      title: `Delete row ${ri + 1}?`,
      confirmLabel: "Delete",
      confirmStyle: "destructive",
      onConfirm: () => delRow(ri),
    });

  return (
    <View style={styles.container} testID={base}>
      {rows.length === 0 ? (
        <Text style={styles.empty} testID={`${base}-empty`}>No rows yet.</Text>
      ) : (
        rows.map((row, ri) => (
          <Pressable
            key={ri}
            onLongPress={() => !disabled && confirmDel(ri)}
            delayLongPress={450}
            style={({ pressed }) => [styles.rowCard, pressed && !disabled && styles.rowPressed]}
            testID={`${base}-row-${ri}`}
          >
            <View style={styles.rowHeader}>
              <Text style={styles.rowTitle}>Row {ri + 1}</Text>
              {!disabled && (
                <TouchableOpacity onPress={() => delRow(ri)} style={styles.delBtn} testID={`${base}-del-${ri}`}>
                  <Ionicons name="trash-outline" size={18} color={colors.error} />
                </TouchableOpacity>
              )}
            </View>
            {cols.map((c) => (
              <CellInput
                key={c.key}
                col={c}
                value={row?.[c.key]}
                disabled={disabled}
                onChange={(v) => setCell(ri, c.key, v)}
                testID={`${base}-cell-${ri}-${c.key}`}
              />
            ))}
          </Pressable>
        ))
      )}
      {!disabled && (
        <TouchableOpacity onPress={addRow} style={styles.addBtn} activeOpacity={0.7} testID={`${base}-add`}>
          <Ionicons name="add-circle-outline" size={18} color={colors.brand} />
          <Text style={styles.addText}>Add row</Text>
        </TouchableOpacity>
      )}
      {!disabled && rows.length > 0 ? (
        <Text style={styles.hint}>Tip: long-press a row to delete it.</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 10 },
  empty: { fontSize: fontSize.sm, fontFamily: font.regular, color: colors.muted, paddingVertical: 8 },
  rowCard: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 12, gap: 10, backgroundColor: colors.surfaceSecondary,
  },
  rowPressed: { borderColor: colors.error, opacity: 0.85 },
  rowHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  rowTitle: {
    fontSize: 11, fontFamily: font.bold, color: colors.onSurfaceSecondary,
    textTransform: "uppercase", letterSpacing: 0.5,
  },
  delBtn: { width: 44, height: 36, alignItems: "flex-end", justifyContent: "center" },
  cell: { gap: 4 },
  cellLabel: { fontSize: 12, fontFamily: font.bold, color: colors.onSurfaceSecondary },
  cellLabelInline: { fontSize: fontSize.base, fontFamily: font.regular, color: colors.onSurface },
  checkRow: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 44 },
  cellInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: 12, paddingVertical: 10, minHeight: 44,
    fontSize: fontSize.base, fontFamily: font.regular,
  },
  cellInputDisabled: { opacity: 0.7 },
  addBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 44,
    borderWidth: 1, borderStyle: "dashed", borderColor: colors.brand, borderRadius: radius.md,
  },
  addText: { fontSize: fontSize.sm, fontFamily: font.bold, color: colors.brand },
  hint: { fontSize: 11, fontFamily: font.regular, color: colors.muted },
});
