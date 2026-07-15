import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, TextInput, Platform, Pressable } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { PrimaryButton } from "@/src/components/ui";

export default function CustomerForm() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const router = useRouter();
  const editing = !!id;
  const [form, setForm] = useState({ name: "", email: "", phone: "", address: "", billing_address: "", gate_code: "", notes: "", avatar: "", pool_gallons: "", is_vip: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (id) {
      api.get(`/customers/${id}`).then((c) =>
        setForm({
          name: c.name || "", email: c.email || "", phone: c.phone || "", address: c.address || "",
          billing_address: c.billing_address || "", gate_code: c.gate_code || "", notes: c.notes || "", avatar: c.avatar || "",
          pool_gallons: c.pool_gallons == null ? "" : String(c.pool_gallons),
          is_vip: !!c.is_vip,
        })
      );
    }
  }, [id]);

  const set = (k: string) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const pickAvatar = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const res = await ImagePicker.launchImageLibraryAsync({ base64: true, quality: 0.5, allowsEditing: true, aspect: [1, 1] });
    if (res.canceled || !res.assets?.[0]?.base64) return;
    setForm((f) => ({ ...f, avatar: `data:image/jpeg;base64,${res.assets[0].base64}` }));
  };

  const save = async () => {
    if (!form.name.trim()) {
      setError("Name is required");
      return;
    }
    // Phase 34d — pool_gallons: blank → null; else must be integer 1..500000.
    let poolGallonsPayload: number | null = null;
    if (form.pool_gallons !== "" && form.pool_gallons != null) {
      const n = Number(form.pool_gallons);
      if (!Number.isInteger(n) || n < 1 || n > 500000) {
        setError("Pool volume must be a whole number between 1 and 500,000 gallons.");
        return;
      }
      poolGallonsPayload = n;
    }
    setBusy(true);
    setError("");
    try {
      const payload = { ...form, pool_gallons: poolGallonsPayload, is_vip: !!form.is_vip };
      if (editing) await api.put(`/customers/${id}`, payload);
      else await api.post("/customers", payload);
      router.back();
    } catch (e: any) {
      setError(e.message || "Failed to save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.root}>
      <Header title={editing ? "Edit Customer" : "New Customer"} back />
      <KeyboardAwareScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        bottomOffset={24}
        keyboardShouldPersistTaps="handled"
      >
        <Pressable style={styles.avatarRow} onPress={pickAvatar} testID="customer-avatar-picker">
          {form.avatar ? (
            <Image source={{ uri: form.avatar }} style={styles.avatar} />
          ) : (
            <View style={[styles.avatar, styles.avatarFallback]}>
              <Ionicons name="person" size={26} color={colors.muted} />
            </View>
          )}
          <View style={{ flex: 1 }}>
            <Text style={styles.avatarLabel}>Profile photo</Text>
            <Text style={styles.avatarHint}>{form.avatar ? "Tap to change" : "Tap to add a photo"}</Text>
          </View>
          <Ionicons name="camera-outline" size={22} color={colors.brand} />
        </Pressable>

        <Field label="Name *" value={form.name} onChangeText={set("name")} placeholder="Full name" testID="customer-name-input" />
        <Field label="Phone" value={form.phone} onChangeText={set("phone")} placeholder="480-555-0100" keyboardType="phone-pad" testID="customer-phone-input" />
        <Field label="Email" value={form.email} onChangeText={set("email")} placeholder="name@email.com" keyboardType="email-address" testID="customer-email-input" />
        <Field label="Service Address" value={form.address} onChangeText={set("address")} placeholder="Street, City, State" testID="customer-address-input" />
        <Field label="Billing Address" value={form.billing_address} onChangeText={set("billing_address")} placeholder="If different from service address" testID="customer-billing-input" />
        <Field label="Gate Code" value={form.gate_code} onChangeText={set("gate_code")} placeholder="e.g. #1234" testID="customer-gate-input" />
        <Field
          label="Pool Volume (gallons)"
          value={form.pool_gallons}
          onChangeText={set("pool_gallons")}
          placeholder="e.g. 20000"
          keyboardType="number-pad"
          testID="customer-pool-gallons-input"
        />
        <Text style={styles.hint}>Used for chemical dosing recommendations. Leave blank if unknown.</Text>
        <View style={styles.vipRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.vipLabel}>VIP customer</Text>
            <Text style={styles.vipHint}>Highlights on tech routes and dispatch board.</Text>
          </View>
          <Switch
            testID="customer-vip-toggle"
            value={!!form.is_vip}
            onValueChange={(v) => setForm((f) => ({ ...f, is_vip: v }))}
            trackColor={{ false: colors.border, true: "#F59E0B" }}
            thumbColor={form.is_vip ? "#FEF3C7" : "#f4f3f4"}
          />
        </View>
        <Field label="Notes" value={form.notes} onChangeText={set("notes")} placeholder="Access instructions, pets, preferences…" multiline testID="customer-notes-input" />
        {error ? <Text style={styles.error} testID="customer-form-error">{error}</Text> : null}
        <View style={{ height: spacing.lg }} />
        <PrimaryButton title={editing ? "Save Changes" : "Create Customer"} onPress={save} loading={busy} testID="save-customer-button" />
      </KeyboardAwareScrollView>
    </View>
  );
}

export function Field({
  label,
  multiline,
  testID,
  ...props
}: any) {
  return (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        testID={testID}
        style={[styles.input, multiline && styles.multiline]}
        placeholderTextColor={colors.muted}
        multiline={multiline}
        {...props}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  avatarRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.md },
  avatar: { width: 56, height: 56, borderRadius: 28, backgroundColor: colors.brandTertiary },
  avatarFallback: { alignItems: "center", justifyContent: "center" },
  avatarLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  avatarHint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  label: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 52,
    fontFamily: font.regular,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  multiline: { height: 100, paddingTop: spacing.md, textAlignVertical: "top" },
  error: { color: colors.error, fontFamily: font.medium, fontSize: fontSize.base, marginTop: spacing.sm },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: -spacing.sm, marginBottom: spacing.md },
  vipRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.md,
    marginBottom: spacing.md,
  },
  vipLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  vipHint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
});
