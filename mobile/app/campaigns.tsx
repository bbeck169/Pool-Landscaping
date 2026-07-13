import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, TextInput, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState, PrimaryButton, Sheet } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";

function relTime(iso?: string) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch { return ""; }
}

export default function Campaigns() {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ channel: "email", subject: "", body: "" });

  const load = useCallback(async () => {
    try {
      setItems(await api.get("/campaigns"));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const send = async () => {
    if (!form.subject.trim()) { Alert.alert("Missing", "Enter a subject."); return; }
    try {
      const res = await api.post("/campaigns", { ...form, audience: "all_customers" });
      setAddOpen(false);
      setForm({ channel: "email", subject: "", body: "" });
      Alert.alert("Campaign sent", `Delivered to ${res.sent_count} customer${res.sent_count === 1 ? "" : "s"}.`);
      load();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Could not send.");
    }
  };

  return (
    <View style={styles.root}>
      <Header title="Communication" back subtitle="Email & SMS campaigns" right={<IconButton icon="add" onPress={() => setAddOpen(true)} testID="add-campaign-button" />} />
      {loading ? (
        <Loading testID="campaigns-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="megaphone-outline" title="No campaigns" subtitle="Reach your customers with a blast." testID="campaigns-empty" />
      ) : (
        <FlatList
          testID="campaigns-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`campaign-${item.id}`}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                <View style={[styles.icon, { backgroundColor: item.channel === "sms" ? "#DCFCE7" : colors.brandTertiary }]}>
                  <Ionicons name={item.channel === "sms" ? "chatbubble-ellipses-outline" : "mail-outline"} size={18} color={item.channel === "sms" ? colors.success : colors.brand} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.subject} numberOfLines={1}>{item.subject}</Text>
                  <Text style={styles.meta}>{item.channel.toUpperCase()} · {relTime(item.sent_at)}</Text>
                </View>
                <View style={styles.sentPill}>
                  <Ionicons name="paper-plane" size={12} color={colors.brand} />
                  <Text style={styles.sentText}>{item.sent_count}</Text>
                </View>
              </View>
              {item.body ? <Text style={styles.body} numberOfLines={2}>{item.body}</Text> : null}
            </View>
          )}
        />
      )}

      <Sheet visible={addOpen} onClose={() => setAddOpen(false)} title="New Campaign" testID="add-campaign-sheet">
        <Text style={styles.inputLabel}>CHANNEL</Text>
        <View style={styles.pickerWrap}>
          {["email", "sms"].map((ch) => (
            <Pressable key={ch} style={[styles.pickChip, form.channel === ch && styles.pickChipActive]} onPress={() => setForm((f) => ({ ...f, channel: ch }))} testID={`campaign-channel-${ch}`}>
              <Text style={[styles.pickChipText, form.channel === ch && { color: "#fff" }]}>{ch.toUpperCase()}</Text>
            </Pressable>
          ))}
        </View>
        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>SUBJECT</Text>
        <TextInput style={styles.input} value={form.subject} onChangeText={(v) => setForm((f) => ({ ...f, subject: v }))} placeholder="Summer special…" placeholderTextColor={colors.muted} testID="campaign-subject-input" />
        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>MESSAGE</Text>
        <TextInput style={[styles.input, { height: 96, paddingTop: spacing.sm }]} value={form.body} onChangeText={(v) => setForm((f) => ({ ...f, body: v }))} placeholder="Write your message…" placeholderTextColor={colors.muted} multiline testID="campaign-body-input" />
        <View style={{ height: spacing.md }} />
        <PrimaryButton title="Send Campaign" icon="paper-plane-outline" onPress={send} testID="send-campaign-button" />
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  icon: { width: 40, height: 40, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  subject: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  sentPill: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brandTertiary, paddingHorizontal: 10, paddingVertical: 5, borderRadius: radius.pill },
  sentText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.brand },
  body: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, marginTop: spacing.sm },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  pickerWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  pickChip: { paddingHorizontal: spacing.lg, height: 36, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  pickChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  pickChipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
});
