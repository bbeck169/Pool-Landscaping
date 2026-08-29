/**
 * ServiceNotes — view + add notes for customer detail (A8).
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity,
  ActivityIndicator, Alert, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/api";
import { offlineWrite } from "@/src/services/offlineWrite";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

type Props = { customerId: string };

export default function ServiceNotes({ customerId }: Props) {
  const [notes, setNotes] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [composerOpen, setComposerOpen] = useState(false);
  const [newNote, setNewNote] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.get(`/customers/${customerId}/service-notes-for-schedule`)
      .then((d) => setNotes(Array.isArray(d) ? d : []))
      .catch(() => setNotes([]))
      .finally(() => setLoading(false));
  }, [customerId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const addNote = async () => {
    if (!newNote.trim()) return;
    setSaving(true);
    try {
      const payload = {
        notes: [{ text: newNote.trim(), created_at: new Date().toISOString() }, ...notes],
      };
      await offlineWrite({
        op_type: "customer.service_notes",
        entity_id: customerId,
        endpoint: `/customers/${customerId}/service-notes`,
        method: "PATCH",
        payload,
        onlineFn: () => api.patch(`/customers/${customerId}/service-notes`, payload),
      });
      setNewNote("");
      setComposerOpen(false);
      load();
    } catch (e: any) {
      Alert.alert("Error", e.message || "Failed to save note");
    } finally {
      setSaving(false);
    }
  };

  return (
    <View testID="service-notes-list">
      <View style={styles.header}>
        <Ionicons name="document-text-outline" size={18} color={colors.brand} />
        <Text style={styles.sectionTitle}>Service Notes ({notes.length})</Text>
        <TouchableOpacity
          testID="service-note-add-btn"
          style={styles.addBtn}
          onPress={() => setComposerOpen(!composerOpen)}
        >
          <Ionicons name={composerOpen ? "close" : "add"} size={16} color={colors.brand} />
          <Text style={styles.addBtnText}>{composerOpen ? "Cancel" : "Add"}</Text>
        </TouchableOpacity>
      </View>

      {composerOpen && (
        <View style={styles.composer}>
          <TextInput
            style={styles.composerInput}
            value={newNote}
            onChangeText={setNewNote}
            placeholder="Add a service note…"
            placeholderTextColor={colors.muted}
            multiline
            numberOfLines={3}
          />
          <TouchableOpacity
            style={[styles.saveBtn, (!newNote.trim() || saving) && styles.saveBtnDisabled]}
            onPress={addNote}
            disabled={!newNote.trim() || saving}
          >
            {saving ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Text style={styles.saveBtnText}>Save</Text>
            )}
          </TouchableOpacity>
        </View>
      )}

      {loading ? (
        <ActivityIndicator style={{ paddingVertical: 12 }} color={colors.brand} />
      ) : notes.length === 0 ? (
        <Text style={styles.empty}>No service notes yet.</Text>
      ) : (
        notes.map((n: any, i: number) => (
          <View key={n.id || i} style={styles.noteRow}>
            <View style={styles.noteBullet} />
            <View style={{ flex: 1 }}>
              <Text style={styles.noteText}>{typeof n === "string" ? n : n.text || n.note || JSON.stringify(n)}</Text>
              {n.created_at && (
                <Text style={styles.noteDate}>{n.created_at.slice(0, 10)}</Text>
              )}
            </View>
          </View>
        ))
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: spacing.xl, marginBottom: spacing.md },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, flex: 1 },
  addBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brandTertiary, paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill },
  addBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  composer: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  composerInput: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, minHeight: 60, textAlignVertical: "top", ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  saveBtn: { alignSelf: "flex-end", backgroundColor: colors.brand, paddingHorizontal: 16, paddingVertical: 8, borderRadius: radius.sm, marginTop: spacing.sm },
  saveBtnDisabled: { opacity: 0.4 },
  saveBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  empty: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  noteRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.sm },
  noteBullet: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brand, marginTop: 6 },
  noteText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 20 },
  noteDate: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
});
