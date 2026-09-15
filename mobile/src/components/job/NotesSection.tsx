import React, { useState } from "react";
import { View, Text } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing } from "@/src/theme";
import { styles } from "./styles";
import AppTextInput from "@/src/components/ui/AppTextInput";

export default function NotesSection({
  job,
  readOnly,
  save,
}: {
  job: any;
  readOnly: boolean;
  save: (partial: any) => void;
}) {
  const [customerNotes, setCustomerNotes] = useState<string>(job.customer_notes || "");
  const [internalNotes, setInternalNotes] = useState<string>(job.internal_notes || "");

  if (!readOnly) {
    return (
      <>
        <View style={styles.reportHeader}>
          <Ionicons name="document-text" size={18} color={colors.brand} />
          <Text style={styles.reportTitle}>Notes</Text>
        </View>
        <View style={styles.reportCard}>
          <Text style={styles.noteFieldLabel}>Customer notes <Text style={styles.noteHint}>· shown on service report</Text></Text>
          <AppTextInput
            style={styles.noteInput}
            value={customerNotes}
            onChangeText={setCustomerNotes}
            onBlur={() => setCustomerNotes((v) => { save({ customer_notes: v }); return v; })}
            onEndEditing={() => setCustomerNotes((v) => { save({ customer_notes: v }); return v; })}
            placeholder="e.g. Water is crystal clear, replaced filter cartridge."
            placeholderTextColor={colors.muted}
            multiline
            testID="customer-notes-input"
          />
          <View style={{ height: spacing.md }} />
          <Text style={styles.noteFieldLabel}>Internal notes <Text style={styles.noteHint}>· team only, hidden from customer</Text></Text>
          <AppTextInput
            style={styles.noteInput}
            value={internalNotes}
            onChangeText={setInternalNotes}
            onBlur={() => setInternalNotes((v) => { save({ internal_notes: v }); return v; })}
            onEndEditing={() => setInternalNotes((v) => { save({ internal_notes: v }); return v; })}
            placeholder="e.g. Pump making noise, quote replacement next visit."
            placeholderTextColor={colors.muted}
            multiline
            testID="internal-notes-input"
          />
        </View>
      </>
    );
  }

  if (!job.customer_notes) return null;

  return (
    <>
      <View style={styles.reportHeader}>
        <Ionicons name="document-text" size={18} color={colors.brand} />
        <Text style={styles.reportTitle}>Service Notes</Text>
      </View>
      <View style={styles.reportCard}>
        <Text style={styles.notes} testID="customer-notes-readonly">{job.customer_notes}</Text>
      </View>
    </>
  );
}
