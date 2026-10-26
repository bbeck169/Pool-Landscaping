/**
 * M2 · Lead notes card — customer-profile-style layout (ServiceNotes / notesBox).
 * Append-only by design (POST /leads/{id}/note via onSubmit); the web-written
 * `lead.notes` field is shown read-only so web-entered notes are visible on mobile.
 */
import React from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Props = {
  leadNotes?: string | null;
  timeline?: any[];
  value: string;
  onChangeText: (t: string) => void;
  onSubmit: () => void;
  busy?: boolean;
};

export default function LeadNotesCard({ leadNotes, timeline, value, onChangeText, onSubmit, busy }: Props) {
  const entries = (timeline || []).filter((e) => e?.kind === "note_added" && e?.payload?.text).reverse();
  const off = !value.trim() || !!busy;
  return (
    <View style={st.card} testID="lead-notes-card">
      <View style={st.header}>
        <Ionicons name="document-text-outline" size={18} color={colors.brand} />
        <Text style={st.title} testID="lead-notes-title">Notes ({entries.length})</Text>
      </View>
      {leadNotes ? (
        <View style={st.pinned} testID="lead-notes-field">
          <Text style={st.pinnedLabel}>Lead notes</Text>
          <Text style={st.pinnedText}>{leadNotes}</Text>
        </View>
      ) : null}
      <View style={st.composer}>
        <AppTextInput style={st.input} value={value} onChangeText={onChangeText} placeholder="Type a note…" placeholderTextColor={colors.muted} multiline testID="lead-note-input" />
        <TouchableOpacity style={[st.saveBtn, off && { opacity: 0.4 }]} onPress={onSubmit} disabled={off} testID="lead-note-submit">
          {busy ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name="send" size={14} color="#fff" />}
          <Text style={st.saveText}>Add Note</Text>
        </TouchableOpacity>
      </View>
      {entries.length === 0 ? (
        <Text style={st.empty} testID="lead-notes-empty">No notes yet.</Text>
      ) : entries.map((e, i) => (
        <View key={`${e.ts || ""}-${i}`} style={st.row} testID={`lead-note-row-${i}`}>
          <View style={st.bullet} />
          <View style={{ flex: 1 }}>
            <Text style={st.text}>{e.payload.text}</Text>
            {e.ts ? <Text style={st.date}>{new Date(e.ts).toLocaleString()}</Text> : null}
          </View>
        </View>
      ))}
    </View>
  );
}

const st = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.md },
  title: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, flex: 1 },
  pinned: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  pinnedLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, marginBottom: 4 },
  pinnedText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, lineHeight: 20 },
  composer: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  input: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, minHeight: 60, textAlignVertical: "top" },
  saveBtn: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-end", minHeight: 44, backgroundColor: colors.brand, paddingHorizontal: 16, borderRadius: radius.md, marginTop: spacing.sm },
  saveText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  empty: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  row: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.sm },
  bullet: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brand, marginTop: 6 },
  text: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 20 },
  date: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
});
