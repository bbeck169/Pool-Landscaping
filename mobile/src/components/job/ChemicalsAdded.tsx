import React from "react";
import { View, Text, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors } from "@/src/theme";
import { styles } from "./styles";

export default function ChemicalsAdded({
  readOnly,
  chemicals,
  chemicalCatalog,
  chemAmounts,
  openChemPicker,
}: {
  readOnly: boolean;
  chemicals: any[];
  chemicalCatalog: any[];
  chemAmounts: Record<string, string>;
  openChemPicker: (item: any) => void;
}) {
  return (
    <>
      <View style={styles.reportHeader}>
        <Ionicons name="beaker" size={18} color={colors.brand} />
        <Text style={styles.reportTitle}>Chemicals Added</Text>
      </View>
      <View style={styles.reportCard}>
        {readOnly ? (
          chemicals.length === 0 ? (
            <Text style={styles.chemEmpty}>No chemicals added.</Text>
          ) : (
            chemicals.map((c) => (
              <View key={c.id} style={styles.chemRow} testID={`chemical-${c.id}`}>
                <Ionicons name="water-outline" size={16} color={colors.brand} />
                <Text style={styles.chemName}>{c.name}</Text>
                <Text style={styles.chemAmt}>{c.amount}{c.unit ? ` ${c.unit}` : ""}</Text>
              </View>
            ))
          )
        ) : (chemicalCatalog || []).length === 0 ? (
          <Text style={styles.chemEmpty}>No chemicals configured.</Text>
        ) : (
          (chemicalCatalog || []).map((item: any) => (
            <View key={item.name} style={styles.chemFieldRow} testID={`chemical-field-${item.name}`}>
              <Text style={styles.chemFieldName}>{item.name}</Text>
              <Pressable style={styles.chemSelect} onPress={() => openChemPicker(item)} testID={`chemical-input-${item.name}`}>
                <Text style={[styles.chemSelectText, !chemAmounts[item.name] && styles.chemSelectPlaceholder]}>
                  {chemAmounts[item.name] || "—"}
                </Text>
                <Ionicons name="chevron-down" size={15} color={colors.muted} />
              </Pressable>
              {item.unit ? <Text style={styles.chemFieldUnit}>{item.unit}</Text> : null}
            </View>
          ))
        )}
      </View>
    </>
  );
}
