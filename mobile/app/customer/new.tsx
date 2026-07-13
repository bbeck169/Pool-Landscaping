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
  const [form, setForm] = useState({ name: "", email: "", phone: "", address: "", billing_address: "", gate_code: "", notes: "", avatar: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (id) {
      api.get(`/customers/${id}`).then((c) =>
        setForm({
          name: c.name || "", email: c.email || "", phone: c.phone || "", address: c.address || "",
          billing_address: c.billing_address || "", gate_code: c.gate_code || "", notes: c.notes || "", avatar: c.avatar || "",
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
    setBusy(true);
    setError("");
    try {
      if (editing) await api.put(`/customers/${id}`, form);
      else await api.post("/customers", form);
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
});
