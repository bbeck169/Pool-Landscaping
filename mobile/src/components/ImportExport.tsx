import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { Sheet } from "@/src/components/ui";
import { IconButton } from "@/src/components/widgets";
import { colors, spacing, font, fontSize } from "@/src/theme";
import { exportCsv, importCsv } from "@/src/utils/csvIO";

const COLS: Record<string, string> = {
  customers: "name, email, phone, address, billing_address, gate_code, notes",
  items: "name, category, unit, unit_price, taxable",
};

export function ImportExport({
  entity,
  label,
  exportPath,
  importPath,
  onDone,
}: {
  entity: "customers" | "items";
  label: string;
  exportPath: string;
  importPath: string;
  onDone?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<"export" | "import" | null>(null);

  const doExport = async () => {
    setBusy("export");
    try {
      const r = await exportCsv(exportPath);
      setOpen(false);
      Alert.alert("Exported", `${r.count} ${label} exported to CSV.`);
    } catch (e: any) {
      Alert.alert("Export failed", e?.message || "Please try again.");
    } finally {
      setBusy(null);
    }
  };

  const doImport = async () => {
    setBusy("import");
    try {
      const r = await importCsv(importPath);
      if (r) {
        setOpen(false);
        const extra = r.skipped ? `, skipped ${r.skipped}` : "";
        Alert.alert("Import complete", `Added ${r.created}, updated ${r.updated}${extra}.` + (r.errors?.length ? `\n\nFirst issues:\n${r.errors.slice(0, 3).join("\n")}` : ""));
        onDone?.();
      }
    } catch (e: any) {
      Alert.alert("Import failed", e?.message || "Check the file is a valid CSV.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <IconButton icon="swap-vertical-outline" onPress={() => setOpen(true)} testID={`impexp-${entity}-button`} />
      <Sheet visible={open} onClose={() => setOpen(false)} title={`Import / Export ${label}`} testID="impexp-sheet">
        <Pressable style={styles.row} onPress={doExport} disabled={!!busy} testID="impexp-export">
          <Ionicons name="download-outline" size={22} color={colors.brand} />
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Export to CSV</Text>
            <Text style={styles.sub}>Download all {label} as a spreadsheet</Text>
          </View>
          {busy === "export" ? <ActivityIndicator color={colors.brand} /> : <Ionicons name="chevron-forward" size={16} color={colors.muted} />}
        </Pressable>
        <Pressable style={styles.row} onPress={doImport} disabled={!!busy} testID="impexp-import">
          <Ionicons name="cloud-upload-outline" size={22} color={colors.brand} />
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Import from CSV</Text>
            <Text style={styles.sub}>Add or update {label} from a file</Text>
          </View>
          {busy === "import" ? <ActivityIndicator color={colors.brand} /> : <Ionicons name="chevron-forward" size={16} color={colors.muted} />}
        </Pressable>
        <Text style={styles.hint}>CSV columns: {COLS[entity]}. The first row must be the header. Existing {label} (matched by {entity === "customers" ? "email or name" : "name"}) are updated.</Text>
      </Sheet>
    </>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.md, lineHeight: 18 },
});
