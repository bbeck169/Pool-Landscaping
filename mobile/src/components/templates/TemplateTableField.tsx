import React from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Switch } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, font, fontSize, radius } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Column = { key: string; label?: string; type?: string };

export default function TemplateTableField({
  field,
  value,
  onChange,
  disabled = false,
}: {
  field: any;
  value: any;
  onChange: (v: any) => void;
  disabled?: boolean;
}) {
  const cols: Column[] = Array.isArray(field.columns) ? field.columns : [];
  const rows: Record<string, any>[] = Array.isArray(value) ? value : [];

  const setRow = (idx: number, patch: Record<string, any>) => {
    const next = rows.map((r, i) => (i === idx ? { ...r, ...patch } : r));
    onChange(next);
  };

  const addRow = () => onChange([...rows, {}]);
  const delRow = (idx: number) => onChange(rows.filter((_, i) => i !== idx));

  return (
    <View
      style={styles.container}
      testID={`template-table-${field.key}`}
    >
      {/* Header */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View>
          <View style={styles.headerRow}>
            {cols.map((c) => (
              <View key={c.key} style={styles.headerCell}>
                <Text style={styles.headerText}>{c.label || c.key}</Text>
              </View>
            ))}
            {!disabled && <View style={styles.actionCell} />}
          </View>
          {/* Rows */}
          {rows.length === 0 ? (
            <View style={styles.emptyRow}>
              <Text style={styles.emptyText}>No rows yet.</Text>
            </View>
          ) : (
            rows.map((row, ri) => (
              <View
                key={ri}
                style={styles.row}
                testID={`template-table-${field.key}-row-${ri}`}
              >
                {cols.map((c) => {
                  const ct = c.type || "text";
                  const val = row?.[c.key];
                  if (ct === "checkbox") {
                    return (
                      <View key={c.key} style={styles.dataCell}>
                        <Switch
                          value={!!val}
                          disabled={disabled}
                          onValueChange={(v) => setRow(ri, { [c.key]: v })}
                          trackColor={{ false: colors.border, true: colors.brand }}
                          testID={`template-table-${field.key}-cell-${ri}-${c.key}`}
                        />
                      </View>
                    );
                  }
                  return (
                    <View key={c.key} style={styles.dataCell}>
                      <AppTextInput
                        value={val != null ? String(val) : ""}
                        editable={!disabled}
                        onChangeText={(t) => {
                          const v = ct === "number" ? (t === "" ? "" : Number(t)) : t;
                          setRow(ri, { [c.key]: v });
                        }}
                        keyboardType={ct === "number" ? "decimal-pad" : "default"}
                        style={[
                          styles.cellInput,
                          disabled && { backgroundColor: colors.surfaceSecondary },
                        ]}
                        testID={`template-table-${field.key}-cell-${ri}-${c.key}`}
                      />
                    </View>
                  );
                })}
                {!disabled && (
                  <View style={styles.actionCell}>
                    <TouchableOpacity
                      onPress={() => delRow(ri)}
                      hitSlop={8}
                      testID={`template-table-${field.key}-del-${ri}`}
                    >
                      <Ionicons name="trash-outline" size={16} color={colors.error} />
                    </TouchableOpacity>
                  </View>
                )}
              </View>
            ))
          )}
        </View>
      </ScrollView>
      {!disabled && (
        <TouchableOpacity
          onPress={addRow}
          style={styles.addBtn}
          activeOpacity={0.7}
          testID={`template-table-${field.key}-add`}
        >
          <Ionicons name="add" size={14} color={colors.brand} />
          <Text style={styles.addText}>Add row</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  headerRow: {
    flexDirection: "row",
    backgroundColor: colors.surfaceSecondary,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerCell: {
    width: 140,
    paddingHorizontal: 8,
    paddingVertical: 8,
  },
  headerText: {
    fontSize: 10,
    fontFamily: font.bold,
    color: colors.onSurfaceSecondary,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  row: {
    flexDirection: "row",
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  dataCell: {
    width: 140,
    paddingHorizontal: 6,
    paddingVertical: 6,
    justifyContent: "center",
  },
  cellInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 6,
    fontSize: fontSize.sm,
    fontFamily: font.regular,
    color: colors.onSurface,
    backgroundColor: "#fff",
  },
  actionCell: {
    width: 40,
    justifyContent: "center",
    alignItems: "center",
  },
  emptyRow: {
    padding: 16,
    alignItems: "center",
  },
  emptyText: {
    fontSize: fontSize.sm,
    fontFamily: font.regular,
    color: colors.muted,
  },
  addBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    padding: 10,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  addText: {
    fontSize: fontSize.sm,
    fontFamily: font.bold,
    color: colors.brand,
  },
});
