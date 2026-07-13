import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, TextInput, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { ImportExport } from "@/src/components/ImportExport";

export default function PriceBook() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ name: "", category: "Service", unit: "each", unit_price: "" });

  const load = useCallback(async () => {
    try {
      setItems(await api.get("/items"));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const create = async () => {
    if (!form.name.trim()) return;
    await api.post("/items", { ...form, unit_price: parseFloat(form.unit_price) || 0 });
    setAddOpen(false);
    setForm({ name: "", category: "Service", unit: "each", unit_price: "" });
    load();
  };

  const remove = async (iid: string) => {
    await api.del(`/items/${iid}`);
    load();
  };

  return (
    <View style={styles.root}>
      <Header title="Price Book" back subtitle="Services, parts & chemicals" right={
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
          <ImportExport entity="items" label="items" exportPath="/export/items" importPath="/import/items" onDone={load} />
          <IconButton icon="add" onPress={() => setAddOpen(true)} testID="add-item-button" />
        </View>
      } />
      {loading ? (
        <Loading testID="items-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="pricetags-outline" title="No items" subtitle="Add services and parts to your catalog." testID="items-empty" />
      ) : (
        <FlatList
          testID="items-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <View style={styles.row} testID={`item-${item.id}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.name}</Text>
                <Text style={styles.sub}>{item.category} · per {item.unit}</Text>
              </View>
              <Text style={styles.price}>{money(item.unit_price)}</Text>
              <Pressable onPress={() => remove(item.id)} hitSlop={8} testID={`delete-item-${item.id}`} style={{ marginLeft: spacing.md }}>
                <Ionicons name="trash-outline" size={18} color={colors.error} />
              </Pressable>
            </View>
          )}
        />
      )}

      <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="New Item" testID="add-item-sheet">
        {[["name", "Name *", "default"], ["category", "Category", "default"], ["unit", "Unit (each, hour…)", "default"], ["unit_price", "Unit Price ($)", "decimal-pad"]].map(([k, lbl, kt]) => (
          <View key={k as string} style={{ marginBottom: spacing.sm }}>
            <Text style={styles.inputLabel}>{lbl}</Text>
            <TextInput
              testID={`item-${k}-input`}
              style={styles.input}
              value={(form as any)[k as string]}
              onChangeText={(v) => setForm((f) => ({ ...f, [k as string]: v }))}
              keyboardType={kt as any}
              placeholderTextColor={colors.muted}
            />
          </View>
        ))}
        <View style={{ height: spacing.sm }} />
        <PrimaryButton title="Add Item" onPress={create} testID="save-item-button" />
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  price: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
});
