import React from "react";
import { View, Text, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors } from "@/src/theme";
import { styles } from "./styles";

export default function ChecklistSection({
  isPool,
  readOnly,
  checklist,
  checklistToShow,
  done,
  toggleItem,
}: {
  isPool: boolean;
  readOnly: boolean;
  checklist: any[];
  checklistToShow: any[];
  done: number;
  toggleItem: (idx: number) => void;
}) {
  return (
    <>
      <View style={styles.reportHeader}>
        <Ionicons name={isPool ? "water" : "leaf"} size={18} color={colors.brand} />
        <Text style={styles.reportTitle}>
          {readOnly ? (isPool ? "Completed Pool Service" : "Completed Landscaping") : isPool ? "Pool Service Checklist" : "Landscaping Checklist"}
        </Text>
        <View style={{ flex: 1 }} />
        {!readOnly ? <Text style={styles.reportProgress}>{done}/{checklist.length}</Text> : null}
      </View>
      <View style={styles.reportCard}>
        {checklistToShow.map((c) => {
          const idx = checklist.findIndex((x) => x.id === c.id);
          return (
            <Pressable key={c.id} style={styles.checkRow} onPress={() => toggleItem(idx)} disabled={readOnly} testID={`checklist-item-${idx}`}>
              <View style={[styles.checkbox, c.done && styles.checkboxOn]}>
                {c.done ? <Ionicons name="checkmark" size={15} color="#fff" /> : null}
              </View>
              <Text style={[styles.checkLabel, c.done && styles.checkLabelDone]}>{c.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </>
  );
}
