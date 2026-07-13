import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, TextInput, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";

export default function Forms() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", fields: "name, email, phone" });

  const load = useCallback(async () => {
    try {
      setItems(await api.get("/forms"));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const create = async () => {
    if (!form.name.trim()) { Alert.alert("Missing", "Enter a form name."); return; }
    const fields = form.fields.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      await api.post("/forms", { name: form.name, description: form.description, fields });
      setAddOpen(false);
      setForm({ name: "", description: "", fields: "name, email, phone" });
      load();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Could not create form.");
    }
  };

  return (
    <View style={styles.root}>
      <Header title="Form Builder" back subtitle="Lead-capture forms" right={<IconButton icon="add" onPress={() => setAddOpen(true)} testID="add-form-button" />} />
      {loading ? (
        <Loading testID="forms-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="documents-outline" title="No forms" subtitle="Build a form to capture website leads." testID="forms-empty" />
      ) : (
        <FlatList
          testID="forms-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`form-${item.id}`}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                <View style={styles.icon}>
                  <Ionicons name="document-text-outline" size={18} color={colors.brand} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.name}>{item.name}</Text>
                  {item.description ? <Text style={styles.sub}>{item.description}</Text> : null}
                </View>
                <View style={styles.subsPill}>
                  <Text style={styles.subsValue}>{item.submissions}</Text>
                  <Text style={styles.subsLabel}>leads</Text>
                </View>
              </View>
              <View style={styles.fieldsRow}>
                {(item.fields || []).map((f: string) => (
                  <View key={f} style={styles.fieldChip}>
                    <Text style={styles.fieldText}>{f}</Text>
                  </View>
                ))}
              </View>
            </View>
          )}
        />
      )}

      <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="New Form" testID="add-form-sheet">
        <Text style={styles.inputLabel}>NAME</Text>
        <TextInput style={styles.input} value={form.name} onChangeText={(v) => setForm((f) => ({ ...f, name: v }))} placeholder="e.g. Free Pool Estimate" placeholderTextColor={colors.muted} testID="form-name-input" />
        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>DESCRIPTION</Text>
        <TextInput style={styles.input} value={form.description} onChangeText={(v) => setForm((f) => ({ ...f, description: v }))} placeholder="Where this form lives" placeholderTextColor={colors.muted} testID="form-desc-input" />
        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>FIELDS (comma separated)</Text>
        <TextInput style={styles.input} value={form.fields} onChangeText={(v) => setForm((f) => ({ ...f, fields: v }))} placeholder="name, email, phone" placeholderTextColor={colors.muted} testID="form-fields-input" />
        <View style={{ height: spacing.md }} />
        <PrimaryButton title="Create Form" onPress={create} testID="save-form-button" />
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  icon: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  subsPill: { alignItems: "center", backgroundColor: colors.brandTertiary, borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 6 },
  subsValue: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand },
  subsLabel: { fontFamily: font.medium, fontSize: 10, color: colors.brand },
  fieldsRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginTop: spacing.md },
  fieldChip: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 4, borderWidth: 1, borderColor: colors.border },
  fieldText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
});
