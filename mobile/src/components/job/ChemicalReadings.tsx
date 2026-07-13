import React from "react";
import { View, Text, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors } from "@/src/theme";
import { styles, RATING_COLORS } from "./styles";

export default function ChemicalReadings({
  readOnly,
  report,
  readingFields,
  readings,
  idealValue,
  setReadingValue,
  openReadingPicker,
  setAllIdeal,
}: {
  readOnly: boolean;
  report: any[];
  readingFields: any[];
  readings: Record<string, string>;
  idealValue: (f: any) => string | null;
  setReadingValue: (f: any, v: string) => void;
  openReadingPicker: (f: any) => void;
  setAllIdeal: () => void;
}) {
  return (
    <>
      <View style={styles.reportHeader}>
        <Ionicons name="flask" size={18} color={colors.brand} />
        <Text style={styles.reportTitle}>Chemical Readings</Text>
        <View style={{ flex: 1 }} />
        {!readOnly ? (
          <Pressable style={styles.allIdealBtn} onPress={setAllIdeal} testID="readings-set-all-ideal">
            <Ionicons name="sparkles" size={13} color="#fff" />
            <Text style={styles.allIdealText}>All ideal</Text>
          </Pressable>
        ) : null}
      </View>
      <View style={styles.reportCard}>
        {readOnly ? (
          report.length === 0 ? (
            <Text style={styles.chemEmpty}>Readings not recorded yet.</Text>
          ) : (
            report.map((r: any) => (
              <View key={r.key} style={styles.readingRow} testID={`reading-report-${r.key}`}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.readingLabel}>{r.label}</Text>
                  <Text style={styles.readingIdeal}>{r.value}{r.unit ? ` ${r.unit}` : ""} · ideal {r.ideal}</Text>
                </View>
                <View style={[styles.ratingBadge, { backgroundColor: (RATING_COLORS[r.rating] || colors.muted) + "1A" }]}>
                  <Text style={[styles.ratingText, { color: RATING_COLORS[r.rating] || colors.muted }]}>{r.rating}</Text>
                </View>
              </View>
            ))
          )
        ) : (
          (readingFields || []).map((f: any) => {
            const idv = idealValue(f);
            return (
              <View key={f.key} style={styles.readingRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.readingLabel}>{f.label}</Text>
                  <Text style={styles.readingIdeal}>Ideal {f.ideal}{f.unit ? ` ${f.unit}` : ""}</Text>
                </View>
                {idv ? (
                  <Pressable
                    style={[styles.idealBtn, readings[f.key] === idv && styles.idealBtnOn]}
                    onPress={() => setReadingValue(f, idv)}
                    testID={`reading-ideal-${f.key}`}
                  >
                    <Ionicons name="checkmark-circle" size={13} color={readings[f.key] === idv ? "#fff" : colors.brand} />
                    <Text style={[styles.idealBtnText, readings[f.key] === idv && { color: "#fff" }]}>Ideal</Text>
                  </Pressable>
                ) : null}
                <Pressable style={styles.chemSelect} onPress={() => openReadingPicker(f)} testID={`reading-${f.key}`}>
                  <Text style={[styles.chemSelectText, !readings[f.key] && styles.chemSelectPlaceholder]}>
                    {readings[f.key] || "—"}
                  </Text>
                  <Ionicons name="chevron-down" size={15} color={colors.muted} />
                </Pressable>
              </View>
            );
          })
        )}
      </View>
    </>
  );
}
